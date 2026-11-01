"""Attachments on the web server (docs/proposals/instruments-on-machines.md §6, unit tests 5, 9, 11,
13, 14): ``measured`` and ``comparison`` on ``/api/machines``, ``hung_on`` on ``/api/instruments``,
from the background read, never making a machine seen or active."""

from __future__ import annotations

import time

from attach_seed import OWNER, SUPERVISOR, declare_postgres, every, project_with_instruments, write
from fastapi.testclient import TestClient

from orchestra.events import Events
from orchestra.sd.intended import measured as m


def client(project):
    from orchestra.web.app import create_app
    from orchestra.web.auth import bearer
    return TestClient(create_app(project), headers=bearer(project))


def poll(c, path, want, seconds: float = 20.0):
    deadline = time.time() + seconds
    got = None
    while time.time() < deadline:
        got = c.get(path).json()
        if got.get("ok") and want(got):
            return got
        time.sleep(0.2)
    raise AssertionError(got)


def machine(got, mid):
    return next(x for x in got["machines"] if x["id"] == mid)


def measured_read(got, mid="postgres"):
    mm = machine(got, mid).get("measured") or {}
    return mm.get("attachments") and not mm.get("unknown")


# 5, and 11
def test_a_measured_machine_with_no_events_is_never_seen_or_active_until_heard(tmp_path, monkeypatch):
    project = project_with_instruments(tmp_path, monkeypatch)
    for s in ("db-1", "db-2"):
        write(project, "pg_connections", {"server": s}, every(10, 6))
    declare_postgres(project, instance_label="server")
    c = client(project)
    got = poll(c, "/api/machines", measured_read)
    pg = machine(got, "postgres")
    assert pg["last_seen"] is None and pg["active"] is False and pg["unseen"] and pg["flows"] == []
    assert pg["measured"]["measured"] and pg["measured"]["last_measured"] and pg["measured"]["instances"] == 2
    assert pg["measured"]["instruments"] == ["pg"] and pg["comparison"] == m.MEASURED_NEVER_HEARD
    a = pg["measured"]["attachments"][0]
    assert a["kind"] == "script" and [i["value"] for i in a["instances"]["list"]] == ["db-1", "db-2"]
    assert all(x["measured"] is None for x in got["machines"] if x["id"] != "postgres")
    run = [x for x in got["machines"] if not x.get("unseen") and (x.get("mode") == "continuous" or x.get("active"))]
    assert "postgres" not in [x["id"] for x in run], "the Dashboard's running panel never lists it for being measured"

    Events(project.events_file, source="postgres/db-1").publish("orchestra.machine.started", {"mode": "continuous"})
    got = poll(c, "/api/machines", lambda g: not machine(g, "postgres").get("unseen") and measured_read(g))
    pg = machine(got, "postgres")
    assert pg["last_seen"] is not None and pg["intent"]["heard"] and pg["comparison"] == m.HEARD
    assert pg["measured"]["instances"] == 2 and [i["id"] for i in pg["instances"]] == ["db-1"], "the bus's instances are its own"


# 9, and the Instruments page
def test_the_instruments_page_shows_which_declared_machines_each_instrument_is_hung_on(tmp_path, monkeypatch):
    project = project_with_instruments(tmp_path, monkeypatch)
    for job in ("jenkins", "deploy-web"):
        write(project, "build_seconds", {"job": job}, every(30, 4), instrument="ci")
    write(project, "host_cpu", {"job": "jenkins"}, every(30, 4), instrument="ci")
    intended = project.intended
    intended.apply([{"op": "propose_machine", "id": "jenkins", "managed": "external"},
                    {"op": "propose_machine", "id": "deployer", "managed": "external"},
                    {"op": "propose_attachment", "machine": "jenkins", "instrument": "ci", "match": {"labels": {"job": "jenkins"}}},
                    {"op": "propose_attachment", "machine": "deployer", "instrument": "ci", "match": {"labels": {"job": "=~deploy-.*"}}},
                    {"op": "propose_attachment", "machine": "deployer", "instrument": "ci", "match": {"prefix": "host_"}}], SUPERVISOR)
    c = client(project)
    got = poll(c, "/api/instruments", lambda g: all(h["series"] is not None for r in g["instruments"] for h in r.get("hung_on", [])))
    ci = next(r for r in got["instruments"] if r["name"] == "ci")
    hung = {(h["machine"], h["shown"]): h for h in ci["hung_on"]}
    assert set(hung) == {("jenkins", '{job="jenkins"}'), ("deployer", '{job=~"deploy-.*"}'), ("deployer", "host_*")}
    assert hung[("jenkins", '{job="jenkins"}')]["shared_with"] == ["deployer"]
    assert hung[("deployer", "host_*")]["shared"] and not hung[("deployer", '{job=~"deploy-.*"}')]["shared"]
    assert all(h["state"] == "proposed" for h in ci["hung_on"])
    assert next(r for r in got["instruments"] if r["name"] == "pg")["hung_on"] == []
    js = poll(c, "/api/machines", lambda g: measured_read(g, "jenkins"))
    assert [r["labels"]["job"] for r in machine(js, "jenkins")["measured"]["attachments"][0]["series"]] == ["jenkins", "jenkins"]
    assert machine(js, "jenkins")["comparison"] == m.NEITHER, "a proposed attachment measures nothing"


