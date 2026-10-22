"""structures' repair of unexplained rows (repair.py, docs/research/fixes/310-structures.md)."""

import numpy as np

from sdlab.discovery.strategies.structures import repair

STOCKS = [{"id": "a", "unit": "jobs"}, {"id": "b", "unit": "jobs"}, {"id": "c", "unit": "jobs", "final": True}]


def _run(n=300):
    # a gets the input u; a -> b at 0.1 a, b -> a at 0.3 b, b -> outside at 0.2 b, a -> c (a counter) at 0.4 a
    u = 50 + 20 * np.sin(np.arange(n) / 11.0)
    a, b, c = [100.0], [10.0], [0.0]
    for k in range(n - 1):
        ab, ba, bo, ac = 0.1 * a[-1], 0.3 * b[-1], 0.2 * b[-1], 0.4 * a[-1]
        a.append(a[-1] + u[k + 1] - ab + ba - ac)
        b.append(b[-1] + ab - ba - bo)
        c.append(c[-1] + ac)
    lv = {"a": list(np.round(a, 4)), "b": list(np.round(b, 4)), "c": list(np.round(c, 4))}
    run = {"t": list(range(n)), "levels": lv, "boundary_declared": True,
           "boundary": {"a": {"in": ["input"], "out": []}, "b": {"in": [], "out": ["estimate"]}, "c": {"in": [], "out": []}}}
    return run, {"inputs": {"u": list(u)}}


TRUE_REST = [{"from": None, "to": "a", "rate": {"form": "proportional", "stock": "u", "k": 1.0}},
             {"from": "a", "to": "c", "rate": {"form": "proportional", "stock": "a", "k": 0.4}}]


def test_missing_moves_and_a_dead_outflow_are_repaired():
    run, opts = _run()
    # the answer lost both moves; b's outflow is floored dead
    flows = TRUE_REST + [{"from": "b", "to": None, "rate": {"form": "linear", "c": -0.4, "terms": [{"stock": "b", "k": -0.001}]}}]
    r = repair.apply({"flows": flows}, STOCKS, run, opts)
    assert r["repair"]["kept"]
    got = {(f["from"], f["to"]): f["rate"] for f in r["flows"]}
    assert abs(got[("a", "b")]["k"] - 0.1) < 1e-4 and abs(got[("b", "a")]["k"] - 0.3) < 1e-4
    out = got[("b", None)]
    k = out["k"] if out.get("form") == "proportional" else next(t["k"] for t in out["terms"] if t["stock"] == "b")
    assert abs(k - 0.2) < 1e-4
    assert got[(None, "a")]["k"] == 1.0                     # the declared input side is held


def test_exact_answer_is_left_alone():
    run, opts = _run()
    flows = TRUE_REST + [{"from": "a", "to": "b", "rate": {"form": "proportional", "stock": "a", "k": 0.1}},
                         {"from": "b", "to": "a", "rate": {"form": "proportional", "stock": "b", "k": 0.3}},
                         {"from": "b", "to": None, "rate": {"form": "proportional", "stock": "b", "k": 0.2}}]
    r = repair.apply({"flows": flows}, STOCKS, run, opts)
    assert r["flows"] == flows
