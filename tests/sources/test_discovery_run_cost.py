"""A discovery run's store cost is what it asked of the store (``sd/runs.py``): every request it
sends is tagged with its id in the request log, its inference round with ``<id>~infer-<source>``
and recorded as a round of its own; the second run reads only what is new (incremental)."""

from __future__ import annotations

import json
import math
import time

from fake_prometheus import FakePrometheus
from helpers import project, source_toml

from orchestra.metrics.file import FileMetrics
from orchestra.sd.rediscover import rediscover
from orchestra.sd.store import ModelStore
from orchestra.sources import reqlog

NOW = math.floor(time.time() / 60) * 60


def dump():
    return [("queue_depth", {"queue": q}, [(NOW - 7200 + 60 * i, float(i % 7)) for i in range(121)]) for q in ("a", "b")]


def test_a_runs_cost_is_every_request_it_tagged_and_its_inference_round_is_its_own(tmp_path, monkeypatch):
    fake = FakePrometheus(dump())
    try:
        p = project(tmp_path, monkeypatch, source_toml(fake.url))
        rediscover(p, FileMetrics(tmp_path / "m.jsonl"), window_s=3600.0, step_s=60.0, trigger="schedule", now=NOW)
        first = fake.requests
        rediscover(p, FileMetrics(tmp_path / "m.jsonl"), window_s=3600.0, step_s=60.0, trigger="button", now=NOW + 60)
    finally:
        fake.close()
    recs = ModelStore.for_state(p.state_dir).runs().recent()
    disc = [r for r in recs if r["kind"] == "discovery"]
    rounds = [r for r in recs if r["kind"] == "inference"]
    assert [r["trigger"] for r in disc] == ["schedule", "button"]
    assert len(rounds) == 1 and rounds[0]["parent"] == disc[0]["id"] and rounds[0]["source"] == "rig"
    assert rounds[0]["id"] == disc[0]["id"] + "~infer-rig" and rounds[0]["outcome"].startswith("inferred ")
    logged = [json.loads(x) for x in reqlog.path(p.state_dir, "rig").read_text().splitlines()]
    assert all(x.get("run") for x in logged) and all(x.get("bytes", 0) > 0 for x in logged if not x.get("error"))
    a, b = disc[0]["cost"]["rig"], disc[1]["cost"]["rig"]
    assert a["requests"] == first and b["requests"] == fake.requests - first
    assert rounds[0]["cost"]["rig"]["requests"] == a["inference"] > 0
    assert a["whole"] > 0 and a["incremental"] == 0 and b["inference"] == 0 and b["incremental"] > 0 and b["whole"] == 0
    assert a["points"] > 0 and a["bytes"] > 0 and a["today"] == first and a["per_day"] == 20000
    assert disc[0]["phases"]["inference"] > 0 and disc[0]["phases"]["reads"] > 0
