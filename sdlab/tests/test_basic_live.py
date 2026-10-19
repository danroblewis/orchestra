"""A basic model run live (sdlab/basic_live.py): the case's true model stepped by the ground-truth
engine, reproducing the recorded data step for step and going on past it; live discovery on it, and
its comparison with the truth."""

import time

import pytest
from fastapi.testclient import TestClient

from sdlab import basics
from sdlab.basic_live import BasicLiveRun
from sdlab.ladder import api as ladder

CASES = ["003-chain-2", "015-hidden-stock", "016-coflow", "017-linear-effect", "018-table-effect", "019-announced-era",
         "020-unannounced-step", "021-daily-inflow", "023-injection", "024-floor-binds", "025-runs-empty",
         "032-three-chains-of-three", "033-independent-chains-shared-driver", "043-random-three-chains-of-two#2"]


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("SDLAB_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("SDLAB_LADDER_CACHE", str(tmp_path / "ladder"))
    from sdlab.server import create_app
    with TestClient(create_app()) as c:
        yield c


@pytest.mark.parametrize("variant", ["none-short", "counts-long"])
@pytest.mark.parametrize("cid", CASES)
def test_the_live_run_is_the_recorded_data_then_goes_on(monkeypatch, tmp_path, cid, variant):
    monkeypatch.setenv("SDLAB_LADDER_CACHE", str(tmp_path / "ladder"))
    rec = ladder.case_data(cid, variant, flows=True)
    n = len(rec["t"])
    run = BasicLiveRun(basics.model_id_of(cid), variant)
    run.tick(n + 25)
    s = run.snapshot(0)
    assert s["t"] == n + 25 and s["series"]["t"] == list(range(1, n + 26))
    assert set(s["series"]["levels"]) == set(rec["levels"]), "the measured stocks only (a hidden stock runs but is not shown)"
    for k, col in rec["levels"].items():
        assert s["series"]["levels"][k][:n] == col, f"{cid} {variant}: stock {k} differs from the recorded data"
    for k, col in rec["flows"].items():
        assert s["series"]["rates"][k][:n] == col
    starts = [e["start"] for e in rec["eras"]] or [1]
    assert [e["start"] for e in s["eras"]][:len(starts)] == starts, "the announced eras so far, the recorded ones first"


def test_a_live_run_starts_steps_pauses_and_resets(client):
    m, q = "ladder-019-announced-era", {"variant": "counts-short", "live": 1}
    s = client.get(f"/api/models/{m}/live", params=q).json()
    assert s["live"] and s["t"] == 0 and not s["running"] and s["recorded_length"] == 300
    for _ in range(3):
        s = client.post(f"/api/models/{m}/live/step", params={"variant": "counts-short"}).json()
    assert s["t"] == 3 and len(s["series"]["t"]) == 3
    s = client.post(f"/api/models/{m}/live/start", params={"variant": "counts-short"}, json={"seconds_per_tick": 0}).json()
    assert s["running"]
    assert any(m == r["id"] and r.get("running") for r in client.get("/api/models").json()["basics"])
    time.sleep(0.5)
    s = client.post(f"/api/models/{m}/live/stop", params={"variant": "counts-short"}).json()
    t = s["t"]
    assert not s["running"] and t > 3
    time.sleep(0.2)
    assert client.get(f"/api/models/{m}/live", params=q).json()["t"] == t, "paused: it does not move"
    later = client.get(f"/api/models/{m}/live", params={**q, "since": t - 2}).json()
    assert later["series"]["t"] == [t - 1, t]
    rec = client.get(f"/api/models/{m}/live", params={"variant": "counts-short"}).json()
    assert not rec.get("live") and rec["length"] == 300, "the recorded playback is still there"
    s = client.post(f"/api/models/{m}/live/reset", params={"variant": "counts-short"}).json()
    assert s["t"] == 0 and s["series"]["t"] == []


def test_live_discovery_finds_flows_and_compares_with_the_truth(client):
    m = "ladder-003-chain-2"
    for _ in range(60):
        client.post(f"/api/models/{m}/live/step", params={"variant": "none-short"})
    s = client.get(f"/api/models/{m}/live", params={"variant": "none-short", "live": 1}).json()
    body = {"stocks": [{"id": "A"}, {"id": "B"}], "run": {"t": s["series"]["t"], "levels": s["series"]["levels"]}, "strategy": "matrix"}
    job = client.post(f"/api/models/{m}/discovery", json=body).json()["job"]
    st = client.get(f"/api/models/{m}/discovery", params={"job": job, "wait": 30}).json()
    assert st["state"] == "done" and st["result"]["flows"]
    assert ("A", "B") in {(f["from"], f["to"]) for f in st["result"]["flows"]}
    c = client.post(f"/api/models/{m}/truth-compare", json={"flows": st["result"]["flows"], "steps": 60, "variant": "none-short", "live": True}).json()
    assert c["steps"] == 60 and c["status"] == "pass" and {p["key"] for p in c["parts"]} >= {"A -> B [A]"}
    wrong = [{**f, "rate": {**f["rate"], "k": 0.4}} if (f["from"], f["to"]) == ("A", "B") else f for f in st["result"]["flows"]]
    c = client.post(f"/api/models/{m}/truth-compare", json={"flows": wrong, "steps": 60, "variant": "none-short", "live": True}).json()
    ab = next(p for p in c["parts"] if p["key"] == "A -> B [A]")
    assert c["status"] == "fail" and not ab["ok"] and ab["found_value"] == pytest.approx(0.4)
    assert client.post("/api/models/bakery/truth-compare", json={"flows": []}).status_code == 404, "a model without a ladder case has no truth (sd-* examples do: test_known_truth.py)"


def test_a_draw_opens_by_its_model_id(client):
    r = client.get("/api/models").json()
    assert any(d["id"] == "ladder-043-random-three-chains-of-two~2" for d in r["draws"])
    m = client.get("/api/models/ladder-043-random-three-chains-of-two~2").json()
    assert m["basic"]["case"] == "043-random-three-chains-of-two#2"
    s = client.post("/api/models/ladder-043-random-three-chains-of-two~2/live/step").json()
    assert s["t"] == 1


def test_the_strategy_menu_answers_at_once(client):
    m = client.get("/api/discovery/menu").json()
    assert m["default"] and m["strategies"] and "ready" in m
    assert client.get("/api/discovery/strategies").json()["default"] == "matrix", "the API's own default is unchanged"
