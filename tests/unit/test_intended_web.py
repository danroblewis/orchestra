"""The intended model's routes on the web server and the events endpoint, and the host's
announcement (docs/proposals/intended-model.md §5, §6; §10 tests 1, 15, 16, 18, 19, 21, 23, 24,
33, 34): page marks stored by key, requests naming something declared, one announcement per
element, a corrupt ``dN`` answered as unreadable, intent events never hand-offs."""

import json
import time

from fastapi.testclient import TestClient
from intended_seed import project_at, seed

from orchestra.events import Events
from orchestra.sd.store import ModelStore


def client(project):
    from orchestra.web.app import create_app
    from orchestra.web.auth import bearer
    return TestClient(create_app(project), headers=bearer(project))


def machines(c, want=lambda got: True):
    deadline = time.time() + 15
    while time.time() < deadline:
        got = c.get("/api/machines").json()
        if got.get("ok") and want(got):
            return got
        time.sleep(0.2)
    raise AssertionError(got)


def files(project):
    toml = project.config_file.read_text()
    versions = sorted(p.name for p in ModelStore.for_state(project.state_dir).dir.glob("v*.json"))
    return toml, versions


def test_15_the_page_controls_accept_exactly_the_observations(tmp_path, monkeypatch):
    project = project_at(tmp_path, monkeypatch)
    seed(project)
    c = client(project)
    before = files(project)
    ok = c.post("/api/intended/control", json={"control": "expect", "part": "stock", "id": "acceptance_tests_passing",
                                               "from": "changes since v1"}).json()
    assert ok["ok"] and ok["version"] == 3
    j = project.intended.journal(after=2)[0]
    assert j["provenance"]["via"] == "page" and j["provenance"]["control"] == "expect" and j["provenance"]["from"] == "changes since v1"
    for bad in ({"control": "confirm", "part": "machine", "id": "feature_count_improver"},
                {"control": "discard", "part": "attachment", "id": "x"},
                {"control": "expect", "part": "stock", "id": "k", "value": 3},
                {"control": "rename", "part": "stock", "id": "features"}):
        assert c.post("/api/intended/control", json=bad).status_code == 400, bad
    assert c.post("/api/intended/control", json={"control": "discard", "part": "stock", "id": "features"}).status_code == 422
    assert files(project) == before and project.intended.current_version() == 3


def test_a_page_mark_is_stored_by_key_and_an_unknown_target_is_refused(tmp_path, monkeypatch):
    project = project_at(tmp_path, monkeypatch)
    seed(project)
    c = client(project)
    got = c.post("/api/intended/control", json={"control": "expect", "part": "flow", "id": "done_to_acceptance"}).json()
    assert got["ok"]
    flow_key = 'tasks_tickets{state="DONE"} -> acceptance_tests_passing'
    marks = project.intended.read()["layer"]["marks"]["expected"]
    assert list(marks) == [flow_key]
    b = c.get("/api/dynamics/model").json()["model"]["intended"]
    assert next(e for e in b["expected"] if e["key"] == flow_key)["present"] and b["marks"]["flows"]["done_to_acceptance"] == ["expected", "new"]
    assert c.post("/api/intended/control", json={"control": "ignore", "part": "stock", "key": "acceptance_tests_passing"}).json()["ok"]
    n = project.intended.current_version()
    for bad in ({"control": "expect", "part": "stock", "id": "no_such_stock"},
                {"control": "ignore", "part": "flow", "key": "a typo -> nowhere"},
                {"control": "unexpect", "part": "flow", "id": "no_such_flow"},
                {"control": "expect", "part": "stock"}):
        r = c.post("/api/intended/control", json=bad)
        err = r.json()["error"]
        assert r.status_code == 400 and ("latest model" in err or "names its part" in err), bad
    assert project.intended.current_version() == n
    assert c.post("/api/intended/control", json={"control": "unexpect", "part": "flow", "key": flow_key}).json()["ok"]


