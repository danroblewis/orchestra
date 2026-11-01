"""Stopping mid-discovery (sd/bounded.py): the strategy's child is killed, the discovery stops
(``Stopped``, not ``Late``) and saves nothing; nothing is started after a stop; Ctrl-C while
waiting leaves no child."""

import os
import subprocess
import sys
import threading
import time
from types import SimpleNamespace

import pytest
from test_discover import simulate  # pytest puts this folder on the path

from orchestra.metrics.file import FileMetrics
from orchestra.sd import bounded
from orchestra.sd.store import ModelStore
from orchestra.sd.strategies import CONSERVATION, discover_with

SLEEPER = [sys.executable, "-c", "import time; time.sleep(60)"]


def _gone(pid: int) -> bool:
    for _ in range(100):
        try:
            done, _ = os.waitpid(pid, os.WNOHANG)
        except ChildProcessError:
            return True
        if done:
            return True
        time.sleep(0.05)
    return False


def _kill_when_running():
    def go():
        for _ in range(200):
            if bounded._running:
                break
            time.sleep(0.02)
        bounded.kill_running()
    t = threading.Thread(target=go)
    t.start()
    return t


def test_a_strategy_stopped_mid_discovery_propagates_and_is_not_a_late_strategy(tmp_path, monkeypatch):
    store = FileMetrics(tmp_path / "m.jsonl")
    start, end = simulate(store, minutes=30)
    monkeypatch.setattr("orchestra.sd.strategies.handed", lambda base: [s for s in base.stocks if s.series is not None])
    monkeypatch.setattr("orchestra.sd.strategies.run_jobs", lambda jobs, deadline: bounded._bounded(SLEEPER, "", 60.0))
    killer = _kill_when_running()
    with pytest.raises(bounded.Stopped):
        discover_with(store.dump("", {"project": "p"}), start=start, end=end, step=30, strategy="fake", deadline=60)
    killer.join(10)


def test_a_discovery_stopped_mid_run_writes_no_version_and_no_discovered_model(tmp_path, monkeypatch):
    from orchestra.sd import rediscover as rd
    project = SimpleNamespace(key="p", state_dir=tmp_path, config=SimpleNamespace(
        discovery_strategy="fake", discovery_options={}, discovery_window=600.0, discovery_step=30.0, discovery_every=300.0))

    def a_strategy_that_sleeps(*a, **kw):
        bounded._bounded(SLEEPER, "", 60.0)
        raise AssertionError("not reached: the strategy was killed")
    monkeypatch.setattr(rd.simulated, "discovered", a_strategy_that_sleeps)
    killer = _kill_when_running()
    with pytest.raises(bounded.Stopped):
        rd.rediscover(project, FileMetrics(tmp_path / "m.jsonl"))
    killer.join(10)
    ms = ModelStore.for_state(tmp_path)
    assert ms.latest_discovery() is None and ms.load() is None
    assert not list(tmp_path.rglob("discovered*.json"))


def test_nothing_is_started_after_a_stop(monkeypatch):
    bounded.kill_running()

    def no_spawn(*a, **kw):
        raise AssertionError("a strategy was started after the stop")
    monkeypatch.setattr(subprocess, "Popen", no_spawn)
    with pytest.raises(bounded.Stopped):
        bounded._bounded(SLEEPER, "", 60.0)


def test_ctrl_c_while_waiting_on_a_strategy_leaves_no_child(monkeypatch):
    seen = []
    real = subprocess.Popen.communicate

    def interrupted(self, *a, **kw):
        if not seen:
            seen.append(self.pid)
            raise KeyboardInterrupt
        return real(self, *a, **kw)
    monkeypatch.setattr(subprocess.Popen, "communicate", interrupted)
    with pytest.raises(KeyboardInterrupt):
        bounded._bounded(SLEEPER, "", 60.0)
    assert seen and _gone(seen[0]), "the strategy's process outlived Ctrl-C"
    assert not bounded._running


def test_conservation_alone_never_spawns(tmp_path):
    bounded.kill_running()                    # stopped: conservation runs in-process, unaffected
    store = FileMetrics(tmp_path / "m.jsonl")
    start, end = simulate(store, minutes=10)
    assert discover_with(store.dump("", {"project": "p"}), start=start, end=end, step=30, strategy=CONSERVATION).stocks
