"""sindy's coflows.py (port-sindy): on exact data, a co-flow written into a row the answer does not reproduce is
dropped (its flow kept); a co-flow on a row the answer reproduces is kept; data with noise are left alone."""

import copy
import math

import numpy as np

from sdlab.discovery.strategies.sindy import coflows

STOCKS = [{"id": "a", "unit": "u"}, {"id": "b", "unit": "u"}, {"id": "c", "unit": "u"}]


def _run(kink: bool, noise: float = 0.0, n: int = 300, seed: int = 0) -> dict:
    """a fed from outside, a -> b at 0.2 a, b drains 0.1 b; c is fed at 5 a step and loses 0.1 x what moves
    from a to b (a co-flow) or, with kink, max(0, a - 50) (a floored gap no linear row reproduces)."""
    rng = np.random.default_rng(seed)
    t = np.arange(n)
    u = 10 + 5 * np.sin(2 * math.pi * t / 40)
    A, Bs, C = [40.0], [20.0], [100.0]
    for i in range(n - 1):
        mv = 0.2 * A[i]
        A.append(A[i] + u[i] - mv)
        Bs.append(Bs[i] + mv - 0.1 * Bs[i])
        C.append(C[i] + 5 - (max(0.0, A[i] - 50) if kink else 0.1 * mv))
    lv = {"a": np.round(A, 6), "b": np.round(Bs, 6), "c": np.round(C, 6)}
    if noise:
        lv = {k: v + rng.normal(0, noise, n) for k, v in lv.items()}
    return {"t": [float(x) for x in t], "levels": {k: list(v) for k, v in lv.items()}}


def _answer(run: dict) -> dict:
    a = np.asarray(run["levels"]["a"])
    u = np.diff(a) + 0.2 * a[:-1]
    flows = [
        {"from": None, "to": "a", "rate": {"form": "constant", "value": float(np.mean(u))}},
        {"from": "a", "to": "b", "rate": {"form": "proportional", "stock": "a", "k": 0.2}, "uses": [{"stock": "c", "per": 0.1}]},
        {"from": "b", "to": None, "rate": {"form": "proportional", "stock": "b", "k": 0.1}},
        {"from": None, "to": "c", "rate": {"form": "constant", "value": 5.0}},
    ]
    return {"flows": flows}


def test_a_coflow_on_a_row_the_answer_misses_is_dropped():
    run = _run(kink=True)
    r = coflows.apply(_answer(run), STOCKS, run, {})
    ab = next(f for f in r["flows"] if f["from"] == "a" and f["to"] == "b")
    assert "uses" not in ab and r["coflows_dropped"] == ["a -> b uses c"]


def test_a_coflow_the_row_needs_is_kept():
    run = _run(kink=False)
    ans = _answer(run)
    r = coflows.apply(copy.deepcopy(ans), STOCKS, run, {})
    assert r["flows"] == ans["flows"] and "coflows_dropped" not in r


def test_noisy_data_are_left_alone():
    run = _run(kink=True, noise=0.5)
    ans = _answer(run)
    r = coflows.apply(copy.deepcopy(ans), STOCKS, run, {})
    assert r["flows"] == ans["flows"]
