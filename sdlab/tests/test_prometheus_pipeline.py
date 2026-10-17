"""End to end: a Prometheus-compatible server, models built from what it exports, history imported
with PromQL, and discovery finding the consumers whose counters are not exported."""

import json
import socket
import threading
import time
from pathlib import Path

import pytest
import uvicorn
from fastapi.testclient import TestClient

from sdlab.discovery.api import discover
from sdlab.promlab import models as builder
from sdlab.promlab.api import create_app as prom_app
from sdlab.promlab.generate import generate
from sdlab.promlab.store import Dataset
from sdlab.server import create_app

ROOT = Path(__file__).resolve().parents[1]


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def prom(tmp_path_factory):
    out = tmp_path_factory.mktemp("promdata")
    truth = generate(str(out), services=40, days=3, step=300, seed=11, end=1_790_000_000)
    port = free_port()
    server = uvicorn.Server(uvicorn.Config(prom_app(Dataset(str(out))), host="127.0.0.1", port=port, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}", truth
    server.should_exit = True


def test_history_from_promql_and_discovery_of_unexported_consumers(prom, tmp_path, monkeypatch):
    url, truth = prom
    monkeypatch.setenv("SDLAB_HOME", str(tmp_path))
    monkeypatch.setenv("SDLAB_PROM_URL", url)
    stocks, flows = builder.kafka_part(url, 0, 0)
    model = builder.model("test-kafka", "Kafka", "", stocks, flows, 29, None)
    (tmp_path / "models").mkdir()
    (tmp_path / "models" / "test-kafka.json").write_text(json.dumps(model))
    client = TestClient(create_app())

    snap = client.post("/api/models/test-kafka/live/import").json()
    n = len(snap["series"]["t"])
    assert 3 * 288 - 5 <= n <= 3 * 288 + 1                         # three days of 5-minute steps
    assert not snap["errors"]
    hidden = {builder.slug("lag", h["topic"], h["consumergroup"]) for h in truth["hidden_consumers"]}
    assert hidden and hidden <= {s["id"] for s in stocks}           # their lag is exported...
    assert not any(f["id"] == builder.slug("consumed", h["topic"], h["consumergroup"]) for f in flows for h in truth["hidden_consumers"])

    # ...and discovery, given the lag of every group and the measured flows, finds their consumption
    # (the measured flows are what the page subtracts first: the known change of each stock per step)
    t, levels, rates = snap["series"]["t"], snap["series"]["levels"], snap["series"]["rates"]
    known = {}
    for f in model["flows"]:
        if not f.get("query") or f["id"] not in rates:
            continue
        for end, sign in (("to", 1), ("from", -1)):
            if f.get(end):
                k = known.setdefault(f[end], [0.0] * len(t))
                for i, v in enumerate(rates[f["id"]]):
                    k[i] += sign * (v or 0)
    r = discover({"stocks": model["stocks"], "run": {"t": t, "levels": levels}, "known": known})
    found = [(f["from"], f["to"], f["perStep"]) for f in r["flows"]]
    drains = {f[0] for f in found if f[1] is None}
    assert hidden <= drains, (hidden, found)
    assert len(found) <= len(hidden) + 2, found                     # little else is invented
