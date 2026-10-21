"""engine_forms's reread.py (k8s-309): on exact data, a unit whose rows the answer misses is read again row by
row, with a floored linear outside flow where one hinge explains a row; noisy rows are left alone."""

import math

import numpy as np

from sdlab.discovery.strategies.engine_forms import reread


def _run(noise=0.0, n=300, seed=0):
    rng = np.random.default_rng(seed)
    t = np.arange(n)
    goal = np.round(8 + 4 * np.sin(2 * math.pi * t / 90))          # a target count, read by the gap
    P, R = [0.0], [8.0]
    for i in range(n - 1):
        created = max(0.0, goal[i] - P[i] - R[i])
        started = 0.5 * P[i]
        deleted = max(0.0, R[i] - goal[i])
        P.append(P[i] + created - started)
        R.append(R[i] + started - deleted)
    P, R = np.round(np.array(P), 4), np.round(np.array(R), 4)
    if noise:
        P, R = P + rng.normal(0, noise, n), R + rng.normal(0, noise, n)
    return {"t": [float(x) for x in t], "levels": {"goal": list(goal), "pending": list(P), "ready": list(R)},
            "boundary": {"goal": {"in": ["estimate"], "out": ["estimate"]}, "pending": {"in": ["estimate"]},
                         "ready": {"out": ["estimate"]}}, "boundary_declared": True}


STOCKS = [{"id": "goal", "unit": "pods"}, {"id": "pending", "unit": "pods"}, {"id": "ready", "unit": "pods"}]
WRONG = [{"from": "pending", "to": "ready", "rate": {"form": "proportional", "stock": "pending", "k": 0.6}},
         {"from": None, "to": "pending", "rate": {"form": "constant", "value": 0.05}},
         {"from": "ready", "to": None, "rate": {"form": "constant", "value": 0.03}},
         {"from": None, "to": "goal", "rate": {"form": "constant", "value": 0.01}}]


def _terms(f):
    r = f["rate"]
    if r["form"] == "proportional":
        return {r["stock"]: r["k"]}
    return {x["stock"]: x["k"] for x in r.get("terms") or []}


def test_hinged_rows_are_read_as_floored_linear_flows():
    r = reread.apply({"flows": WRONG}, STOCKS, _run(), {})
    assert r.get("reread"), r
    got = {(f["from"], f["to"]): _terms(f) for f in r["flows"]}
    move = got[("pending", "ready")]
    assert abs(move["pending"] - 0.5) < 1e-3
    created = got[(None, "pending")]
    assert all(abs(created.get(k, 0) - v) < 1e-3 for k, v in {"goal": 1, "pending": -1, "ready": -1}.items())
    deleted = got[("ready", None)]
    assert all(abs(deleted.get(k, 0) - v) < 1e-3 for k, v in {"ready": 1, "goal": -1}.items())
    assert (None, "goal") in got                      # a row no form reproduces keeps its own outside flows


def test_noisy_rows_are_left_alone():
    r = reread.apply({"flows": WRONG}, STOCKS, _run(noise=0.3), {})
    assert not r.get("reread")
    assert r["flows"] == WRONG
