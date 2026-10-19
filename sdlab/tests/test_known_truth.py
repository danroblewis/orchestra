"""The known truth behind every model that has one (sdlab/known_truth.py): basic models, and the sd-*
examples through their realistic ladder cases; the editor draws it and compares an estimate with it."""

import pytest
from fastapi.testclient import TestClient

from sdlab import known_truth
from sdlab.ladder import api as ladder


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("SDLAB_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("SDLAB_LADDER_CACHE", str(tmp_path / "ladder"))
    from sdlab.server import create_app
    with TestClient(create_app()) as c:
        yield c


def test_which_models_have_a_truth():
    assert known_truth.case_of("sd-kanban") == "sd-kanban"
    assert known_truth.case_of("sd-k8s-small") == "sd-k8s-small"
    assert known_truth.case_of("ladder-003-chain-2") == "003-chain-2"
    assert known_truth.case_of("bakery") is None and known_truth.case_of("sd-no-such-example") is None


def test_an_examples_truth_is_its_case_with_the_hidden_stocks(client):
    t = client.get("/api/models/sd-kanban/truth").json()
    case = ladder.case("sd-kanban")
    assert t["case"] == "sd-kanban" and t["variant"] == "counts-long"
    assert [f["id"] for f in t["flows"]] == [f["id"] for f in case["model"]["flows"]]
    shown = {s["id"] for s in client.get("/api/models/sd-kanban").json()["stocks"]}
    assert t["hidden"] == ["undetected"] and "undetected" not in shown
    assert {s["id"] for s in t["stocks"]} == shown | {"undetected"}
    assert all("x" in s and "y" in s for s in t["stocks"])
    assert client.get("/api/models/ladder-003-chain-2/truth").json()["case"] == "003-chain-2"
    assert client.get("/api/models/bakery/truth").status_code == 404


def test_an_examples_estimate_is_compared_on_the_runs_own_data(client):
    m, n = "sd-bakery", 300
    live = client.get(f"/api/models/{m}/live").json()          # the example's own run: the case's data, step for step
    d = ladder.case_data(m, "counts-long")
    if len(live["series"]["t"]) >= n:
        for k, col in live["series"]["levels"].items():
            assert col[:n] == pytest.approx(d["levels"][k][:n])
    truth = client.get(f"/api/models/{m}/truth").json()
    last = {k: col[n - 1] for k, col in d["levels"].items()}
    right = [{**f, "ratio": f.get("ratio", 1)} for f in truth["flows"]]
    c = client.post(f"/api/models/{m}/truth-compare", json={"flows": right, "steps": n, "last": last}).json()
    assert c["steps"] == n and c["variant"] == "counts-long" and c["parts"]
    assert all(p["found"] for p in c["parts"]), "the true flows are found"
    none = client.post(f"/api/models/{m}/truth-compare", json={"flows": [], "steps": n, "last": last}).json()
    assert none["status"] == "fail" and not any(p["found"] for p in none["parts"])


def test_a_run_that_is_not_the_cases_data_is_not_compared(client):
    d = ladder.case_data("sd-kanban", "counts-long")
    last = {k: col[99] + 1 for k, col in d["levels"].items()}
    r = client.post("/api/models/sd-kanban/truth-compare", json={"flows": [], "steps": 100, "last": last})
    assert r.status_code == 409 and "not the case's data" in r.json()["detail"]
    assert client.post("/api/models/sd-kanban/truth-compare", json={"flows": [], "steps": 10 ** 7}).status_code == 409
    assert client.post("/api/models/bakery/truth-compare", json={"flows": []}).status_code == 404
