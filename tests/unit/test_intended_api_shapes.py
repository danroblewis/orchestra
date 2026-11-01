"""The API answers in the shapes the pages consume: the captured fixtures
(``mockups/fixtures/api/``) are the expected output for a seeded store, every field of theirs still
there, and beside them the declared layer of docs/proposals/intended-model.md §6.1."""

import time

from fastapi.testclient import TestClient
from intended_seed import fixture, project_at, record_points, seed

EXPECTED_STOCK = {"part", "id", "key", "name", "declared", "present", "measured", "near", "note", "provenance", "target",
                  "candidates", "measure"}
INTENDED = {"version", "since", "since_saved_at", "expected", "marks", "removed", "changes", "came_and_went", "ignored", "settled"}
INTENT = {"state", "author", "kind", "heard", "title", "description", "tags", "managed", "engagement", "receives", "emits",
          "reads", "spec", "guessed", "pending", "requested", "expected_effect", "provenance", "latest"}


def client(project):
    from orchestra.web.app import create_app
    from orchestra.web.auth import bearer
    return TestClient(create_app(project), headers=bearer(project))


def machines(c):
    deadline = time.time() + 15
    while time.time() < deadline:
        got = c.get("/api/machines").json()
        if got.get("ok"):
            return got
        time.sleep(0.2)
    raise AssertionError(got)


def test_the_dynamics_answer_keeps_the_fixture_shape_and_adds_intended(tmp_path, monkeypatch):
    project = project_at(tmp_path, monkeypatch)
    seed(project)
    record_points(project)
    c = client(project)
    got = c.get("/api/dynamics/model").json()
    want = fixture("dynamics_model")
    assert got["ok"] and set(want) <= set(got)
    assert set(want["model"]) <= set(got["model"])
    for kind in ("stocks", "flows"):
        assert set(want["model"][kind][0]) <= set(got["model"][kind][0])
    it = got["model"]["intended"]
    assert INTENDED <= set(it), it
    features = next(e for e in it["expected"] if e.get("id") == "features")
    assert EXPECTED_STOCK <= set(features)
    assert features["declared"] and not features["present"] and features["measured"]
    assert features["measure"]["chosen"] == "a" and features["measure"]["recording"]["points"] == 3
    assert features["measure"]["recording"]["last"] == 46.0
    assert features["candidates"] == [{"key": "acceptance_tests_passing", "id": "acceptance_tests_passing",
                                       "why": "recorded by the chosen instrument"}]
    assert it["since"] == 1 and it["marks"]["stocks"]["acceptance_tests_passing"] == ["new"]
    assert [r["id"] for r in it["removed"]["flows"]] == ["repo_files_to_commits"]
    assert it["removed"]["flows"][0]["machines"] == [{"machine": "merge_gate", "confidence": 0.71}]
    signs = [(ch["sign"], ch["part"]) for ch in it["changes"]]
    assert ("+", "stock") in signs and ("+", "flow") in signs and ("-", "flow") in signs and ("o", "stock") in signs
    plus = next(ch for ch in it["changes"] if ch["sign"] == "+" and ch["part"] == "flow")
    assert plus["controls"] == ["expect", "ignore"]


def test_the_machines_answer_keeps_the_fixture_shape_and_adds_intent(tmp_path, monkeypatch):
    project = project_at(tmp_path, monkeypatch)
    seed(project)
    got = machines(client(project))
    want = fixture("machines")
    assert set(want) <= set(got)
    m = next(x for x in got["machines"] if x["id"] == "feature_count_improver")
    assert set(want["machines"][0]) - {"group", "name", "kinds"} <= set(m)
    assert m["unseen"] and m["kind"] == "universal" and m["subscribes"] == [] and m["mode"] is None
    assert m["comparison"] == "declared, neither heard nor measured"
    assert INTENT <= set(m["intent"])
    assert m["intent"]["state"] == "proposed" and m["intent"]["author"] == "supervisor" and not m["intent"]["heard"]
    assert m["intent"]["guessed"] == ["receives[0]", "receives[1]"]
    edit = m["intent"]["expected_effect"]["edits"][0]
    assert edit == {"edit": {"stock": "features", "rises": True}, "label": "Features ↑", "link": "/dynamics#s:features",
                    "publishable": False, "why": "waits for a link"}
    assert {"from": "session.settled", "to": "feature_count_improver", "kind": "subscribes", "state": "proposed",
            "observed": False, "gone": False} in got["intended_edges"]
    assert {"type": "work.requested", "description": None, "implicit": True} in got["intended_types"]
    assert all(x["intent"] is None for x in got["machines"] if x["id"] != "feature_count_improver")


def test_the_intended_read_endpoints(tmp_path, monkeypatch):
    project = project_at(tmp_path, monkeypatch)
    seed(project)
    c = client(project)
    assert c.get("/api/intended").json()["version"] == 2
    assert c.get("/api/intended?version=1").json()["layer"]["machines"] == {}
    assert [v["version"] for v in c.get("/api/intended/versions").json()["versions"]] == [1, 2]
    assert [e["seq"] for e in c.get("/api/intended/journal?after=1").json()["journal"]] == [2]
    d = c.get("/api/intended/diff?d=1&v=2&since=1").json()
    assert d["ok"] and d["version"] == 1 and d["since"] == 1
    assert c.get("/api/intended/design").json()["version"] == 2
