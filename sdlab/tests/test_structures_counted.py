"""structures' counted move with a threshold effect (counted.py, docs/research/fixes/310-structures.md)."""

import numpy as np

from sdlab.discovery.strategies.structures import counted


def _run(n=300):
    # x rises past 50; above it a moves to b at a x 0.02 x (x - 50) a step, counted in c; b returns at 0.5 b
    x = 30 + 30 * np.arange(n) / n + 5 * np.sin(np.arange(n) / 7.0)
    a, b, c = [10.0], [0.0], [0.0]
    for i in range(n - 1):
        kill = a[-1] * min(1.0, max(0.0, 0.02 * (x[i] - 50)))
        back = 0.5 * b[-1]
        a.append(a[-1] - kill + back)
        b.append(b[-1] + kill - back)
        c.append(c[-1] + kill)
    lv = {"a": a, "b": b, "c": c, "x": list(x)}
    return {"t": list(range(n)), "levels": {k: list(np.round(v, 9)) for k, v in lv.items()},
            "boundary": {"c": {"in": "estimate"}, "x": {"in": "estimate", "out": "estimate"}}, "boundary_declared": True}


STOCKS = [{"id": "a", "unit": "pods"}, {"id": "b", "unit": "pods"}, {"id": "c", "unit": "pods", "final": True}, {"id": "x", "unit": "MiB"}]


def test_counter_gets_the_effect_and_the_move_it_counts():
    run = _run()
    flows = [{"from": "b", "to": "a", "rate": {"form": "proportional", "stock": "b", "k": 0.5}},
             {"from": None, "to": "c", "rate": {"form": "constant", "value": 0.05}},
             {"from": None, "to": "x", "rate": {"form": "constant", "value": 0.1}}]
    r = counted.apply({"flows": flows}, STOCKS, run, {})
    note = r["counted"][0]
    assert note["counter"] == "c" and note["reads"] == "a" and note["effect"] == "x" and note["move"] == "a -> b"
    inflow = next(f for f in r["flows"] if f.get("to") == "c")
    pts = inflow["effects"][0]["points"]
    assert abs(np.interp(50.0, *zip(*pts)) - 0.0) < 1e-3 and abs(np.interp(55.0, *zip(*pts)) - 0.1) < 2e-3


def test_counter_fed_by_a_plain_rate_is_left_alone():
    n = 200
    a = 10 + 3 * np.sin(np.arange(n) / 5.0)
    c = np.concatenate([[0.0], np.cumsum(0.1 * a[:-1])])
    run = {"t": list(range(n)), "levels": {"a": list(a), "c": list(c)}, "boundary": {"c": {"in": "estimate"}}, "boundary_declared": True}
    flows = [{"from": None, "to": "c", "rate": {"form": "proportional", "stock": "a", "k": 0.1}}]
    r = counted.apply({"flows": flows}, [{"id": "a", "unit": "u"}, {"id": "c", "unit": "u", "final": True}], run, {})
    assert r["flows"] == flows
