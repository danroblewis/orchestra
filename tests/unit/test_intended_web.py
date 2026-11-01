"""The intended model's routes on the web server and the events endpoint, and the host's
announcement (docs/proposals/intended-model.md §5, §6; §10 tests 1, 15, 16, 18, 19, 21, 23, 24, 31)."""

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


def test_the_page_controls_accept_exactly_the_observations(tmp_path, monkeypatch):
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


def test_a_request_publishes_one_event_from_owner_and_writes_no_version(tmp_path, monkeypatch):
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
    project.intended.apply([{"op": "confirm", "part": "machine", "id": "feature_count_improver"}],
                           {"author": "owner", "source": "supervisor", "quote": "yes", "request": got["event"]})
    m = next(x for x in machines(c)["machines"] if x["id"] == "feature_count_improver")
    assert m["intent"]["requested"] is None and m["intent"]["state"] == "declared"


def test_a_declared_machine_is_heard_once_its_source_publishes_and_aliases_join(tmp_path, monkeypatch):
    project = project_at(tmp_path, monkeypatch)
    seed(project)
    project.intended.apply([{"op": "propose_machine", "id": "nightly_metrics", "kind": "programmatic", "managed": "external",
                             "engagement": {"mode": "scheduled", "at": "02:00"}},
                            {"op": "alias", "machine": "nightly_metrics", "observed": "jenkins.nightly"}], {"author": "supervisor"})
    c = client(project)
    got = machines(c)
    m = next(x for x in got["machines"] if x["id"] == "feature_count_improver")
    assert m["unseen"] and not m["intent"]["heard"] and m["kind"] == "universal"
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


def test_each_call_is_announced_once_by_the_host_even_one_written_while_it_was_down(tmp_path, monkeypatch):
    from orchestra.sd.intended.announce import announce
    project = project_at(tmp_path, monkeypatch)
    seed(project)
    ev = Events(project.events_file)
    assert announce(project.intended, ev.publish) == [1, 2]
    assert announce(project.intended, ev.publish) == []
    project.intended.apply([{"op": "revise_machine", "id": "feature_count_improver", "set": {"title": "FCI"}}],
                           {"author": "owner", "via": "plugin", "source": "supervisor", "quote": "call it FCI"})
    assert announce(project.intended, ev.publish) == [3]
    evs = [e for e in ev.read(0, 1000)[0] if e["type"] == "orchestra.intent.changed"]
    assert [e["data"]["version"] for e in evs] == [1, 2, 3] and all(e["source"] == "orchestra-host" for e in evs)
    import fnmatch

    from orchestra.sd.eras import parse
    ty, fields = parse("orchestra.intent.changed:subject=machine:feature_count_improver")
    picked = [e for e in evs if fnmatch.fnmatchcase(e["type"], ty)
              and all(fnmatch.fnmatchcase(e.get(k) or "", g) for k, g in fields.items())]
    assert [e["data"]["version"] for e in picked] == [2, 3]


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
    b = dynamics_block(store.intended(), metrics=Slow(), limit_s=0.05)
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
    bad = c.get("/api/intended/script?instrument=features.outside").json()
    assert not bad["ok"] and "outside the project" in bad["error"]
    assert not c.get("/api/intended/script?instrument=nothing").json()["ok"]


def test_the_core_page_answers_with_the_intended_directory_corrupt_or_locked(tmp_path, monkeypatch):
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
        assert c.get("/api/intended").status_code == 404


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
    assert status == 200 and out["version"] == 1 and len(json.dumps(out)) < 20_000
