"""The host's event collector survives a replay that fails at start (retried, with the eras, quiet
machines and intended-model announcements still looked at meanwhile), counts a backlog in full
and in order, and, in a host that does not launch, deletes and writes no counters."""

import os
import subprocess
import threading
import time

import pytest

from orchestra import host as host_mod
from orchestra import runtime
from orchestra.collectors import EVENTS
from orchestra.config import init_project
from orchestra.events import Events
from orchestra.host import Host
from orchestra.metrics import Point, for_project


@pytest.fixture
def bare(tmp_path, monkeypatch):
    monkeypatch.setenv("ORCHESTRATOR_HOME", str(tmp_path / "home"))
    r = tmp_path / "bare"
    r.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=r, check=True)
    monkeypatch.setattr(host_mod, "ERAS_EVERY_S", 0.01)
    return init_project(r)


def _total(project, type_="x.happened", source="m") -> float | None:
    got = for_project(project).latest(EVENTS, {"project": project.key, "type": type_, "source": source})
    return got[1] if got else None


def _run(host: Host, counts: bool = True) -> threading.Thread:
    t = threading.Thread(target=host._collect, args=(counts,), daemon=True)
    t.start()
    return t


def _until(cond, s: float = 10.0) -> bool:
    end = time.time() + s
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.02)
    return cond()


def test_a_replay_that_fails_is_retried_and_the_looks_run_meanwhile(bare, monkeypatch):
    Events.for_project(bare, source="m").publish("x.happened", {})
    h = Host(bare, collect_every=0.02)
    looks = []
    monkeypatch.setattr(h, "_eras", lambda: looks.append("eras"))
    monkeypatch.setattr(h, "_intent", lambda after_discovery=False: looks.append("intent"))
    real, calls = h.events.after, []

    def flaky(offset):
        calls.append(offset)
        if len(calls) == 1:
            raise ConnectionError("bus down")
        return real(offset)
    monkeypatch.setattr(h.events, "after", flaky)
    t = _run(h)
    try:
        assert _until(lambda: _total(bare) == 1.0)
        assert "eras" in looks and "intent" in looks
        assert t.is_alive()
        assert runtime.read(bare)["hosts"][str(os.getpid())]["collector"]["state"] == "following"
    finally:
        h.stop()
        t.join(5)
    log = (bare.logs_dir / "orchestra-host.log").read_text()
    assert "collector: replay failed: ConnectionError: bus down; retrying" in log


def test_a_backfill_whose_write_fails_once_recovers(bare, monkeypatch):
    Events.for_project(bare, source="m").publish("x.happened", {})
    store_cls = type(for_project(bare))
    real, failed = store_cls.write, []

    def write_once_failing(self, points):
        if not failed:
            failed.append(1)
            raise OSError("disk full")
        return real(self, points)
    monkeypatch.setattr(store_cls, "write", write_once_failing)
    h = Host(bare, collect_every=0.02)
    t = _run(h)
    try:
        assert _until(lambda: _total(bare) == 1.0)
        assert failed and t.is_alive()
    finally:
        h.stop()
        t.join(5)


def test_a_backlog_is_counted_in_full_and_in_order(bare, monkeypatch):
    pub = Events.for_project(bare, source="m")
    pub.publish("x.happened", {})
    h = Host(bare, collect_every=0.3)
    t = _run(h)
    try:
        assert _until(lambda: _total(bare) == 1.0)
        for _ in range(1500):                        # more than one read used to keep (only its tail)
            pub.publish("x.happened", {})
        assert _until(lambda: _total(bare) == 1501.0, 20)
    finally:
        h.stop()
        t.join(5)


def test_a_second_host_deletes_nothing_and_writes_no_counters(bare):
    Events.for_project(bare, source="m").publish("x.happened", {})
    for_project(bare).write([Point(EVENTS, 7.0, time.time(), {"project": bare.key, "type": "x.happened", "source": "m"})])
    h = Host(bare, collect_every=0.02)
    t = _run(h, counts=False)
    try:
        assert _until(lambda: runtime.read(bare).get("hosts", {}).get(str(os.getpid()), {}).get("collector", {}).get("state") == "following")
        Events.for_project(bare, source="m").publish("x.happened", {})
        time.sleep(0.3)
        assert _total(bare) == 7.0                   # the launching host's counters, untouched
    finally:
        h.stop()
        t.join(5)
