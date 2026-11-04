"""A stock fed by a source (``[[sources]]``) has its level read through that source on the Dynamics
page: the level now, where it came from (``measured_by``), the projection's start and its trust,
never from the own store, and never copied into it. The source may be added while the web server
runs (bootstrap run 7: every queue's level read "no data", its source added after the page began)."""

from __future__ import annotations

import time

from fake_prometheus import FakePrometheus
from fastapi.testclient import TestClient
from helpers import project, source_toml
from test_source_catalogue import _queue, now_grid

from orchestra.metrics import for_project
from orchestra.sd.rediscover import rediscover
from orchestra.web.app import create_app
from orchestra.web.auth import bearer

DECLARED = "".join(f'\n[[series]]\nsource = "rig"\nname = "{n}"\nquery = "{n}"\nkind = "{k}"\n'
                   for n, k in (("queue_depth", "level"), ("jobs_in_total", "counter"), ("jobs_out_total", "counter")))
DISCOVERY = '[discovery]\nwindow = "120m"\nstep = "30s"\nstrategy = "conservation"\n'


def _until(fn, seconds: float = 30.0):
    deadline = time.time() + seconds
    while time.time() < deadline:
        if (got := fn()) is not None:
            return got
        time.sleep(0.3)
    raise AssertionError("not within the time limit")


def test_a_source_fed_stocks_level_projection_and_trust_are_read_through_the_source(tmp_path, monkeypatch):
    end = now_grid(30.0)
    fake = FakePrometheus(_queue(end, "consumer"))
    try:
        p = project(tmp_path, monkeypatch, DISCOVERY)            # the web server starts before the source is added
        client = TestClient(create_app(p), headers=bearer(p))
        with client:
            assert client.get("/api/dynamics/model").json()["ok"] is False
            (p.repo_root / "orchestra.toml").write_text(source_toml(fake.url, window="120m", step="30s",
                                                                    extra='match = [\'{__name__="none"}\']') + DECLARED)
            p.reload_config()                                    # as the host does
            model = rediscover(p, for_project(p)).model
            stock = model.stocks[0]
            assert stock.series.source == "rig"

            def level():
                m = client.get("/api/dynamics/model").json()["model"]
                return m if stock.id in m["levels"] else None
            m = _until(level)
            now = m["levels"][stock.id]
            assert now["v"] == _queue(end, "consumer")[0][2][-1][1] and now["measured_by"] == "source rig"

            def projected():
                r = client.get("/api/dynamics/simulate").json()
                return r if r.get("ok") and r["stocks"][stock.id].get("start") is not None else None
            sim = _until(projected)
            row = sim["stocks"][stock.id]
            assert row["no_projection"] is None and row["start"] == now["v"] and row["trust"] is not None
    finally:
        fake.close()
    assert for_project(p).latest("rig:queue_depth", {}) is None and for_project(p).latest("queue_depth", {}) is None   # never copied
