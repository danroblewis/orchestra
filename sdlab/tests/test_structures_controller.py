"""structures' controller form (controller.py, docs/research/fixes/308-structures.md)."""

import math

import numpy as np

from sdlab.discovery.strategies.structures import controller


def _run(n=400, seed=1):
    rng = np.random.default_rng(seed)
    x = 1500 + 900 * np.sin(np.arange(n) / 20) + rng.normal(0, 50, n)
    s = [9.0]
    for i in range(n - 1):
        up = max(0, min(16, math.ceil(x[i] / 190)) - s[-1])
        dn = 1.0 * (s[-1] > max(3, math.ceil(x[i] / 155)))
        s.append(s[-1] + up - dn)
    return {"t": list(range(n)), "levels": {"s": s, "x": list(x)}}


def test_recovers_gap_up_unit_down():
    run = _run()
    stocks = [{"id": "s"}, {"id": "x"}]
    fake = {"flows": [{"from": None, "to": "s", "rate": {}}, {"from": "s", "to": None, "rate": {}}]}
    r = controller.apply(fake, stocks, run, {})
    (note,) = r["controller"]
    assert note["in"].startswith("max(0, ") and "ceil(x / 19" in note["in"]
    assert "ceil(x / 15" in note["out"]          # one unit or the whole gap: on this run both reproduce every step
    s = np.asarray(run["levels"]["s"])
    for side, sign in (("in", 1), ("out", -1)):
        f = next(g for g in r["flows"] if g["id"] == f"controller_s_{side}")["controller"]
        assert np.array_equal(controller._amounts(side, s[:-1], np.asarray(run["levels"]["x"])[:-1], f), np.maximum(sign * np.diff(s), 0))


def test_leaves_smooth_stocks_and_moves():
    run = {"t": [0, 1, 2, 3], "levels": {"a": [1.5, 2.0, 2.5, 3.1], "b": [1.0, 2.0, 3.0, 2.0]}}
    flows = [{"from": "b", "to": "a", "rate": {}}]
    assert controller.apply({"flows": flows}, [{"id": "a"}, {"id": "b"}], run, {})["flows"] == flows


def test_simple_number():
    assert controller._simple(191.5, 192.7) == 192
    assert controller._simple(157.3, 157.7) == 157.5