def test_15_16_a_request_publishes_one_event_from_owner_and_writes_no_version(tmp_path, monkeypatch):
    project = project_at(tmp_path, monkeypatch)
    seed(project)
    c = client(project)
    before = files(project)
    got = c.post("/api/intended/request", json={"control": "confirm", "part": "machine", "id": "feature_count_improver",
                                               "from": "E1 status strip"}).json()
    assert got["ok"]
    evs = [e for e in Events(project.events_file).read(0, 10_000)[0] if e["type"] == "orchestra.intent.requested"]
    assert len(evs) == 1 and evs[0]["source"] == "owner" and evs[0]["id"] == got["event"]
    assert evs[0]["data"] == {"control": "confirm", "part": "machine", "id": "feature_count_improver", "change": None,
                              "from": "E1 status strip"}
    assert project.intended.current_version() == 2 and files(project) == before
    assert c.post("/api/intended/request", json={"control": "expect", "part": "stock", "id": "x"}).status_code == 400
    m = next(x for x in machines(c)["machines"] if x["id"] == "feature_count_improver")
    assert m["intent"]["requested"]["event"] == got["event"]
    project.intended.apply([{"op": "declare_event", "type": "work.requested", "description": "asks for work"}],
                           {"author": "supervisor", "source": "supervisor", "request": got["event"]})
    m = next(x for x in machines(c)["machines"] if x["id"] == "feature_count_improver")
    assert m["intent"]["requested"]["event"] == got["event"]                 # citing it is no answer: only the op asked for is
    project.intended.apply([{"op": "confirm", "part": "machine", "id": "feature_count_improver"}],
                           {"author": "supervisor", "source": "supervisor", "request": got["event"]})
    m = next(x for x in machines(c)["machines"] if x["id"] == "feature_count_improver")
    assert m["intent"]["requested"] is None and m["intent"]["state"] == "declared"


def test_a_request_names_something_declared_and_carries_no_values(tmp_path, monkeypatch):
    project = project_at(tmp_path, monkeypatch)
    seed(project)
    c = client(project)
    for body, status in (({"control": "confirm", "part": "machine", "id": "nobody"}, 404),
                         ({"control": "confirm", "part": "machine", "id": "feature_count_improver", "change": "c9.0"}, 404),
                         ({"control": "switch_kind", "part": "attachment", "id": "x"}, 400),
                         ({"control": "confirm", "part": "machine", "id": "feature_count_improver", "from": {"a": 1}}, 400),
                         ({"control": "confirm", "part": "machine", "id": "feature_count_improver", "change": 3}, 400)):
        assert c.post("/api/intended/request", json=body).status_code == status, body
    assert not [e for e in Events(project.events_file).read(0, 10_000)[0] if e["type"] == "orchestra.intent.requested"]
    assert not (project.intended.dir / "requests.jsonl").exists()
    got = project.intended.apply([{"op": "revise_machine", "id": "feature_count_improver", "set": {"title": "FCI"}}],
                                 {"author": "supervisor"})
    change = got["changes"][0]["change"]
    assert c.post("/api/intended/request", json={"control": "discard", "part": "machine", "id": "feature_count_improver",
                                                 "change": change}).json()["ok"]


def test_a_declared_machine_is_heard_once_its_source_publishes_and_aliases_join(tmp_path, monkeypatch):
    project = project_at(tmp_path, monkeypatch)
    seed(project)
    project.intended.apply([{"op": "propose_machine", "id": "nightly_metrics", "kind": "programmatic", "managed": "external",
                             "engagement": {"mode": "scheduled", "at": "02:00"}, "receives": ["build.done"]},
                            {"op": "alias", "machine": "nightly_metrics", "observed": "jenkins.nightly"}], {"author": "supervisor"})
    c = client(project)
    got = machines(c)
    m = next(x for x in got["machines"] if x["id"] == "feature_count_improver")
    assert m["unseen"] and not m["intent"]["heard"] and m["kind"] == "universal"
    # a declaration is not an observation: no subscribes, publishes or mode of its own (rule 2 as amended)
    assert m["subscribes"] == [] and m["publishes"] == [] and m["mode"] is None
    assert m["intent"]["receives"] == ["session.settled", "task.reported"] and m["intent"]["engagement"] == {"mode": "continuous"}
    ev = Events(project.events_file, source="feature_count_improver")
    ev.publish("orchestra.machine.started", {"mode": "continuous", "kind": "agent", "listens_for": []})
    got = machines(c, lambda g: any(x["id"] == "feature_count_improver" and not x.get("unseen") for x in g["machines"]))
    m = next(x for x in got["machines"] if x["id"] == "feature_count_improver")
    assert m["intent"]["heard"] and m["kind"] == "agent" and m["last_seen"] is not None
    assert all(x["intent"] is None for x in got["machines"] if x["id"] not in ("feature_count_improver", "nightly_metrics"))
    out = {"machines": [{"id": "jenkins.nightly", "unseen": False}], "edges": []}
    from orchestra.sd.intended.machines_view import merge
    merge(out, project.intended)
    assert out["machines"][0]["intent"]["heard"] and len(out["machines"]) == 2  # the alias and the other declared one
    assert {"from": "build.done", "to": "jenkins.nightly", "kind": "subscribes", "state": "proposed", "observed": False,
            "gone": False} in out["intended_edges"]               # on the drawn node, not the declared id


