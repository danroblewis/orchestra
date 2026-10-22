"""kalman_lna's rows.py (docs/research/fixes/309-kalman_lna.md): each stock's row read off the data, and the flows of
the stocks the answer misses rebuilt from the rows (moves by unit, floored outside flows on declared sides)."""

from __future__ import annotations

import numpy as np

from sdlab.discovery.strategies.kalman_lna import rows


def _pods(T=300):
    """desired jumps to a new whole number every 6 steps; pending gets max(0, desired - pending - ready); pending ->
    ready at 0.4; ready loses max(0, ready - desired)."""
    rng = np.random.default_rng(5)
    D = np.repeat(rng.integers(3, 13, T // 6 + 1).astype(float), 6)[: T + 1]
    P, R = [0.0], [6.0]
    for k in range(T):
        c = max(0.0, D[k] - P[-1] - R[-1])
        m = 0.4 * P[-1]
        d = max(0.0, R[-1] - D[k])
        P.append(round(P[-1] + c - m, 6))
        R.append(round(R[-1] + m - d, 6))
    return D, np.array(P), np.array(R)


def _case():
    D, P, R = _pods()
    stocks = [{"id": "desired", "unit": "pods"}, {"id": "pending", "unit": "pods"}, {"id": "ready", "unit": "pods"}]
    run = {"t": list(range(len(D))), "levels": {"desired": list(D), "pending": list(P), "ready": list(R)},
           "boundary": {"desired": {"in": ["estimate"], "out": ["estimate"]}, "pending": {"in": ["estimate"], "out": []},
                        "ready": {"in": [], "out": ["estimate"]}}, "boundary_declared": True}
    return stocks, run


def test_rows_rebuild_floored_flows_and_the_move():
    stocks, run = _case()
    proxy = [{"from": None, "to": "pending", "ratio": 1, "rate": {"form": "constant", "value": 0.3}},
             {"from": "pending", "to": "ready", "ratio": 1, "rate": {"form": "proportional", "stock": "pending", "k": 0.5}},
             {"from": "ready", "to": None, "ratio": 1, "rate": {"form": "constant", "value": 0.1}}]
    r = rows.revise({"flows": proxy}, stocks, run, {})
    assert set(r["rows"]["rebuilt"]) >= {"pending", "ready"}
    got = {(f["from"], f["to"]): f["rate"] for f in r["flows"]}
    assert abs(got[("pending", "ready")]["k"] - 0.4) < 1e-6
    inflow = {t["stock"]: t["k"] for t in got[(None, "pending")]["terms"]}
    assert all(abs(inflow[s] - k) < 1e-4 for s, k in {"desired": 1, "pending": -1, "ready": -1}.items())
    out = {t["stock"]: t["k"] for t in got[("ready", None)]["terms"]}
    assert all(abs(out[s] - k) < 1e-4 for s, k in {"ready": 1, "desired": -1}.items())
    assert ("pending", None) not in got                       # pending has no declared outflow


def test_rows_leave_a_fitted_answer_alone():
    rng = np.random.default_rng(3)
    T = 300
    a, b = [50.0], [20.0]
    for _ in range(T):
        a.append(a[-1] + 5 - 0.1 * a[-1] + rng.normal(0, 0.5))
        b.append(b[-1] + 0.1 * a[-2] - 0.2 * b[-1] + rng.normal(0, 0.5))
    stocks = [{"id": "a", "unit": "u"}, {"id": "b", "unit": "u"}]
    run = {"t": list(range(T + 1)), "levels": {"a": a, "b": b}}
    flows = [{"from": None, "to": "a", "ratio": 1, "rate": {"form": "constant", "value": 5.0}},
             {"from": "a", "to": "b", "ratio": 1, "rate": {"form": "proportional", "stock": "a", "k": 0.1}},
             {"from": "b", "to": None, "ratio": 1, "rate": {"form": "proportional", "stock": "b", "k": 0.2}}]
    r = rows.revise({"flows": flows}, stocks, run, {})
    assert "rows" not in r and r["flows"] == flows


def test_a_fixed_drain_leaves_the_floored_inflow_free_to_read_its_own_stock():
    """(309 regression from 065afa3) where pending's first row reads pending plain and max(0, desired - ready) floored,
    the refit with its drain fixed at what the move takes must let the floored term read pending itself, or the gap
    desired - pending - ready is lost (without the fix: 0.895 desired - 0.897 ready)."""
    T, move = 300, 0.6
    D = np.clip(np.round(8 + 5 * np.sin(2 * np.pi * np.arange(T + 1) / 90)), 3, 16).astype(float)
    P, R = [0.0], [6.0]
    for k in range(T):
        c, m, d = max(0.0, D[k] - P[-1] - R[-1]), move * P[-1], max(0.0, R[-1] - D[k])
        P.append(round(P[-1] + c - m, 6))
        R.append(round(R[-1] + m - d, 6))
    stocks = [{"id": "desired", "unit": "pods"}, {"id": "pending", "unit": "pods"}, {"id": "ready", "unit": "pods"}]
    run = {"t": list(range(T + 1)), "levels": {"desired": list(D), "pending": P, "ready": R},
           "boundary": {"desired": {"in": ["estimate"], "out": ["estimate"]}, "pending": {"in": ["estimate"], "out": []},
                        "ready": {"in": [], "out": ["estimate"]}}, "boundary_declared": True}
    proxy = [{"from": None, "to": "pending", "ratio": 1, "rate": {"form": "constant", "value": 0.3}},
             {"from": "pending", "to": "ready", "ratio": 1, "rate": {"form": "proportional", "stock": "pending", "k": 0.5}},
             {"from": "ready", "to": None, "ratio": 1, "rate": {"form": "constant", "value": 0.1}}]
    got = {(f["from"], f["to"]): f["rate"] for f in rows.revise({"flows": proxy}, stocks, run, {})["flows"]}
    inflow = {t["stock"]: t["k"] for t in got[(None, "pending")]["terms"]}
    assert all(abs(inflow.get(s, 0.0) - k) < 1e-3 for s, k in {"desired": 1, "pending": -1, "ready": -1}.items())
