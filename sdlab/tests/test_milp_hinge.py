"""milp's floored gap flows (hinge.py, k8s-309): a create-what-is-missing gap recovered, a plain drain left alone."""

import numpy as np

from sdlab.discovery.strategies.milp import hinge


def _pods(n=300):
    k = np.arange(n)
    desired = 6 + np.round(3 * np.sin(k / 20.0))
    pending, ready = np.zeros(n), np.zeros(n)
    ready[0] = desired[0]
    for i in range(n - 1):
        created = max(0.0, desired[i] - pending[i] - ready[i])
        started = 0.5 * pending[i]
        deleted = max(0.0, ready[i] - desired[i])
        pending[i + 1] = pending[i] + created - started
        ready[i + 1] = ready[i] + started - deleted
    return desired, pending, ready


def _run(desired, pending, ready):
    stocks = [{"id": s, "unit": "pods"} for s in ("desired", "pending", "ready")]
    run = {"t": list(range(len(desired))), "levels": {"desired": list(desired), "pending": list(pending), "ready": list(ready)},
           "boundary": {"pending": {"in": ["estimate"]}, "ready": {"out": ["estimate"]}}, "boundary_declared": True}
    return stocks, run


def _rate(flows, src, dst):
    f = next(f for f in flows if f["from"] == src and f["to"] == dst)
    r = f["rate"]
    if r["form"] == "proportional":
        return {r["stock"]: r["k"]}
    return {t["stock"]: t["k"] for t in r.get("terms") or []}


def test_gap_recovered_from_a_shrunk_linear_answer():
    stocks, run = _run(*_pods())
    shrunk = [{"from": None, "to": "pending", "ratio": 1, "rate": {"form": "linear", "c": 0.0, "terms": [
                  {"stock": "desired", "k": 0.34}, {"stock": "ready", "k": -0.34}, {"stock": "pending", "k": -0.33}]}},
              {"from": "pending", "to": "ready", "ratio": 1, "rate": {"form": "proportional", "stock": "pending", "k": 0.6}},
              {"from": "ready", "to": None, "ratio": 1, "rate": {"form": "proportional", "stock": "ready", "k": 0.003}}]
    flows, note = hinge.refine(shrunk, stocks, run, {}, skip={"desired"})
    assert note["used"]
    c = _rate(flows, None, "pending")
    assert abs(c["desired"] - 1) < 1e-3 and abs(c["ready"] + 1) < 1e-3 and abs(c["pending"] + 1) < 1e-3
    assert abs(_rate(flows, "pending", "ready")["pending"] - 0.5) < 1e-3
    d = _rate(flows, "ready", None)
    assert abs(d["ready"] - 1) < 1e-3 and abs(d["desired"] + 1) < 1e-3


def test_plain_drain_left_alone():
    n = 300
    x = np.zeros(n)
    x[0] = 50
    u = 10 + 5 * np.sin(np.arange(n) / 15.0)
    for i in range(n - 1):
        x[i + 1] = x[i] + u[i + 1] - 0.2 * x[i]
    stocks = [{"id": "x", "unit": "items"}]
    run = {"t": list(range(n)), "levels": {"x": list(x)}, "boundary": {"x": {"in": ["input"], "out": ["estimate"]}},
           "boundary_declared": True}
    flows = [{"from": None, "to": "x", "ratio": 1, "rate": {"form": "proportional", "stock": "u", "k": 1.0}, "input": "u"},
             {"from": "x", "to": None, "ratio": 1, "rate": {"form": "proportional", "stock": "x", "k": 0.2}}]
    out, note = hinge.refine(flows, stocks, run, {"inputs": {"u": list(u)}})
    assert not note.get("used")
    assert out == flows