def picked(evs, selector):
    import fnmatch

    from orchestra.sd.eras import parse
    ty, fields = parse(selector)
    return [e for e in evs if fnmatch.fnmatchcase(e["type"], ty) and all(fnmatch.fnmatchcase(e.get(k) or "", g) for k, g in fields.items())]


def test_18_each_call_is_announced_once_by_the_host_even_one_written_while_it_was_down(tmp_path, monkeypatch):
    from orchestra.sd.intended.announce import announce
    project = project_at(tmp_path, monkeypatch)
    seed(project)
    ev = Events(project.events_file)
    assert announce(project.intended, ev.publish) == [1, 2]
    assert announce(project.intended, ev.publish) == []
    project.intended.apply([{"op": "revise_machine", "id": "feature_count_improver", "set": {"title": "FCI"}}],
                           {"author": "owner", "source": "supervisor", "quote": "call it FCI"})
    assert announce(project.intended, ev.publish) == [3]
    evs = [e for e in ev.read(0, 1000)[0] if e["type"] == "orchestra.intent.changed"]
    assert [e["data"]["version"] for e in evs] == [1, 2, 3] and all(e["source"] == "orchestra-host" for e in evs)
    assert [e["data"]["version"] for e in picked(evs, "orchestra.intent.changed:subject=machine:feature_count_improver")] == [2, 3]


def test_a_call_touching_two_machines_is_announced_once_for_each(tmp_path, monkeypatch):
    from orchestra.sd.intended.announce import announce
    project = project_at(tmp_path, monkeypatch)
    project.intended.apply([{"op": "propose_machine", "id": "fci"}, {"op": "propose_machine", "id": "worker"},
                            {"op": "set_expected_effect", "machine": "fci", "horizon_s": 60, "edits": []}], {"author": "supervisor"})
    ev = Events(project.events_file)
    assert announce(project.intended, ev.publish) == [1]
    evs = [e for e in ev.read(0, 1000)[0] if e["type"] == "orchestra.intent.changed"]
    assert [e["subject"] for e in evs] == ["machine:fci", "machine:worker"]
    assert [c["change"] for c in evs[0]["data"]["ops"]] == ["c1.0", "c1.2"] and [c["change"] for c in evs[1]["data"]["ops"]] == ["c1.1"]
    worker = picked(evs, "orchestra.intent.changed:subject=machine:worker")
    assert len(worker) == 1 and worker[0]["data"]["version"] == 1 and worker[0]["data"]["via"] == "plugin"


def test_18_the_hosts_look_announces_and_writes_the_live_diff_after_a_declaration(tmp_path, monkeypatch):
    from orchestra.host import Host

    project = project_at(tmp_path, monkeypatch)
    seed(project)
    host = Host(project)
    published = []

    class Fake:
        def publish(self, type_, data, **kw):
            published.append((type_, kw.get("subject"), data["version"]))
            return {"id": str(len(published))}
    host.events = Fake()
    diff = project.intended.dir / "diff"
    host._intent()
    assert published == [("orchestra.intent.changed", "stock:features", 1), ("orchestra.intent.changed", "machine:feature_count_improver", 2)]
    assert [f.name for f in diff.glob("*.json")] == ["d2-v2-v1-none-h3.json"]
    host._intent()
    assert len(published) == 2


