"""matrix_v2's port of the kubernetes climb's fixes (docs/research/fixes/port-matrix_v2.md): its tracker copy takes a
stage the answer feeds a stock through and a still stock's smeared moves with the outside flows it replaces, and a
move that is 0 on every nonnegative state is dropped (dead.py)."""

from __future__ import annotations

import math

import numpy as np

from sdlab.discovery.strategies.matrix_v2 import dead, tracker


def _controlled(T=300, a=190.0, b=150.0, H=14, L=3):
    rng = np.random.default_rng(1)
    x = 1500 + 900 * np.sin(np.arange(T + 1) / 20.0) + rng.normal(0, 50, T + 1)
    s = [8.0]
    for k in range(T):
        up = max(0, min(H, math.ceil(x[k] / a)) - s[-1])
        dn = 1.0 * (s[-1] > max(L, math.ceil(x[k] / b)))
        s.append(s[-1] + up - dn)
    return x, np.array(s)


def _run(x, s, extra=None):
    lv = {"x": list(x), "s": list(s), **(extra or {})}
    stocks = [{"id": k} for k in lv]
    bd = {k: {"in": ["estimate"], "out": ["estimate"]} for k in lv}
    return stocks, {"t": list(range(len(s))), "levels": lv, "boundary": bd, "boundary_declared": True}


def test_a_stage_into_the_controlled_stock_goes_with_its_outside_flows():
    x, s = _controlled()
    stocks, run = _run(x, s)
    T = len(s) - 1
    h = list(np.full(T + 1, 2.0))
    flows = [{"from": None, "to": "s_hidden", "ratio": 1, "rate": {"form": "constant", "c": 0.02}},
             {"from": "s_hidden", "to": "s", "ratio": 1, "rate": {"form": "proportional", "stock": "s_hidden", "k": 0.01}},
             {"from": "s", "to": None, "ratio": 1, "rate": {"form": "proportional", "stock": "s", "k": 0.001}}]
    r = tracker.revise({"flows": flows, "inferred_levels": {"s_hidden": h}}, stocks, run, {})
    ends = {(f["from"], f["to"]) for f in r["flows"]}
    assert ends == {(None, "s"), ("s", None)}                       # the stage is gone, one flow per side
    assert "s_hidden" not in (r.get("inferred_levels") or {})


def test_a_still_stocks_smeared_move_is_left_out():
    x, s = _controlled()
    y = 50 + 0.5 * np.arange(len(s))                                  # a partner the move would feed
    stocks, run = _run(x, s, {"y": list(y)})
    flows = [{"from": None, "to": "s", "ratio": 1, "rate": {"form": "constant", "c": 0.1}},
             {"from": "s", "to": "y", "ratio": 1, "rate": {"form": "proportional", "stock": "s", "k": 0.05}},
             {"from": None, "to": "y", "ratio": 1, "rate": {"form": "constant", "c": 0.1}}]
    r = tracker.revise({"flows": flows}, stocks, run, {})
    ends = {(f["from"], f["to"]) for f in r["flows"]}
    assert ("s", "y") not in ends and (None, "s") in ends and ("s", None) in ends
    assert r["tracker"][0]["sse"][1] < 1e-9 and r["tracker"][0].get("moves_dropped") == 1


def test_dead_moves_are_dropped_and_nothing_else():
    lv = {"a": [1.0, 2.0, 3.0], "b": [0.0, 1.0, 0.5], "c": [-1.0, 0.0, 1.0]}
    stocks = [{"id": k} for k in lv]
    flows = [{"from": "a", "to": "b", "ratio": 1, "rate": {"form": "proportional", "stock": "a", "k": -2.0}},
             {"from": "a", "to": "b", "ratio": 1, "rate": {"form": "linear", "c": 0.0, "terms": [{"stock": "a", "k": -1.0}, {"stock": "b", "k": 0.1}]}},
             {"from": "b", "to": "a", "ratio": 1, "rate": {"form": "proportional", "stock": "c", "k": -1.0}},    # c goes negative
             {"from": "a", "to": None, "ratio": 1, "rate": {"form": "proportional", "stock": "a", "k": -1.0}}]   # an outside side
    r = dead.apply({"flows": flows}, stocks, {"levels": lv}, {})
    assert r["flows"] == flows[1:] and r["dead_moves"] == ["a -> b"]
