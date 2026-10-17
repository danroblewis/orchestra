"""The milling shop: a co-flow (each part wears bits) and an effect (few bits slow the CNC)."""

import pytest
from fastapi.testclient import TestClient

from sdlab.server import create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("SDLAB_HOME", str(tmp_path))
    return TestClient(create_app())


def test_the_milling_shop_loads_and_validates(client):
    m = client.get("/api/models/milling").json()
    assert [s["id"] for s in m["stocks"]] == ["blanks", "parts", "shipped", "on_order", "bits"]
    mill = next(f for f in m["flows"] if f["id"] == "mill")
    assert mill["uses"] == [{"stock": "bits", "per": 0.1}]
    assert mill["effects"][0]["stock"] == "bits"
    assert client.put("/api/models/milling", json=m).json() == {"ok": True}
    progs = client.get("/api/programs").json()["programs"]
    assert {"milling/blanks", "milling/cnc", "milling/shipping", "milling/purchasing", "milling/supplier"} <= set(progs)


def test_the_milling_shop_runs_live_and_bits_limit_milling(client):
    for _ in range(60):
        snap = client.post("/api/models/milling/live/step").json()
    assert snap["t"] == 60 and not snap["errors"], snap["errors"]
    lv, rt = snap["series"]["levels"], snap["series"]["rates"]

    # the live run starts from the model's starting values, like the simulation: one bit, so the
    # CNC starts slowly (a quarter speed) until more bits arrive
    assert lv["bits"][0] >= 0 and sum(rt["mill"][:3]) <= 3 * 1.5

    # parts get made and shipped
    milled, delivered = sum(rt["mill"]), sum(rt["deliver"])
    assert milled > 120 and lv["shipped"][-1] > 100

    # the co-flow: every ten parts use up a bit, so bits delivered = bits used + bits on hand
    used = delivered + 1 - lv["bits"][-1]                     # one bit at the start
    assert abs(used - milled * 0.1) <= 1.5, (used, milled)

    # the effect: with few bits the CNC cannot keep up with the 4 blanks a minute that arrive
    assert max(lv["bits"]) < 5
    assert sum(rt["mill"][-30:]) < sum(rt["arrive"][-30:]) - 15
    assert lv["blanks"][-1] > lv["blanks"][30] > 10

    # the items are real: parts name the bit and the alloy they were cut from
    part = client.get("/api/models/milling/live/stocks/shipped").json()["items"][0]
    assert {"part_no", "alloy", "carrier"} <= part.keys()
    bit = client.get("/api/models/milling/live/stocks/bits").json()["items"][0]
    assert bit["po"].startswith("PO-")


def test_more_bits_mill_faster_live(client):
    """Same run, but Purchasing aims for eight bits: the effect lifts and milling keeps up."""
    m = client.get("/api/models/milling").json()
    next(f for f in m["flows"] if f["id"] == "order")["rate"]["goal"] = 8
    client.put("/api/models/milling", json=m)
    for _ in range(60):
        snap = client.post("/api/models/milling/live/step").json()
    assert not snap["errors"], snap["errors"]
    lv, rt = snap["series"]["levels"], snap["series"]["rates"]
    assert max(lv["bits"][-30:]) >= 5
    assert sum(rt["mill"][-30:]) >= sum(rt["arrive"][-30:]) - 6