def test_heard_is_read_now_even_from_a_cached_diff_and_a_slow_store_is_named(tmp_path, monkeypatch):
    from orchestra.sd.intended.view import dynamics_block

    project = project_at(tmp_path, monkeypatch)
    store = seed(project)
    c = client(project)
    c.get("/api/dynamics/model")
    assert list((store.dir / "intended" / "diff").glob("*.json"))
    Events(project.events_file, source="feature_count_improver").publish("work.requested", {})
    m = next(x for x in machines(c, lambda g: any(x["id"] == "feature_count_improver" and not x.get("unseen")
                                                  for x in g["machines"]))["machines"] if x["id"] == "feature_count_improver")
    assert m["intent"]["heard"]

    class Slow:
        def series(self, *a, **k):
            time.sleep(1)
            return []
    b = dynamics_block(store.intended(), metrics=Slow(), limit_s=0.05, hold=3)
    assert b["missing"] == ["recording features.acceptance"]


def test_the_script_is_read_only_inside_the_repository_or_the_state_directory(tmp_path, monkeypatch):
    project = project_at(tmp_path, monkeypatch)
    seed(project)
    (project.repo_root / "tools").mkdir()
    (project.repo_root / "tools" / "acc.sh").write_text("pytest tests/acceptance --junitxml\n")
    outside = tmp_path / "elsewhere.sh"
    outside.write_text("secret\n")
    project.config_file.write_text(project.config_file.read_text() + f'''
[[collect]]
name = "features.acceptance"
command = "sh tools/acc.sh"
every = "15m"

[[collect]]
name = "features.outside"
command = "sh {outside}"
''')
    project.reload_config()
    c = client(project)
    got = c.get("/api/intended/script?instrument=features.acceptance").json()
    assert got["ok"] and got["script"]["text"].startswith("pytest") and got["entry"]["every"] == "15m"
    bad = c.get("/api/intended/script?instrument=features.outside")
    assert bad.status_code == 403 and bad.json() == {"ok": False, "error": bad.json()["error"]} and "outside the project" in bad.json()["error"]
    none = c.get("/api/intended/script?instrument=nothing")
    assert none.status_code == 404 and not none.json()["ok"]


def test_the_script_is_found_past_an_interpreter_outside_the_project(tmp_path, monkeypatch):
    import sys

    project = project_at(tmp_path, monkeypatch)
    (project.repo_root / "tools").mkdir()
    (project.repo_root / "tools" / "acc.sh").write_text("pytest tests/acceptance\n")
    (project.repo_root / "scripts").mkdir()
    (project.repo_root / "scripts" / "x.py").write_text("print(41)\n")
    project.config_file.write_text(project.config_file.read_text() + f'''
[[collect]]
name = "by.sh"
command = "/bin/sh tools/acc.sh"

[[collect]]
name = "by.python"
command = ["{sys.executable}", "scripts/x.py"]
''')
    project.reload_config()
    c = client(project)
    assert c.get("/api/intended/script?instrument=by.sh").json()["script"]["text"].startswith("pytest")
    assert c.get("/api/intended/script?instrument=by.python").json()["script"]["text"] == "print(41)\n"


def test_a_non_integer_parameter_is_a_400_with_the_usual_body(tmp_path, monkeypatch):
    project = project_at(tmp_path, monkeypatch)
    seed(project)
    c = client(project)
    for path in ("/api/intended?version=abc", "/api/intended/journal?after=x", "/api/intended/diff?d=1.5"):
        r = c.get(path)
        assert r.status_code == 400 and r.json() == {"ok": False, "error": r.json()["error"]}, path
    assert [e["seq"] for e in c.get("/api/intended/journal?after=1").json()["journal"]] == [2]
    assert c.get("/api/intended/diff?d=9").status_code == 404


def test_34_the_core_page_answers_with_the_intended_directory_corrupt_or_locked(tmp_path, monkeypatch):
    import fcntl

    project = project_at(tmp_path, monkeypatch)
    d = ModelStore.for_state(project.state_dir).dir / "intended"
    d.mkdir(parents=True)
    (d / "d0001.json").write_text("{not json")
    (d / "journal.jsonl").write_text("garbage\n")
    with open(ModelStore.for_state(project.state_dir).dir / "intended.lock", "w") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        c = client(project)
        assert c.get("/api/core").status_code == 200
        assert c.get("/api/intended").status_code == 500 and "d1 cannot be read" in c.get("/api/intended").json()["error"]


