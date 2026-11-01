"""Instruments attached to declared machines (docs/proposals/instruments-on-machines.md §6, unit
tests 1–4, 6–10, 12): the ops and their checks, the match, instances and the measured window, all
derived on read and never stored."""

from __future__ import annotations

import ast
import json
import time
from pathlib import Path

import pytest
from attach_seed import OWNER, SUPERVISOR, declare_postgres, every, project_with_instruments, write

from orchestra.metrics import for_project as metrics_for
from orchestra.sd.intended import IntentError
from orchestra.sd.intended import measured as m
from orchestra.sd.intended.attach import selects

ROOT = Path(__file__).resolve().parents[2]


def att(**kw) -> dict:
    return {"id": "a", "machine": "postgres", "instrument": "pg", "match": None, "instance_label": None, "state": "declared", **kw}


def view(a: dict, series, now=None, **kw) -> dict:
    return m.attachment_view(a, series, time.time() if now is None else now, "script", **kw)


# 1
def test_propose_then_confirm_records_the_attachment_in_a_new_version_and_changes_nothing_measured(tmp_path, monkeypatch):
    project = project_with_instruments(tmp_path, monkeypatch)
    write(project, "pg_up", {"server": "db-1"}, every(60, 5))
    store = metrics_for(project)
    toml, dump = project.config_file.read_text(), store.dump()
    overlay = project.overlay_file.exists() and project.overlay_file.read_text()
    aid = declare_postgres(project, match={"prefix": "pg_", "labels": {"job": "=~postgres.*"}}, instance_label="server")
    layer = project.intended.read()["layer"]
    a = layer["attachments"][aid]
    assert (a["machine"], a["instrument"], a["match"], a["instance_label"], a["state"]) == (
        "postgres", "pg", {"prefix": "pg_", "labels": {"job": "=~postgres.*"}}, "server", "declared")
    assert a["provenance"]["author"] == "supervisor" and a["confirmed"]["by"] == "owner"
    assert [e["changes"][0]["op"] for e in project.intended.journal()] == ["propose_machine", "propose_attachment", "confirm"]
    assert project.intended.current_version() == 3
    assert store.dump() == dump and project.config_file.read_text() == toml
    assert (project.overlay_file.exists() and project.overlay_file.read_text()) == overlay


# 2
def test_an_attachment_to_an_undeclared_machine_an_unknown_instrument_or_a_summed_away_label_is_refused(tmp_path, monkeypatch):
    project = project_with_instruments(tmp_path, monkeypatch)
    intended = project.intended
    with pytest.raises(IntentError, match="no declared machine"):
        intended.apply([{"op": "propose_attachment", "machine": "postgres", "instrument": "pg"}], SUPERVISOR)
    intended.apply([{"op": "propose_machine", "id": "postgres", "managed": "external"}], SUPERVISOR)
    with pytest.raises(IntentError, match="no instrument 'pgx'"):
        intended.apply([{"op": "propose_attachment", "machine": "postgres", "instrument": "pgx"}], SUPERVISOR)
    with pytest.raises(IntentError, match="summed away") as e:
        intended.apply([{"op": "propose_attachment", "machine": "postgres", "instrument": "work", "instance_label": "server"}],
                       SUPERVISOR)
    assert "orders_published_total" in str(e.value)
    with pytest.raises(IntentError, match="match"):
        intended.apply([{"op": "propose_attachment", "machine": "postgres", "instrument": "pg", "match": {"labels": {"j": "=~("}}}],
                       SUPERVISOR)
    assert intended.current_version() == 1
    ok = intended.apply([{"op": "propose_attachment", "machine": "postgres", "instrument": "work", "instance_label": "topic"},
                         {"op": "propose_attachment", "machine": "postgres", "instrument": "ci"}], SUPERVISOR)
    assert [c["id"] for c in ok["changes"]] == ["postgres_work", "postgres_ci"]
    with pytest.raises(IntentError, match="summed away"):
        intended.apply([{"op": "revise_attachment", "id": "postgres_work", "set": {"instance_label": "pod"}}], OWNER)
    intended.apply([{"op": "discard", "part": "machine", "id": "postgres"}], OWNER)
    assert intended.read()["layer"]["attachments"] == {}, "a discarded machine takes its attachments with it"


