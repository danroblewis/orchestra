"""structures' floored outside rates (floor.py, docs/research/fixes/309-structures.md)."""

import numpy as np

from sdlab.discovery.strategies.structures import floor


def _run(n=300):
    # a: a target that wanders; b: filled at 0.3 x (a - b) when below a, its surplus over a deleted at once
    a = 10 + 6 * np.sin(np.arange(n) / 9.0)
    b = [10.0]
    for i in range(n - 1):
        up = 0.3 * max(0.0, a[i] - b[-1])
        dn = max(0.0, b[-1] - a[i])
        b.append(b[-1] + up - dn)
    return {"t": list(range(n)), "levels": {"a": list(np.round(a, 6)), "b": list(np.round(b, 6))},
            "boundary": {"b": {"in": "estimate", "out": "estimate"}}, "boundary_declared": True}


def test_floored_surplus_outflow_replaces_a_drift_and_a_spurious_move():
    run = _run()
    stocks = [{"id": "a"}, {"id": "b"}]
    # what a linear fit gives: a drift on the outflow and a move from a soaking up the misfit
    flows = [{"from": None, "to": "b", "rate": {"form": "linear", "c": 0.0, "terms": [{"stock": "a", "k": 0.3}, {"stock": "b", "k": -0.3}]}},
             {"from": "b", "to": None, "rate": {"form": "proportional", "stock": "b", "k": 0.05}},
             {"from": "a", "to": "b", "rate": {"form": "proportional", "stock": "a", "k": 0.02}}]
    r = floor.apply({"flows": flows}, stocks, run, {})
    out = next(f for f in r["flows"] if f.get("from") == "b" and f.get("to") is None)["rate"]
    k = {t["stock"]: t["k"] for t in out["terms"]}
    assert abs(k["b"] - 1) < 1e-3 and abs(k["a"] + 1) < 1e-3
    assert not any(f.get("from") == "a" and f.get("to") == "b" for f in r["flows"])


def test_leaves_a_rate_whose_floor_never_binds():
    n = 200
    x = [5.0]
    for _ in range(n - 1):
        x.append(x[-1] + 2.0 - 0.2 * x[-1])
    run = {"t": list(range(n)), "levels": {"x": x}, "boundary": {"x": {"in": "estimate", "out": "estimate"}}, "boundary_declared": True}
    flows = [{"from": None, "to": "x", "rate": {"form": "constant", "value": 2.0}},
             {"from": "x", "to": None, "rate": {"form": "proportional", "stock": "x", "k": 0.2}}]
    assert floor.apply({"flows": flows}, [{"id": "x"}], run, {})["flows"] == flows
