"""kalman_lna's boundary-forced move across units (docs/research/fixes/316-kalman_lna.md): a stock alone in its unit
with no outside outflow can lose only by a move into another stock, so a capped move may cross units there
(rows.py `movable`), and its cap is read off the receiver's floored row (rows.py `seeds`). A synthetic case with its
own numbers (not the ladder's): tickets wait for desks, min(0.7 waiting, 30 - 0.25 desks_busy), desks free at 0.6."""

from __future__ import annotations

import numpy as np

from sdlab.discovery.strategies.kalman_lna import rows


def _sim(T=300):
    t = np.arange(T + 1)
    demand = 50.0 + 30.0 * np.sin(2 * np.pi * t / 97)
    W, A = [5.0], [20.0]
    for k in range(T):
        take = min(0.7 * W[-1], 30.0 - 0.25 * A[-1])
        W.append(W[-1] + 0.4 * demand[k + 1] - take)
        A.append(A[-1] + take - 0.6 * A[-1])
    lv = {"waiting": [round(x, 7) for x in W], "busy": [round(x, 7) for x in A]}
    stocks = [{"id": "waiting", "unit": "tickets"}, {"id": "busy", "unit": "desks"}]
    run = {"t": list(t), "levels": lv, "boundary_declared": True,
           "boundary": {"waiting": {"in": ["estimate"]}, "busy": {"out": ["estimate"]}}}
    return stocks, run, {"inputs": {"demand": list(demand)}}


def test_the_move_crosses_units_where_the_boundary_forces_it():
    stocks, run, opts = _sim()
    W, A = (np.array(run["levels"][k]) for k in ("waiting", "busy"))
    room = 30.0 - 0.25 * A[:-1]
    assert np.sum(room < 0.7 * W[:-1]) > 20 and np.sum(room >= 0.7 * W[:-1]) > 20      # both regimes act
    proxy = [{"from": None, "to": "waiting", "ratio": 1, "rate": {"form": "proportional", "stock": "demand", "k": 0.3}},
             {"from": "busy", "to": None, "ratio": 1, "rate": {"form": "proportional", "stock": "busy", "k": 0.1}}]
    r = rows.revise({"flows": proxy}, stocks, run, opts)
    got = {(f["from"], f["to"]): f for f in r["flows"]}
    assert ("waiting", "busy") in got, r["flows"]
    move = got[("waiting", "busy")]["rate"]["expr"]
    ns = {"min": min, "max": max}
    for w, a in ((10.0, 20.0), (100.0, 40.0)):
        assert abs(eval(move, ns, {"waiting": w, "busy": a}) - min(0.7 * w, 30.0 - 0.25 * a)) < 0.01
    assert abs(got[("busy", None)]["rate"]["k"] - 0.6) < 1e-3


def test_no_move_across_units_without_a_declared_boundary():
    stocks, run, opts = _sim()
    run = {"t": run["t"], "levels": run["levels"]}
    proxy = [{"from": None, "to": "waiting", "ratio": 1, "rate": {"form": "proportional", "stock": "demand", "k": 0.3}},
             {"from": "busy", "to": None, "ratio": 1, "rate": {"form": "proportional", "stock": "busy", "k": 0.1}}]
    r = rows.revise({"flows": proxy}, stocks, run, opts)
    assert not any(f.get("from") == "waiting" and f.get("to") == "busy" for f in r["flows"])