# 3
def test_discovery_is_the_same_with_and_without_attachments_and_attribute_never_reads_them(tmp_path, monkeypatch):
    from orchestra.collectors import EVENTS
    from orchestra.config import load_project
    from orchestra.metrics import Point
    from orchestra.sd.rediscover import rediscover

    project = project_with_instruments(tmp_path, monkeypatch, '\n[intended]\nmax_instances = 50\n', sources=False)
    text = project.config_file.read_text().replace("[discovery]", '[discovery]\nstrategy = "conservation"', 1)
    project.config_file.write_text(text)
    project = load_project(project.repo_root)
    now = time.time()
    store = metrics_for(project)
    pts, q, arrived, done = [], 5, 0, 0
    for i in range(720):
        t = now - 3600 + 5 * i
        a, d = (i % 3 == 0), (q > 0 and i % 4 == 0)
        q, arrived, done = q + a - d, arrived + a, done + d
        lab = {"project": project.key, "instrument": "pg", "server": "db-1"}
        pts += [Point("jobs_waiting", q, t, lab), Point("jobs_arrived_total", arrived, t, lab),
                Point("jobs_done_total", done, t, lab), Point(EVENTS, done, t, {"project": project.key, "type": "job.done",
                                                                                  "source": "postgres"})]
    store.write(pts)

    def body():
        got = rediscover(project, store, now=now).model.to_json()
        for k in ("saved_at", "as_of", "version"):
            got.pop(k, None)
        got["discovery"].pop("compute_ms", None)
        return json.dumps(got, sort_keys=True, default=str)
    first = body()
    declare_postgres(project, instance_label="server")
    assert project.intended.read()["layer"]["attachments"]
    assert body() == first
    tree = ast.parse((ROOT / "orchestra" / "sd" / "attribute.py").read_text())
    imported = [n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
    imported += [a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names]
    assert not [i for i in imported if "intended" in i], imported


# 6
def test_instances_and_the_measured_window(tmp_path, monkeypatch):
    project = project_with_instruments(tmp_path, monkeypatch)
    now = time.time()
    for s in ("db-1", "db-2"):
        write(project, "pg_up", {"server": s}, every(60, 12))
    write(project, "pg_up", {"server": "db-3"}, every(60, 12, ago=61 * 60))                # silent for 61 min
    write(project, "pg_up", {"server": "db-4"}, every(60, 3), value=0.0)                    # down, and measured
    write(project, "pg_nightly_size", {"server": "db-1"}, every(86400, 3, ago=30 * 3600))     # once a day, 30 h ago
    a = att(instance_label="server", match={"prefix": "pg_up"})
    v = view(a, m.read_own(metrics_for(project), project.key, a, now), now)
    inst = v["instances"]
    assert [(i["value"], i["measured"]) for i in inst["list"]] == [("db-1", True), ("db-2", True), ("db-3", False), ("db-4", True)]
    assert (inst["measured"], inst["quiet"]) == (3, 1)
    assert next(i for i in inst["list"] if i["value"] == "db-4")["last_value"] == 0.0, "pg_up=0 is measured, its value shown"
    nightly = view(att(match={"prefix": "pg_nightly"}), m.read_own(metrics_for(project), project.key,
                                                                    att(match={"prefix": "pg_nightly"}), now), now)
    assert nightly["measured"] and nightly["series"][0]["window_s"] == pytest.approx(2.5 * 86400)
    assert m.window([(0, 1)]) == m.FLOOR_S and m.window([(0, 1), (60, 1), (120, 1)]) == m.FLOOR_S


def test_a_new_value_of_the_instance_label_adds_an_instance_with_no_new_declaration(tmp_path, monkeypatch):
    project = project_with_instruments(tmp_path, monkeypatch)
    aid = declare_postgres(project, instance_label="server")
    a = project.intended.read()["layer"]["attachments"][aid]
    for s in ("db-1", "db-2", "db-3"):
        write(project, "pg_up", {"server": s}, every(60, 5))
    version = project.intended.current_version()
    assert view(a, m.read_own(metrics_for(project), project.key, a))["instances"]["measured"] == 3
    write(project, "pg_up", {"server": "db-9"}, every(60, 2))
    assert view(a, m.read_own(metrics_for(project), project.key, a))["instances"]["measured"] == 4
    assert project.intended.current_version() == version


# 7
def test_two_attachments_spelling_one_replica_twice_are_never_unioned():
    now = time.time()
    a1 = view(att(id="a1", instance_label="server"), [("pg_up", {"server": "db-1"}, [(now - 60, 1), (now, 1)])], now)
    a2 = view(att(id="a2", instance_label="instance"), [("pg_stat", {"instance": "db-1:9187"}, [(now - 60, 1), (now, 1)])], now)
    got = m.machine_measured([a1, a2])
    assert a1["instances"]["measured"] == 1 and a2["instances"]["measured"] == 1
    assert got["instances"] == 1 and got["measured"] and got["instruments"] == ["pg"]


# 8
def test_an_instance_label_with_more_values_than_the_cap_lists_none():
    now = time.time()
    series = [("http_requests", {"pod": f"p{i}"}, [(now, 1)]) for i in range(51)]
    v = view(att(instance_label="pod"), series, now)
    assert v["instances"]["too_many"] and v["instances"]["list"] is None
    assert v["instances"]["note"] == "51 values: too many for instances"
    assert view(att(instance_label="pod"), series[:50], now)["instances"]["measured"] == 50


# 9
def test_one_scrape_two_machines_each_sees_its_own_series_and_shared_ones_are_marked():
    now = time.time()
    series = [("build_seconds", {"job": "jenkins"}, [(now, 1)]), ("build_seconds", {"job": "deploy-web"}, [(now, 2)]),
              ("build_seconds", {"job": "deploy-api"}, [(now, 3)]), ("host_cpu", {"job": "jenkins", "role": "deploy-x"}, [(now, 4)])]
    jenkins = view(att(id="j", machine="jenkins", instrument="ci", match={"labels": {"job": "jenkins"}}), series, now)
    deploys = view(att(id="d", machine="deployer", instrument="ci", match={"labels": {"job": "=~deploy-.*"}}), series, now)
    cpu = view(att(id="c", machine="deployer", instrument="ci", match={"prefix": "host_"}), series, now)
    m.mark_shared([jenkins, deploys, cpu])
    assert [r["labels"]["job"] for r in jenkins["series"]] == ["jenkins", "jenkins"]
    assert sorted(r["labels"]["job"] for r in deploys["series"]) == ["deploy-api", "deploy-web"]
    shared = [r for r in jenkins["series"] if r["shared_with"]]
    assert [r["name"] for r in shared] == ["host_cpu"] and shared[0]["shared_with"] == ["deployer"]
    assert jenkins["shared"] and cpu["shared"] and not deploys["shared"]


# 10
def test_a_sources_label_aliases_match_both_spellings_and_a_renamed_job_goes_quiet():
    now = time.time()
    aliases = {"service": "service", "svc": "service"}
    old = [(now - 3 * 3600 + 60 * i, 1.0) for i in range(60)]                 # the old job, last point two hours ago
    new = [(now - 3600 + 60 * i, 1.0) for i in range(60)]
    series = [("work:build_seconds", {"svc": "gate", "job": "land"}, old), ("work:build_seconds", {"service": "gate", "job": "land-v2"}, new),
              ("work:build_seconds", {"svc": "checkout", "job": "land"}, new)]
    a = att(instrument="work", match={"prefix": "build_", "labels": {"service": "gate"}}, instance_label="job")
    v = m.attachment_view(a, series, now, "source", aliases=aliases, strip="work:")
    assert [(r["labels"].get("job"), r["measured"]) for r in v["series"]] == [("land", False), ("land-v2", True)]
    assert [(i["value"], i["measured"]) for i in v["instances"]["list"]] == [("land", False), ("land-v2", True)]
    assert selects("work:build_seconds", {"svc": "gate"}, {"prefix": "work:build_", "labels": {"service": "gate"}}, aliases, "work:")
    assert not selects("work:build_seconds", {"svc": "gate"}, {"labels": {"service": "gate"}})     # no aliases: svc is not service


# 12
def test_an_attachment_that_matches_nothing_is_on_the_comparison_and_the_flag_is_never_stored(tmp_path, monkeypatch):
    project = project_with_instruments(tmp_path, monkeypatch)
    aid = declare_postgres(project, match={"labels": {"job": "nothing-has-this"}})
    a = project.intended.read()["layer"]["attachments"][aid]
    v = view(a, m.read_own(metrics_for(project), project.key, a))
    assert not v["measured"] and v["status"] == "nothing" and v["comparison"] == m.NOTHING
    assert m.comparison(False, m.machine_measured([v])) == m.NOTHING
    assert m.comparison(False, m.machine_measured([])) == m.NEITHER
    assert m.comparison(True, m.machine_measured([v])) == m.HEARD
    stored = [p.read_text() for p in (project.state_dir / "model" / "intended").iterdir() if p.is_file()]
    assert not any('"measured"' in t or '"last_measured"' in t or m.NOTHING in t for t in stored)
    with pytest.raises(IntentError, match="measured"):
        project.intended.apply([{"op": "revise_attachment", "id": aid, "set": {"instance_label": "x"}, "measured": True}], OWNER)
    design = project.intended.design()
    assert {"what": m.NOTHING, "part": "attachment", "id": aid, "machine": "postgres"} in design["open"]
    assert {"what": m.NEITHER, "part": "machine", "id": "postgres"} in design["open"]


def test_a_proposed_attachment_shows_its_series_and_measures_nothing():
    now = time.time()
    v = view(att(state="proposed"), [("pg_up", {}, [(now, 1)])], now)
    assert v["measured"] and v["comparison"] is None
    got = m.machine_measured([v])
    assert not got["measured"] and got["last_measured"] is None and got["instances"] == 0
