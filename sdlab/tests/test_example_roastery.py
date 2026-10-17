import pytest
from fastapi.testclient import TestClient

from sdlab.server import create_app, validate


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("SDLAB_HOME", str(tmp_path))
    return TestClient(create_app())


def test_roastery_is_seeded_and_valid(client):
    m = client.get("/api/models/roastery").json()
    assert validate(m) == []
    assert client.put("/api/models/roastery", json=m).json() == {"ok": True}
    assert [s["id"] for s in m["stocks"]] == ["green", "roasted", "cooled", "bags", "shipped", "orders"]


def test_roastery_runs_live(client):
    for _ in range(40):
        client.post("/api/models/roastery/live/step")
    snap = client.get("/api/models/roastery/live").json()
    assert snap["t"] == 40 and not snap["errors"], snap["errors"]
    total = {f: sum(v) for f, v in snap["series"]["rates"].items()}
    for f in ("deliver", "roast", "cool", "package", "order", "ship"):
        assert total[f] > 0, f"{f} never fired: {total}"
    assert snap["series"]["levels"]["shipped"][-1] >= 40
    bags = client.get("/api/models/roastery/live/stocks/shipped").json()["items"]
    assert bags and all(b["origin"] and b["profile"] and b["grams"] == 250 for b in bags)