def test_a_corrupt_or_missing_version_is_answered_on_every_route(tmp_path, monkeypatch):
    from orchestra.endpoint.api import handle

    project = project_at(tmp_path, monkeypatch)
    seed(project)
    c = client(project)
    assert c.get("/api/intended?version=9").status_code == 404
    (project.intended.dir / "d0002.json").write_text("{not json")
    for path in ("/api/intended", "/api/intended/design"):
        r = c.get(path)
        assert r.status_code == 500 and r.json() == {"ok": False, "error": r.json()["error"]} and "d2 cannot be read" in r.json()["error"]
    status, out = handle(project, "GET", "/intended/design", "", b"")
    assert status == 500 and "d2 cannot be read" in out["error"]
    status, out = handle(project, "POST", "/intended", "", json.dumps({"source": "supervisor", "ops": [
        {"op": "declare_stock", "name": "Bugs"}]}).encode())
    assert status == 500 and "d2 cannot be read" in out["error"]
    assert "cannot be read" in c.get("/api/dynamics/model").json()["model"]["intended"]["error"]


def test_a_bad_version_parameter_is_a_400_or_404(tmp_path, monkeypatch):
    project = project_at(tmp_path, monkeypatch)
    seed(project)
    c = client(project)
    assert c.get("/api/intended/diff?v=abc").status_code == 400
    assert c.get("/api/intended/diff?v=99").status_code == 404
    assert c.get("/api/intended/diff?since=abc").status_code == 400
    assert c.get("/api/intended/diff?v=2&since=99").status_code == 404
    assert c.get("/api/intended/diff?v=2&since=off").json()["since"] is None
    assert "since is a version" in c.get("/api/dynamics/model?since=abc").json()["model"]["intended"]["error"]


def test_the_events_endpoint_takes_one_call_and_refuses_with_its_index(tmp_path, monkeypatch):
    from orchestra.endpoint.api import handle

    project = project_at(tmp_path, monkeypatch)
    body = {"source": "supervisor", "author": "owner", "quote": "I'm going to create a Features stock.",
            "ops": [{"op": "declare_stock", "name": "Features"}]}
    status, out = handle(project, "POST", "/intended", "", json.dumps(body).encode())
    assert status == 200 and out["ok"] and out["version"] == 1
    body["ops"] = [{"op": "declare_effect", "name": "Latency"}, {"op": "expect", "part": "stock"},
                   {"op": "declare_stock", "name": "x", "present": True}]
    status, out = handle(project, "POST", "/intended", "", json.dumps(body).encode())
    assert status == 422 and out == {"ok": False, "error": out["error"], "index": 1}
    status, out = handle(project, "GET", "/intended/design", "", b"")
    assert status == 200 and out["version"] == 1


def test_design_stays_under_20_kb_for_100_elements(tmp_path, monkeypatch):
    from orchestra.endpoint.api import handle

    project = project_at(tmp_path, monkeypatch)
    seed(project)
    owner = {"author": "owner", "source": "supervisor", "quote": "track these"}
    ops = [{"op": "declare_stock", "name": f"Stock number {i}", "note": "the owner's words, briefly"} for i in range(60)]
    ops += [{"op": "declare_flow", "from": f"stock_number_{i}", "to": f"stock_number_{i + 1}"} for i in range(20)]
    ops += [{"op": "propose_machine", "id": f"machine_{i}", "receives": ["a.b"], "guessed": ["receives[0]"]} for i in range(18)]
    project.intended.apply(ops, owner)
    status, out = handle(project, "GET", "/intended/design", "", b"")
    assert status == 200 and len(out["elements"]) >= 100 and len(json.dumps(out)) < 20_000, len(json.dumps(out))


