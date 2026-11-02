"""Refuter round for T16's three discovery changes (driverchoice's drain rule and alias test,
rediscover's widened window): what each must still do, and the three cases that refuted them
(a refused driver falling back to a constant that drained an empty source faster; a slow board
whose last hour held no move never widened; a cause acting 15 min later called a period alias),
which hold since the fixes."""

from __future__ import annotations

import random
from types import SimpleNamespace

import pytest

from orchestra.metrics import Point
from orchestra.metrics.file import FileMetrics
from orchestra.sd import rediscover as rd
from orchestra.sd.discover import fit_flow
from orchestra.sd.driverchoice import _empty
from orchestra.sd.model import Model
from orchestra.sd.path import Path
from orchestra.sd.strategies import CONSERVATION

T0 = 1_800_000_000.0
LIVE = [(T0, T0 + 3600)]


def _due_while_empty(form: dict, p: Path) -> float:
    c, k = form["params"].get("c", 0.0), form["params"].get("k", 0.0)
    if form["form"] == "constant":
        return sum(max(0.0, c) * (b - a) / 60 for a, b in _empty(p))
    return sum(p.expected(a, b, c, k) for a, b in _empty(p))


def _drain(seed: int, leak: float, k: float) -> tuple[Path, list]:
    """A stock filled in ten-minute bursts and drained, while it holds anything, by a timer
    (``leak`` a minute) and by each item (``k`` a minute each)."""
    rng = random.Random(seed)
    s, pts, out = 0, [(T0, 0.0)], []
    for i in range(1, 3600):
        t = T0 + i
        if rng.random() < (3.0 if (i // 600) % 2 == 0 else 0.0) / 60:
            s += 1
            pts.append((t, float(s)))
        if s > 0 and rng.random() < (leak + k * s) / 60:
            s -= 1
            out.append((t + 0.5, 1.0))
            pts.append((t + 0.5, float(s)))
    return Path.of(pts, LIVE, 60.0), out


@pytest.mark.parametrize("seed", range(4))
def test_a_timer_and_per_item_drain_of_a_stock_that_empties_is_still_fitted_as_a_drain(seed):
    p, events = _drain(seed, 0.3, 0.3)
    assert sum(b - a for a, b in _empty(p)) >= 600                 # empty ten minutes or more
    best = fit_flow(events, 60.0, {"s": p}, "s", set())[0]
    assert best["inputs"] == ["s"], best
    assert _due_while_empty(best, p) < 1.0, best


def test_an_outflow_whose_driver_is_refuted_for_draining_falls_back_to_no_worse_a_drain():
    """The commit's own end-to-end case (a demand with a base rate, its source never empty). The
    driver is refuted because its rate never falls below 0.5 + 2 × 1; what is kept instead is
    the constant, whose rate never falls below the mean, 5.5 a minute: the rule's own criterion,
    broken more by what it chose. Replayed on UC-1 and UC-3, all 11 of the flows it changed
    went the same way (uc3 READY_FOR_REVIEW → IN_REVIEW: 0.11 + 59 × level, ≈5 events due over
    the 44.7 min its source was empty, became the constant 0.489, ≈22 due)."""
    rng = random.Random(1)
    out, t, v = [], 0, 1.0
    while t < 3600:
        out.append((t, v))
        t += rng.randint(60, 300)
        v = 4.0 if v == 1.0 else 1.0
    demand = lambda x: next(val for start, val in reversed(out) if start <= x - T0)
    events = [(T0 + i, 1.0) for i in range(3600) if rng.random() < (0.5 + 2.0 * demand(T0 + i)) / 60]
    src = Path.of([(T0 + i, 5.0) for i in range(0, 3600, 15)], LIVE, 60.0)
    drv = Path.of([(T0 + i, demand(T0 + i)) for i in range(0, 3600, 15)], LIVE, 60.0)
    forms = fit_flow(events, 60.0, {"s": src, "d": drv}, "s", {"d"})
    best = forms[0]
    driver = next(f for f in forms if f["inputs"] == ["d"] and f["form"] == "linear")
    floor = lambda f, p: (f["params"]["c"] if f["form"] == "constant"
                          else min(max(0.0, f["params"].get("c", 0.0) + f["params"]["k"] * x) for x in p.time_at))
    p_best = drv if best["inputs"] == ["d"] else src
    assert floor(best, p_best) <= floor(driver, drv), (best["form"], best["params"], driver["params"])


def _project(tmp_path):
    return SimpleNamespace(key="p", state_dir=tmp_path, config=SimpleNamespace(
        discovery_strategy=CONSERVATION, discovery_options={}, discovery_window=3600.0, discovery_step=30.0,
        discovery_every=300.0, eras_from=None, prior_for=None))


NOW = 1_800_000_000.0


def _board(tmp_path, hours: float, every_h: float, phase: float) -> FileMetrics:
    """A board's level and its two counters, written each minute for ``hours`` up to now: one item
    added every ``every_h`` hours (at ``phase`` of each), one moved out ten minutes after every
    second."""
    adds = [NOW - hours * 3600 + (k + phase) * every_h * 3600 for k in range(int(hours / every_h))]
    outs = adds[1::2]
    m, pts = FileMetrics(tmp_path / "m.jsonl"), []
    labels = {"instrument": "board", "board": "b", "project": "p"}
    for i in range(int(hours * 60) + 1):
        t = NOW - hours * 3600 + 60 * i
        na, no = sum(x <= t for x in adds), sum(x + 600 <= t for x in outs)
        pts += [Point("board_items", float(na - no), t, labels), Point("board_items_added_total", float(na), t, labels),
                Point("board_items_moved_total", float(no), t, labels)]
    m.write(pts)
    return m


def test_a_slow_board_whose_last_hour_holds_a_move_gets_a_model_by_widening(tmp_path):
    r = rd.rediscover(_project(tmp_path), _board(tmp_path, 10.0, 2.0, 0.75), now=NOW, collectors=[])
    assert r.version == 1 and r.model.stocks, r.model.discovery.get("counter_events")
    assert r.model.discovery["widened"]["tried_s"] == [3600.0, 7200.0, 14400.0]


def test_a_slow_board_whose_last_hour_holds_no_move_gets_a_model_by_widening(tmp_path):
    # the same board, 10 h of one add every 2 h (five adds, two moves out), the last add 1 h ago:
    # counter_events was {"counters": 0}, and widen said a wider window was no help
    r = rd.rediscover(_project(tmp_path), _board(tmp_path, 10.0, 2.0, 0.5), now=NOW, collectors=[])
    assert r.version == 1 and r.model.stocks, r.model.discovery.get("counter_events")


def test_a_widened_window_stops_once_it_covers_all_the_history_there_is(tmp_path):
    # 4 h of history: the window doubled eight times, to 7 days, reading the same 4 h each time
    r = rd.rediscover(_project(tmp_path), _board(tmp_path, 4.0, 2.0, 0.5), now=NOW, collectors=[])
    assert r.version is None and r.model.discovery["widened"]["tried_s"] == [3600.0, 7200.0]
    assert r.model.discovery["window_s"] == 14400.0


def _switching(rng, hold=(120, 600)):
    out, t, v = [], -3600, 0.0
    while t < 3600:
        out.append((t, v))
        t += rng.randint(*hold)
        v = 1.0 - v
    return lambda t: next(val for start, val in reversed(out) if start <= t - T0)


def test_a_driver_acting_in_place_is_untouched_by_the_alias_test():
    for seed in range(10):
        rng = random.Random(seed)
        a = _switching(rng)
        events = [(T0 + i, 1.0) for i in range(3600) if rng.random() < (0.5 + 4.0 * a(T0 + i)) / 60]
        gauge = Path.of([(T0 + i, a(T0 + i)) for i in range(0, 3600, 15)], LIVE, 60.0)
        assert fit_flow(events, 60.0, {"input:a": gauge}, None, {"input:a"})[0]["inputs"] == ["input:a"], seed


def test_a_driver_that_acts_fifteen_minutes_later_is_not_called_a_period_alias():
    rng = random.Random(1)
    a = _switching(rng)                                     # random holds of 2 to 10 min: no period
    events = [(T0 + i, 1.0) for i in range(3600) if rng.random() < (0.5 + a(T0 + i) + 4.0 * a(T0 + i - 900)) / 60]
    gauge = Path.of([(T0 + i, a(T0 + i)) for i in range(0, 3600, 15)], LIVE, 60.0)
    best = fit_flow(events, 60.0, {"input:a": gauge}, None, {"input:a"})[0]
    assert not any("period alias" in r["why"] for r in best["driver"].get("refuted", [])), best["driver"]["refuted"]
    assert best["inputs"] == ["input:a"], best["driver"]


def test_widen_reads_counters_that_did_not_move_and_stops_at_the_oldest_point():
    m = Model("system", "The system")
    m.discovery = {"counters_read": 2, "counter_events": {"counters": 0, "most": 0.0, "needed": 5}}
    assert rd.widen(m, 3600.0, 30.0, NOW, None) == (7200.0, 60.0)               # read, not moved: widened
    assert rd.widen(m, 3600.0, 30.0, NOW, None, NOW - 1800) is None             # the window holds all there is
    m.discovery["counters_read"] = 0
    assert rd.widen(m, 3600.0, 30.0, NOW, None) is None                         # no counter at all
