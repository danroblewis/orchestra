"""The Core page's probes run in a lane per component (web/core.py, rule 8): a metrics store that
hangs holds its own lane, never the host's or the bus's, however many rounds go by."""

import subprocess
import time

import pytest

from orchestra import plugins
from orchestra.config import init_project
from orchestra.events import Events
from orchestra.web import core
from orchestra.web.core import CoreProbe


class HungMetrics:
    name = "hung"

    def _sleep(self, *a, **kw):
        time.sleep(0.6)
        return []

    write = latest = series = raw = _sleep


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setenv("ORCHESTRATOR_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(plugins, "entry_points", lambda group: [])
    r = tmp_path / "repo"
    r.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=r, check=True)
    return init_project(r)


def test_a_hung_metrics_store_never_times_out_the_host_or_the_bus(project, monkeypatch):
    monkeypatch.setattr(core, "INTERVAL", 0.0)
    monkeypatch.setattr(core, "TIMEOUT", 0.1)
    probe = CoreProbe(project, Events.for_project(project))
    probe.metrics = HungMetrics()
    seen = set()
    for _ in range(12):
        out = probe.status()
        assert out["host"]["ok"], out["host"]
        assert out["bus"]["ok"], out["bus"]
        assert out["metrics"]["ok"] is False
        err = out["metrics"]["error"]
        assert "timed out" in err or "still waiting since" in err
        seen.add("timed out" if "timed out" in err else "waiting")
        time.sleep(0.02)
    assert seen == {"timed out", "waiting"}           # never a second probe queued behind the hung one
    assert len(probe._lanes) == len({id(lane._pool) for lane in probe._lanes.values()})


def test_a_lane_keeps_one_call_in_flight_and_returns_the_last_result_while_waiting():
    lane = core.Lane("x")
    assert lane.run(lambda: {"ok": True, "n": 1}, timeout=1) == {"ok": True, "n": 1}
    fut = lane.start(time.sleep, 0.3)
    assert lane.start(time.sleep, 0.3) is None
    out = lane.wait(None, 0)
    assert out["ok"] is False and out["n"] == 1 and "still waiting since" in out["error"]
    fut.result()
    assert lane.start(lambda: {"ok": True}) is not None
