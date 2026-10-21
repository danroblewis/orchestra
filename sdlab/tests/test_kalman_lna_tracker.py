"""kalman_lna's tracker.py (docs/research/fixes/308-kalman_lna.md): a counted stock driven towards a target
read off another stock replaces its outside flows where it wins, and nothing changes where there is none."""

from __future__ import annotations

import math

import numpy as np

from sdlab.discovery.strategies.kalman_lna import tracker


def _controlled(T=300, a=190.0, b=150.0, H=14, L=3):
    rng = np.random.default_rng(1)
    x = 1500 + 900 * np.sin(np.arange(T + 1) / 20.0) + rng.normal(0, 50, T + 1)
    s = [8.0]
    for k in range(T):
        up = max(0, min(H, math.ceil(x[k] / a)) - s[-1])
        dn = 1.0 * (s[-1] > max(L, math.ceil(x[k] / b)))
        s.append(s[-1] + up - dn)
    return x, np.array(s)


def _run(x, s, declared=True):
    stocks = [{"id": "x"}, {"id": "s"}]
    run = {"t": list(range(len(s))), "levels": {"x": list(x), "s": list(s)}}
    if declared:
        run.update(boundary={"x": {"in": ["estimate"], "out": ["estimate"]}, "s": {"in": ["estimate"], "out": ["estimate"]}},
                   boundary_declared=True)
    return stocks, run


def test_tracker_replaces_a_linear_proxy():
    x, s = _controlled()
    stocks, run = _run(x, s)
    flows = [{"from": None, "to": "s", "ratio": 1, "rate": {"form": "constant", "c": 0.1}},
             {"from": "s", "to": None, "ratio": 1, "rate": {"form": "proportional", "stock": "s", "k": 0.01}}]
    r = tracker.revise({"flows": flows}, stocks, run, {})
    got = {(f["from"], f["to"]): f["rate"]["expr"] for f in r["flows"] if f.get("id", "").startswith("tracker")}
    assert set(got) == {(None, "s"), ("s", None)}
    assert "ceil(x /" in got[(None, "s")] and "ceil(x /" in got[("s", None)]
    assert r["tracker"][0]["sse"][1] < 1e-9
    assert r["tracker"][0]["in"]["form"] == "gap" and r["tracker"][0]["out"]["form"] == "step"


def test_tracker_leaves_a_linear_stock_alone():
    rng = np.random.default_rng(2)
    T = 300
    x = 1000 + rng.normal(0, 30, T + 1)
    s = [50.0]
    for k in range(T):
        s.append(s[-1] + 5 + rng.normal(0, 1) - 0.1 * s[-1])
    stocks, run = _run(x, np.array(s))
    flows = [{"from": None, "to": "s", "ratio": 1, "rate": {"form": "constant", "c": 5.0}},
             {"from": "s", "to": None, "ratio": 1, "rate": {"form": "proportional", "stock": "s", "k": 0.1}}]
    r = tracker.revise({"flows": flows}, stocks, run, {})
    assert "tracker" not in r and r["flows"] == flows


def test_tracker_keeps_to_the_declared_sides():
    x, s = _controlled()
    stocks, run = _run(x, s)
    run["boundary"]["s"] = {"in": [], "out": []}
    flows = [{"from": "x", "to": "s", "ratio": 1, "rate": {"form": "proportional", "stock": "x", "k": 0.0}}]
    r = tracker.revise({"flows": flows}, stocks, run, {})
    assert "tracker" not in r
