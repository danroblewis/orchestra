import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sdlab.server import EXAMPLES, create_app, validate


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("SDLAB_HOME", str(tmp_path))
    return TestClient(create_app())


def test_the_repair_shop_is_a_valid_model():
    m = json.loads((EXAMPLES / "repair.json").read_text())
    assert validate(m) == []
    assert {f["id"] for f in m["flows"] if f.get("hidden")} == {"send", "back"}


def test_the_page_never_sees_the_backroom(client):
    page = client.get("/api/models/repair").json()
    assert [f["id"] for f in page["flows"]] == ["arrive", "fix", "collect"]
    assert "vendor" not in json.dumps(page["flows"]).lower()
    full = client.get("/api/models/repair?reveal=true").json()
    assert {"send", "back"} <= {f["id"] for f in full["flows"]}


def test_the_repair_shop_runs_live(client, tmp_path):
    for _ in range(25):
        client.post("/api/models/repair/live/step")
    snap = client.get("/api/models/repair/live").json()
    assert snap["t"] == 25 and not snap["errors"], snap["errors"]
    assert set(snap["series"]["rates"]) == {"arrive", "fix", "collect"}            # hidden flows stay hidden
    assert all(set(m) <= {"arrive", "fix", "collect"} for m in snap["series"]["moved"])
    assert sum(snap["series"]["rates"]["fix"]) > 0
    # the backroom is real: devices went to the vendor (their queue lives in the run's directory)
    vendor = json.loads(Path(tmp_path, "runs", "repair", "vendor.json").read_text())
    assert vendor["clock"] == 25
    sent = len(vendor["queue"])
    moved = snap["series"]["moved"]
    came_in = sum(m.get("arrive", {}).get("made", {}).get("intake", 0) for m in moved)
    left = sum(m.get("fix", {}).get("took", {}).get("intake", 0) for m in moved)
    assert came_in - left - snap["series"]["levels"]["intake"][-1] >= sent > 0      # unmeasured departures from Intake


def test_a_reset_empties_the_vendor(client, tmp_path):
    for _ in range(10):
        client.post("/api/models/repair/live/step")
    client.post("/api/models/repair/live/reset")
    client.post("/api/models/repair/live/step")
    vendor = json.loads(Path(tmp_path, "runs", "repair", "vendor.json").read_text())
    assert vendor["clock"] == 1