# 13
def test_with_the_metrics_store_unreachable_both_routes_answer_in_time_with_series_unknown(tmp_path, monkeypatch):
    project = project_with_instruments(tmp_path, monkeypatch)
    declare_postgres(project)
    monkeypatch.setenv("ORCHESTRA_METRICS_URL", "http://127.0.0.1:9")     # nothing listens there
    c = client(project)
    t = time.monotonic()
    got = poll(c, "/api/machines", lambda g: "postgres" in [x["id"] for x in g["machines"]])
    pg = machine(got, "postgres")
    assert pg["measured"]["attachments"][0]["status"] == m.UNKNOWN and pg["comparison"] == m.UNKNOWN
    ins = c.get("/api/instruments").json()
    assert next(r for r in ins["instruments"] if r["name"] == "pg")["hung_on"][0]["status"] == m.UNKNOWN
    assert time.monotonic() - t < 15


# 14
def test_page_controls_never_write_an_attachment_and_a_request_publishes_one_event(tmp_path, monkeypatch):
    project = project_with_instruments(tmp_path, monkeypatch)
    project.intended.apply([{"op": "propose_machine", "id": "postgres", "managed": "external"},
                            {"op": "propose_attachment", "machine": "postgres", "instrument": "pg"}], SUPERVISOR)
    c = client(project)
    version = project.intended.current_version()
    for control in ("confirm", "discard"):
        r = c.post("/api/intended/control", json={"control": control, "part": "attachment", "id": "postgres_pg"})
        assert r.status_code == 400
    got = c.post("/api/intended/request", json={"control": "confirm", "part": "attachment", "id": "postgres_pg", "from": "Measured by"})
    assert got.json()["ok"]
    evs = [e for e in Events(project.events_file).read(0, 1000)[0] if e["type"] == "orchestra.intent.requested"]
    assert len(evs) == 1 and evs[0]["source"] == "owner" and evs[0]["data"]["part"] == "attachment"
    assert project.intended.current_version() == version
    assert project.intended.read()["layer"]["attachments"]["postgres_pg"]["state"] == "proposed"
    project.intended.apply([{"op": "confirm", "part": "attachment", "id": "postgres_pg"}], {**OWNER, "request": evs[0]["id"]})
    assert project.intended.read()["layer"]["attachments"]["postgres_pg"]["state"] == "declared"


class FakeCatalogue:
    """A source's reads, as ``Catalogue.selected`` answers them: a Jenkins job renamed an hour ago
    (``land`` → ``land-v2``), its series spelled ``svc`` before and ``service`` after."""

    def __init__(self, specs, now):
        self.specs, self.asked = specs, []
        old = [[now - 7200 + 60 * i, 1.0] for i in range(50)]
        new = [[now - 3000 + 60 * i, 1.0] for i in range(50)]
        self.rows = [{"name": "work:build_seconds", "labels": {"svc": "gate", "job": "land"}, "points": old},
                     {"name": "work:build_seconds", "labels": {"service": "gate", "job": "land-v2"}, "points": new},
                     {"name": "work:build_seconds", "labels": {"service": "checkout", "job": "land"}, "points": new},
                     {"name": "work:queue_depth", "labels": {"service": "gate"}, "points": new}]

    def selected(self, name, keep, start, end, step):
        from types import SimpleNamespace
        self.asked.append((name, keep(SimpleNamespace(name="build_seconds")), keep(SimpleNamespace(name="queue_depth"))))
        return self.rows, None


def test_a_sources_attachment_matches_both_spellings_and_follows_a_renamed_job(tmp_path, monkeypatch):
    from orchestra.sources.spec import for_project
    from orchestra.web.measured import merge_machines, read_all

    project = project_with_instruments(tmp_path, monkeypatch)
    aid = declare_postgres(project, instrument="work", match={"prefix": "work:build_", "labels": {"service": "gate"}},
                           instance_label="job")
    layer = project.intended.read()["layer"]
    now = time.time()
    cat = FakeCatalogue(for_project(project), now)
    cache = read_all(project, None, cat, layer, now)
    assert cat.asked == [("work", True, False)], "only the definitions the match's prefix names are read"
    out = {"machines": [{"id": "postgres", "intent": {"heard": False}}]}
    merge_machines(out, project, layer, cache, now)
    a = out["machines"][0]["measured"]["attachments"][0]
    assert a["id"] == aid and a["kind"] == "source"
    assert [(r["labels"]["job"], r["measured"]) for r in a["series"]] == [("land", False), ("land-v2", True)]
    assert [(i["value"], i["measured"]) for i in a["instances"]["list"]] == [("land", False), ("land-v2", True)]
