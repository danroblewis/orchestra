"""Basic models (sdlab/basics.py): the ladder's cases as read-only models in the editor, each
playing back its recorded data in one variant, with discovery available on it."""

import pytest
from fastapi.testclient import TestClient

from sdlab.ladder import api as ladder


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("SDLAB_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("SDLAB_LADDER_CACHE", str(tmp_path / "ladder"))
    from sdlab.server import create_app
    with TestClient(create_app()) as c:
        yield c


def test_every_case_is_listed_first_simplest_first(client):
    r = client.get("/api/models").json()
    basics = r["basics"]
    assert [b["case"] for b in basics] == [c["id"] for c in sorted(ladder.cases(), key=lambda c: (c["level"], c["id"]))]
    assert all(b["id"] == "ladder-" + b["case"] and b["tests"] and b["name"] for b in basics)
    assert r["examples"], "the older models are still listed (the page hides them)"


def test_a_basic_model_is_the_true_model_and_read_only(client):
    m = client.get("/api/models/ladder-015-hidden-stock").json()
    assert m["example"] and m["recorded"] and m["basic"]["case"] == "015-hidden-stock" and m["basic"]["variant"] == "counts-long"
    assert [s["id"] for s in m["stocks"]] == ["A", "H", "B"] and m["stocks"][1]["measured"] is False
    assert {f["id"] for f in m["flows"]} == {"in", "a_h", "h_b", "b_out"}
    assert client.put("/api/models/ladder-015-hidden-stock", json=m).status_code == 409
    assert client.delete("/api/models/ladder-015-hidden-stock").status_code == 409
    assert client.post("/api/models/ladder-015-hidden-stock/live/start", json={}).status_code == 409
    copy = client.post("/api/models/ladder-015-hidden-stock/copy", json={"name": "my hidden stock"}).json()
    mine = client.get(f"/api/models/{copy['id']}").json()
    assert not mine["example"] and "recorded" not in mine and len(mine["flows"]) == 4


def test_its_run_is_the_recorded_data_in_a_variant(client):
    s = client.get("/api/models/ladder-019-announced-era/live", params={"since": 0}).json()
    assert s["variant"] == "counts-long" and not s["running"] and s["length"] == 2000
    assert set(s["series"]["levels"]) == {"A", "B"} and set(s["series"]["rates"]) == {"in", "ab", "b_out"}
    assert [e["label"] for e in s["eras"]][:3] == ["Start", "slow", "fast"] and s["eras"][0]["model"]["basic"]
    short = client.get("/api/models/ladder-019-announced-era/live", params={"since": 0, "variant": "none-short"}).json()
    assert short["variant"] == "none-short" and len(short["series"]["t"]) == 300
    later = client.get("/api/models/ladder-019-announced-era/live", params={"since": 290, "variant": "none-short"}).json()
    assert len(later["series"]["t"]) == 10 and "model" not in later["eras"][0]
    hidden = client.get("/api/models/ladder-015-hidden-stock/live").json()
    assert set(hidden["series"]["levels"]) == {"A", "B"}, "a stock nobody measures has no levels"


def test_discovery_runs_on_a_basic_model(client):
    s = client.get("/api/models/ladder-003-chain-2/live", params={"variant": "none-short"}).json()
    body = {"stocks": [{"id": "A"}, {"id": "B"}], "run": {"t": s["series"]["t"], "levels": s["series"]["levels"]}}
    job = client.post("/api/models/ladder-003-chain-2/discovery", json=body).json()["job"]
    st = client.get("/api/models/ladder-003-chain-2/discovery", params={"job": job, "wait": 30}).json()
    assert st["state"] == "done"
    ends = {(f["from"], f["to"]) for f in st["result"]["flows"]}
    assert ("A", "B") in ends


@pytest.mark.parametrize("mid", ["ladder-nope", "ladder-..%2Fetc", "ladder-"])
def test_unknown_basic_models_are_not_found(client, mid):
    assert client.get(f"/api/models/{mid}").status_code in (400, 404)
    assert client.get(f"/api/models/{mid}/discovery").status_code in (400, 404)
