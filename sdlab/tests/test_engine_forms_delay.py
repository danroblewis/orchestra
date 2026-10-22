"""engine_forms (k8s-312): a MIN branch that binds on a few steps is still read (reread.pieces' last small
piece); two pieces whose lin column is 0 on one of them still make a floored MIN (reread.two_regimes); and a
stock fed from outside through a hidden DELAY1 stage is written as that stage (delay.py)."""

import math

import numpy as np

from sdlab.discovery.strategies.engine_forms import delay, reread


def _rows(cols: dict, n: int):
    names = list(cols) + ["1"]
    Z = np.vstack([np.asarray(cols[k], float) for k in cols] + [np.ones(n)])
    return reread._Rows(None, Z, names, 1e-4), names


def test_a_min_branch_binding_on_a_few_steps_is_read():
    n = 300
    t = np.arange(n)
    q = 50 + 30 * np.sin(2 * math.pi * t / 97)
    r = np.where((t % 60) < 2, 0.6, 2.0)                          # the cap binds on 10 of 300 steps (under 5%)
    i = 20 + 5 * np.cos(2 * math.pi * t / 41)
    y = np.round(-0.5 * i + np.minimum(0.6 * q, 25 * r), 4)
    rows, names = _rows({"q": np.round(q, 4), "r": r, "i": np.round(i, 4)}, n)
    assert np.sum(25 * r < 0.6 * q) < 0.05 * n
    got = rows.two_regimes(y)
    assert got is not None
    lin, s, u, v = got
    named = lambda d: {names[j]: x for j, x in d.items()}  # noqa: E731
    assert s > 0 and abs(named(lin)["i"] + 0.5) < 1e-3
    assert {tuple(named(u)), tuple(named(v))} == {("q",), ("r",)}


def _stage_run(n=400, least=0.0):
    """nodes fed from outside through a DELAY1 (2 steps) of 0.1 x the pods that do not fit, removed at 0.05 x
    the nodes above half the pods; the pods follow a demand."""
    t = np.arange(n)
    pods = np.round(8 + 6 * np.sin(2 * math.pi * t / 120) + 3 * (t % 50 > 40), 4)
    N, H = [3.0], [0.0]
    for k in range(n - 1):
        need = 0.1 * max(0.0, pods[k] - 4 * N[k])
        out = 0.05 * max(0.0, N[k] - max(least, pods[k] / 2))
        N.append(N[k] + 0.5 * H[k] - out)
        H.append(H[k] + need - 0.5 * H[k])
    N = np.round(np.array(N), 4)
    return {"t": [float(x) for x in t], "levels": {"pods": list(pods), "nodes": list(N)},
            "boundary": {"pods": {}, "nodes": {"in": ["estimate"], "out": ["estimate"]}}, "boundary_declared": True}


def test_a_stock_fed_through_a_hidden_delay_is_a_stage():
    run = _stage_run()
    stocks = [{"id": "pods", "unit": "pods"}, {"id": "nodes", "unit": "nodes"}]
    wrong = [{"from": None, "to": "nodes", "rate": {"form": "constant", "value": 0.01}}]
    r = delay.apply({"flows": wrong}, stocks, run, {})
    assert r.get("delay"), r
    got = {(f["from"], f["to"]): f for f in r["flows"]}
    drain = got[("stage_nodes", "nodes")]
    assert abs(drain["rate"]["k"] - 0.5) < 1e-3
    fed = got[(None, "stage_nodes")]["rate"]
    terms = {x["stock"]: x["k"] for x in fed["terms"]}
    assert abs(terms["pods"] - 0.1) < 1e-3 and abs(terms["nodes"] + 0.4) < 1e-3
    out = got[("nodes", None)]["rate"]
    terms = {x["stock"]: x["k"] for x in out["terms"]}
    assert abs(terms["nodes"] - 0.05) < 1e-3 and abs(terms["pods"] + 0.025) < 1e-3
    assert len(r["inferred_levels"]["stage_nodes"]) == len(run["t"])


def test_a_removal_with_a_minimum_is_a_floored_min():
    run = _stage_run(n=600, least=2.0)                  # nodes above max(2, pods / 2) removed: the 2 binds at low demand
    stocks = [{"id": "pods", "unit": "pods"}, {"id": "nodes", "unit": "nodes"}]
    r = delay.apply({"flows": [{"from": None, "to": "nodes", "rate": {"form": "constant", "value": 0.01}}]}, stocks, run, {})
    assert r.get("delay"), r
    out = {(f["from"], f["to"]): f for f in r["flows"]}[("nodes", None)]["rate"]
    assert out["form"] == "expr"
    for pods, nodes in [(2.0, 5.0), (3.0, 3.5), (10.0, 7.0), (12.0, 4.0)]:
        want = 0.05 * max(0.0, nodes - max(2.0, pods / 2))
        got = max(0.0, eval(out["expr"], {"__builtins__": {}}, {"max": max, "min": min, "pods": pods, "nodes": nodes}))
        assert abs(got - want) < 1e-3


def test_noisy_levels_leave_the_stage_alone():
    run = _stage_run()
    rng = np.random.default_rng(0)
    run["levels"]["nodes"] = list(np.asarray(run["levels"]["nodes"]) + rng.normal(0, 0.05, len(run["t"])))
    stocks = [{"id": "pods", "unit": "pods"}, {"id": "nodes", "unit": "nodes"}]
    wrong = [{"from": None, "to": "nodes", "rate": {"form": "constant", "value": 0.01}}]
    r = delay.apply({"flows": wrong}, stocks, run, {})
    assert not r.get("delay")
