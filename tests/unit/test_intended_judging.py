"""Judging what the intended model expects (docs/proposals/intended-model.md §2; §10 tests 27, 28):
``rises`` / ``falls`` against the slope before the change, and targets on their mean."""

import time

from orchestra.metrics import Point
from orchestra.metrics.file import FileMetrics
from orchestra.sd.intended.facts import Facts, judged
from orchestra.sd.model import SeriesRef
from orchestra.sd.predictions import check
from orchestra.sd.verdict import outcome, slope, unpredicted

RISES = {"kind": "slope", "stock": "features", "direction": "rises"}


def line(rate, n=30, start=0.0, wiggle=0.3):
    return [[start + 60 * i, rate * 60 * i + (wiggle if i % 2 else -wiggle)] for i in range(n)]


def test_rises_is_met_when_the_slope_after_exceeds_the_slope_before():
    got = slope(RISES, {"features": line(0.01, start=-1800)}, {"features": line(0.05)})
    assert got["status"] == "met" and got["z"] >= 2


def test_rises_is_absent_when_the_slope_is_unchanged_though_the_level_rose():
    got = slope(RISES, {"features": line(0.03, start=-1800)}, {"features": line(0.03)})
    assert got["status"] == "absent"
    assert outcome([got], [], [], None) == "no effect"


def test_falls_and_the_other_way():
    falls = {**RISES, "direction": "falls"}
    assert slope(falls, {"features": line(0.05, start=-1800)}, {"features": line(0.0)})["status"] == "met"
    assert slope(RISES, {"features": line(0.05, start=-1800)}, {"features": line(0.0)})["status"] == "different"
    assert slope(RISES, {}, {"features": line(0.1)})["status"] == "waiting"


def test_the_grammar_takes_rises_and_a_named_stock_is_not_unpredicted():
    p = check({"change": "c", "expect": [{"stock": "features", "rises": True}], "horizon_s": 60})
    assert p["expect"] == [RISES]
    comparison = {"flows": [], "stocks": {"appeared": ["features"]}}
    assert unpredicted(p["expect"], comparison, [], None) == []


def test_a_flow_target_is_judged_on_its_count_over_the_window_and_a_stock_on_its_mean_level(tmp_path):
    m = FileMetrics(tmp_path / "metrics.jsonl")
    now = time.time()
    m.write([Point("landed_total", float(i), now - 3600 + 600 * i, {"instrument": "i"}) for i in range(7)])
    m.write([Point("queue", v, now - 300 + 100 * i, {"instrument": "i"}) for i, v in enumerate([2.0, 4.0, 6.0])])
    f = Facts(m, now=now)
    count = f.count([SeriesRef("landed_total", {"instrument": "i"})], 3600, "t")
    assert count == 6.0
    assert judged({"op": "above", "value": 5, "over_s": 3600}, count, False)["met"] == "met"
    mean = f.mean_level(SeriesRef("queue", {"instrument": "i"}), 400, "t")
    assert mean == 4.0
    assert judged({"op": "within", "value": 1, "hi": 3, "over_s": 400}, mean, False)["met"] == "missed"
    assert judged({"op": "below", "value": 1, "over_s": 1}, None, False)["met"] == "unknown"
