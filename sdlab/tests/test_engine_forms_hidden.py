"""engine_forms's hidden.py (k8s-310 round 1): on exact data, a row the answer misses that reads a per-unit column
and a hidden integrator (filled at a constant rate, drained by the per-unit fraction of a counted flow) is written
with the model's own hidden stock; noisy rows are left alone."""

import math

import numpy as np

from sdlab.discovery.strategies.engine_forms import hidden

TABLE = [[100.0, 0.0], [300.0, 0.0], [330.0, 0.3]]


def _t(m):
    return float(np.interp(m, [p[0] for p in TABLE], [p[1] for p in TABLE]))


def _run(noise=0.0, n=400, seed=0):
    rng = np.random.default_rng(seed)
    t = np.arange(n)
    R = np.round(6 + 3 * np.sin(2 * math.pi * t / 70))               # pods (measured, driven from outside)
    X = np.round(200 + 80 * np.sin(2 * math.pi * t / 37), 4)         # requests in flight (measured)
    M, H, K = [150.0], [0.0], [0.0]
    for i in range(n - 1):
        frac = _t(M[i])
        M.append(M[i] + 0.5 * (100 + H[i] + 2 * X[i] / max(1.0, R[i])) - 0.5 * M[i])
        H.append(H[i] + 1.0 - H[i] * frac)
        K.append(K[i] + R[i] * frac)
    M, K = np.round(np.array(M), 4), np.round(np.array(K), 4)
    if noise:
        M = M + rng.normal(0, noise, n)
    run = {"t": [float(x) for x in t], "levels": {"pods": list(R), "inflight": list(X), "mem": list(M), "kills": list(K)},
           "boundary": {"pods": {"in": ["estimate"], "out": ["estimate"]}, "inflight": {"in": ["estimate"], "out": ["estimate"]},
                        "mem": {"in": ["estimate"], "out": ["estimate"]}, "kills": {"in": ["estimate"]}},
           "boundary_declared": True}
    return run, np.array(H)


STOCKS = [{"id": "pods", "unit": "pods"}, {"id": "inflight", "unit": "requests"}, {"id": "mem", "unit": "MiB"},
          {"id": "kills", "unit": "pods", "final": True}]
ANSWER = [{"from": None, "to": "kills", "rate": {"form": "proportional", "stock": "pods", "k": 1.0},
           "effects": [{"stock": "mem", "shape": "table", "points": TABLE}]},
          {"from": None, "to": "mem", "rate": {"form": "constant", "value": 120.0}},
          {"from": "mem", "to": None, "rate": {"form": "proportional", "stock": "mem", "k": 0.4}}]


def test_a_row_reading_a_hidden_integrator_gets_its_own_hidden_stock():
    run, H = _run()
    r = hidden.apply({"flows": ANSWER}, STOCKS, run, {})
    assert r.get("hidden"), r.get("hidden")
    fl = {(f["from"], f["to"]): f for f in r["flows"]}
    assert (None, "hidden_mem") in fl and ("hidden_mem", None) in fl
    assert fl[("hidden_mem", None)]["effects"] == ANSWER[0]["effects"]               # drained by the counted fraction
    e = fl[(None, "mem")]["rate"]["expr"]
    assert "hidden_mem" in e and "inflight / max(1, pods)" in e
    assert fl[("mem", None)]["rate"]["terms"][0]["k"] == pytest_approx(0.5)


def test_a_noisy_row_is_left_alone():
    run, _ = _run(noise=2.0)
    r = hidden.apply({"flows": ANSWER}, STOCKS, run, {})
    assert not r.get("hidden")
    assert r["flows"] == ANSWER


def pytest_approx(x, rel=1e-3):
    import pytest
    return pytest.approx(x, rel=rel)