def test_33_design_lists_a_declared_machine_neither_heard_nor_measured(tmp_path, monkeypatch):
    from orchestra.collectors import EVENTS
    from orchestra.metrics import Point
    from orchestra.metrics import for_project as metrics_for

    project = project_at(tmp_path, monkeypatch)
    seed(project)
    project.intended.apply([{"op": "propose_machine", "id": "nightly_metrics"}, {"op": "propose_machine", "id": "still_proposed"}],
                           {"author": "supervisor"})
    project.intended.apply([{"op": "confirm", "part": "machine", "id": "feature_count_improver"},
                            {"op": "confirm", "part": "machine", "id": "nightly_metrics"}], {"author": "owner", "source": "supervisor", "quote": "yes"})
    neither = "declared, neither heard nor measured"
    items = [o for o in project.intended.design()["open"] if o["what"] == neither]
    assert items == [{"what": neither, "part": "machine", "id": "feature_count_improver"},
                     {"what": neither, "part": "machine", "id": "nightly_metrics"}]
    metrics_for(project).write([Point(EVENTS, 1.0, time.time(), {"project": project.key, "type": "work.requested",
                                                                 "source": "feature_count_improver/1"})])
    assert [o["id"] for o in project.intended.design()["open"] if o["what"] == neither] == ["nightly_metrics"]
    c = client(project)
    got = machines(c)
    assert {m["id"]: m["comparison"] for m in got["machines"] if m.get("intent")} == {
        "feature_count_improver": neither, "nightly_metrics": neither, "still_proposed": neither}
    Events(project.events_file, source="feature_count_improver").publish("work.requested", {})
    got = machines(c, lambda g: any(x["id"] == "feature_count_improver" and not x.get("unseen") for x in g["machines"]))
    assert next(m for m in got["machines"] if m["id"] == "feature_count_improver")["comparison"] == "heard"
    assert all(m["comparison"] is None for m in got["machines"] if not m.get("intent"))


def test_design_and_the_machines_page_agree_on_a_machine_heard_by_counted_traffic(tmp_path, monkeypatch):
    import orchestra.web.app as app_module

    def counted(view, summary, now):
        view["machines"].append({"id": "jira.bot", "bootstrap": False, "mode": None, "kind": None, "package": None, "about": {},
                                 "publishes": [], "subscribes": [], "flows": [], "logs": [], "instances": [], "first_seen": None,
                                 "last_seen": None, "active": False, "counted_only": True})
    monkeypatch.setattr(app_module, "merge_counted", counted)
    project = project_at(tmp_path, monkeypatch)
    seed(project)
    project.intended.apply([{"op": "confirm", "part": "machine", "id": "feature_count_improver"},
                            {"op": "alias", "machine": "feature_count_improver", "observed": "jira.bot"}],
                           {"author": "owner", "source": "supervisor", "quote": "yes, the bot"})
    c = client(project)
    m = next(x for x in machines(c)["machines"] if x["id"] == "jira.bot")
    assert m["intent"]["heard"] and m["comparison"] == "heard"
    d = c.get("/api/intended/design").json()
    assert d["ok"] and not [o for o in d["open"] if o["what"] == "declared, neither heard nor measured"]
    neither = [o["id"] for o in project.intended.design()["open"] if o["what"] == "declared, neither heard nor measured"]
    assert neither == ["feature_count_improver"]          # in process, with only the bus count: counted traffic is the web server's


def test_an_owners_request_on_an_attachment_shows_under_its_row(tmp_path, monkeypatch):
    from attach_seed import project_with_instruments

    project = project_with_instruments(tmp_path, monkeypatch, sources=False)   # an attachment names an instrument there is
    seed(project)
    project.intended.apply([{"op": "propose_attachment", "machine": "feature_count_improver", "instrument": "pg"}],
                           {"author": "supervisor"})
    c = client(project)
    got = c.post("/api/intended/request", json={"control": "confirm", "part": "attachment", "id": "feature_count_improver_pg"}).json()
    row = next(x for x in machines(c)["machines"] if x["id"] == "feature_count_improver")["intent"]["attachments"][0]
    assert row["requested"]["event"] == got["event"] and row["requested"]["control"] == "confirm"
    project.intended.apply([{"op": "confirm", "part": "attachment", "id": "feature_count_improver_pg"}],
                           {"author": "supervisor", "request": got["event"]})
    row = next(x for x in machines(c)["machines"] if x["id"] == "feature_count_improver")["intent"]["attachments"][0]
    assert row["requested"] is None and row["state"] == "declared"


def test_one_rule_says_whether_a_draft_is_publishable(tmp_path, monkeypatch):
    from orchestra.sd.intended.machines_view import merge

    project = project_at(tmp_path, monkeypatch)
    seed(project)
    project.intended.apply([{"op": "set_expected_effect", "machine": "feature_count_improver", "horizon_s": 60,
                             "edits": [{"from": "features", "to": None, "appears": True}, {"stock": "nothing_here", "rises": True}]}],
                           {"author": "supervisor"})
    out = {"machines": [], "edges": []}
    merge(out, project.intended, ModelStore.for_state(project.state_dir).load())
    edits = out["machines"][0]["intent"]["expected_effect"]["edits"]
    assert [(e["publishable"], e["why"]) for e in edits] == [(False, "features: waits for a link"), (False, "not in the model")]
    drafts = [(o["edit"], o["why"]) for o in project.intended.design()["open"] if o["what"] == "unpublishable draft"]
    assert drafts == [({"from": "features", "to": None, "appears": True}, "features: waits for a link"),
                      ({"stock": "nothing_here", "rises": True}, "not in the model")]


