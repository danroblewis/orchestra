"""A window too quiet for any counter is widened before "no model" (sd.rediscover.widen): R3, a
sprint board ("the sprint board itself is low traffic", the owner, 2026-11-02) had no model after
5.7 h of an hour's window holding two tickets' moves. The window doubles with its step, up to 7
days and never past the era's start, and the record says which windows were read."""

from __future__ import annotations

from types import SimpleNamespace

from orchestra.metrics.file import FileMetrics
from orchestra.sd import rediscover as rd
from orchestra.sd.model import Model, Stock
from orchestra.sd.strategies import CONSERVATION

NOW = 1_800_000_000.0


def _found(stocks: int, most: float) -> Model:
    m = Model("system", "The system")
    m.stocks = [Stock(f"s{i}", f"s{i}", evidence={}) for i in range(stocks)]
    m.discovery = {"counter_events": {"counters": 2, "most": most, "needed": 5}}
    return m


def test_widen_doubles_with_its_step_until_a_counter_has_the_events():
    assert rd.widen(_found(0, 2.0), 3600.0, 30.0, NOW, None) == (7200.0, 60.0)
    assert rd.widen(_found(0, 5.0), 3600.0, 30.0, NOW, None) is None          # enough events: nothing balanced, said as is
    assert rd.widen(_found(1, 2.0), 3600.0, 30.0, NOW, None) is None          # a model
    assert rd.widen(_found(0, 2.0), 4 * 86400.0, 30.0, NOW, None) == (7 * 86400.0, 52.5)
    assert rd.widen(_found(0, 2.0), 7 * 86400.0, 30.0, NOW, None) is None
    assert rd.widen(_found(0, 2.0), 3600.0, 30.0, NOW, NOW - 1800) is None    # the era began inside the window
    nothing = _found(0, 0.0)
    nothing.discovery["counter_events"]["counters"] = 0
    assert rd.widen(nothing, 3600.0, 30.0, NOW, None) is None                 # no counter moved at all: a wider window is no help


def test_rediscover_reads_wider_windows_and_says_which(tmp_path, monkeypatch):
    project = SimpleNamespace(key="p", state_dir=tmp_path, config=SimpleNamespace(
        discovery_strategy=CONSERVATION, discovery_options={}, discovery_window=3600.0, discovery_step=30.0, discovery_every=300.0,
        eras_from=None, prior_for=None))
    windows = []

    def discovered(*a, **k):
        windows.append((k["end"] - k["start"], k["step"]))
        m = _found(1 if len(windows) == 3 else 0, 6.0 if len(windows) == 3 else 2.0)
        m.discovery.update(start=k["start"], end=k["end"], step=k["step"], left_out={})
        return m

    monkeypatch.setattr(rd.simulated, "discovered", discovered)
    r = rd.rediscover(project, FileMetrics(tmp_path / "m.jsonl"), now=NOW)
    assert windows == [(3600.0, 30.0), (7200.0, 60.0), (14400.0, 120.0)]
    w = r.model.discovery["widened"]
    assert (w["from_s"], w["tried_s"], w["window_s"], w["step_s"]) == (3600.0, [3600.0, 7200.0], 14400.0, 120.0)
    assert w["why"] == "the 1 h window held too few events for any counter (a balance needs 5): widened to 4 h"
    assert r.model.discovery["window_s"] == 14400.0 and r.version == 1
