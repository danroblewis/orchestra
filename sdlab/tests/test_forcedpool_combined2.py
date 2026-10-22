"""combined2 (2026-10-22, k8s-316, docs/research/fixes/316-combined2.md): a move the declared boundary forces across
units (capmin.forced_pairs), and a block holding a capacity limit re-read around it (sparseblock)."""

import math

import numpy as np

from sdlab.discovery.strategies.combined2 import capmin, sparseblock


def _stocks(extra_conn=False):
    s = [{"id": "q", "unit": "requests"}, {"id": "p", "unit": "requests"}, {"id": "done", "unit": "requests", "final": True},
         {"id": "w", "unit": "queries"}, {"id": "a", "unit": "connections"}]
    if extra_conn:
        s.append({"id": "idle", "unit": "connections"})
    return s


BOUNDARY = {"q": {"in": ["input"], "out": []}, "w": {"in": ["estimate"], "out": []}, "a": {"in": [], "out": ["estimate"]}}


def test_forced_pairs_only_where_the_boundary_leaves_no_other_drawing():
    run = {"boundary": BOUNDARY, "boundary_declared": True}
    assert capmin.forced_pairs(_stocks(), run) == {("w", "a")}
    assert capmin.forced_pairs(_stocks(), {"boundary": BOUNDARY}) == set()          # not declared: one unit per move
    assert ("w", "a") not in capmin.forced_pairs(_stocks(extra_conn=True), run)     # a's unit holds another stock


def _run():
    T = 400
    t = np.arange(T + 1, dtype=float)
    traffic = 300 + 250 * np.sin(2 * math.pi * t / 288)
    L = {"q": [50.0], "p": [80.0], "done": [0.0], "w": [10.0], "a": [20.0]}
    for k in range(T):
        q, p, w, a = (L[x][-1] for x in ("q", "p", "w", "a"))
        disp, fin = 0.6 * q, 0.5 * p
        acq = max(0.0, min(0.8 * w, 80 - 0.2 * a))
        L["q"].append(q + traffic[k + 1] - disp)
        L["p"].append(p + disp - fin)
        L["done"].append(L["done"][-1] + fin)
        L["w"].append(w + 0.3 * p - acq)
        L["a"].append(a + acq - 0.8 * a)
    levels = {k: [round(v, 4) for v in vs] for k, vs in L.items()}
    run = {"t": list(t), "levels": levels, "boundary": BOUNDARY, "boundary_declared": True}
    return run, {"inputs": {"traffic": list(traffic)}}


def test_a_block_with_a_limit_is_reread_around_it():
    run, opts = _run()
    w = np.array(run["levels"]["w"][:-1])
    a = np.array(run["levels"]["a"][:-1])
    assert np.any(80 - 0.2 * a < 0.8 * w) and np.any(80 - 0.2 * a > 0.8 * w)   # the limit binds on part of the run
    limit = {"id": "lim", "from": "w", "to": "a", "ratio": 1,
             "rate": {"form": "expr", "expr": "min(0.8 * w, max(0, 80.0 * 1 + -0.2 * a))"}}
    flows = [{"from": None, "to": "q", "rate": {"form": "proportional", "stock": "traffic", "k": 1.0}},
             {"from": "q", "to": "p", "rate": {"form": "proportional", "stock": "q", "k": 0.6}},
             {"from": "p", "to": "done", "rate": {"form": "proportional", "stock": "p", "k": 0.5}},
             limit,
             {"from": None, "to": "w", "rate": {"form": "linear", "c": -60.0, "terms": [{"stock": "q", "k": 0.2}]}},
             {"from": "a", "to": None, "rate": {"form": "linear", "c": -7.0, "terms": [{"stock": "done", "k": 0.001}]}}]
    out = sparseblock.apply({"flows": flows}, _stocks(), run, opts)
    assert out.get("sparse_blocks") and out["sparse_blocks"][0]["rows"] == ["a", "w"]
    got = {(f.get("from"), f.get("to")): f for f in out["flows"]}
    assert got[("w", "a")]["rate"] == limit["rate"]                                 # held as it was
    inflow = {t["stock"]: t["k"] for t in got[(None, "w")]["rate"]["terms"]}
    assert set(inflow) == {"p"} and abs(inflow["p"] - 0.3) < 1e-4
    drain = got[("a", None)]["rate"]
    assert hinge_terms(drain) == {"a"} and abs(drain["terms"][0]["k"] - 0.8) < 1e-4


def hinge_terms(rate):
    return {t["stock"] for t in rate.get("terms") or []}