def test_intent_events_are_records_not_hand_offs(tmp_path, monkeypatch):
    from orchestra.web.machines import MachineIndex, _ListBus

    project = project_at(tmp_path, monkeypatch)
    Events(project.events_file, source="owner").publish("orchestra.intent.requested", {}, subject="machine:fci")
    Events(project.events_file, source="orchestra-host").publish("orchestra.intent.changed", {}, subject="machine:fci")
    Events(project.events_file, source="fci").publish("work.requested", {}, subject="machine:fci")
    Events(project.events_file, source="gate").publish("gate.landed", {}, subject="machine:fci")
    idx = MachineIndex(_ListBus(Events(project.events_file).read(0, 100)[0]))
    idx.update()
    assert list(idx.handoffs) == [("fci", "work.requested", "gate")]
    assert idx.total["owner"]["orchestra.intent.requested"] == 1 and idx.total["orchestra-host"]["orchestra.intent.changed"] == 1


def test_a_hung_store_does_not_grow_the_threads_past_the_pool(tmp_path):
    import threading

    from orchestra.sd.intended import facts

    gate = threading.Event()

    class Hung:
        def series(self, *a, **k):
            gate.wait(10)
            return []
    try:
        before = threading.active_count()
        for _ in range(3 * facts.POOL):
            f = facts.Facts(Hung(), limit_s=0.02)
            assert f.recording("x") is None and f.missing == ["recording x"]
        assert threading.active_count() <= before + facts.POOL
        started = time.monotonic()
        assert facts.Facts(Hung(), limit_s=5).recording("x") is None
        assert time.monotonic() - started < 1                   # every worker busy: missing at once, not queued
    finally:
        gate.set()
    deadline = time.time() + 5
    while time.time() < deadline and facts.within(lambda: 1, 1.0) != (1, True):
        time.sleep(0.05)
    assert facts.within(lambda: 1, 1.0) == (1, True)


def test_the_web_server_reads_an_orchestra_toml_a_plugin_edited_while_it_runs(tmp_path, monkeypatch):
    project = project_at(tmp_path, monkeypatch)
    seed(project)
    c = client(project)
    assert c.get("/api/intended/script?instrument=features.new").status_code == 404
    base = project.config_file.read_text()
    project.config_file.write_text(base + '\n[[collect]]\nname = "features.new"\ncommand = "true"\n')
    assert c.get("/api/intended/script?instrument=features.new").json()["entry"]["command"] == "true"
    project.config_file.write_text(base + '\n[[collect]]\nname = "features.new"\ncommand = "false"\nevery = "1m"\n')
    assert c.get("/api/intended/script?instrument=features.new").json()["entry"]["command"] == "false"
    project.config_file.write_text(base + "\n[[collect\n")                         # half written: the last good one stands
    assert c.get("/api/intended/script?instrument=features.new").json()["entry"]["command"] == "false"


def test_rediscover_reads_the_plugins_collectors_again_once_the_configuration_changed(tmp_path, monkeypatch):
    from orchestra.sd import rediscover as rd
    from orchestra.sd import simulated

    project = project_at(tmp_path, monkeypatch)
    seen = []

    def spy(project, metrics, **kw):
        seen.append(kw["collectors"])
        raise RuntimeError("stop here")
    monkeypatch.setattr(rd, "rediscover", spy)
    monkeypatch.setattr(simulated, "plugin_collectors", lambda project: ["reloaded"])
    c = client(project)

    def run():
        assert c.post("/api/dynamics/rediscover", json={}).json()["started"]
        deadline = time.time() + 10
        while c.get("/api/dynamics/rediscover").json()["running"] and time.time() < deadline:
            time.sleep(0.05)
    run()
    project.config_file.write_text(project.config_file.read_text() + '\n[[collect]]\nname = "x"\ncommand = "true"\nsimulated = true\n')
    run()
    assert seen == [[], ["reloaded"]]
