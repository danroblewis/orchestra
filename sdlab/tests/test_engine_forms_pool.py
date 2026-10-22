"""engine_forms's pool.py and earn.py (k8s-316): a move the declared boundary forces across units, read from its two
rows on noisy (whole-number) data; and a move that earns nothing on the rows dropped."""

import math

import numpy as np

from sdlab.discovery.strategies.engine_forms import capmin, earn, pool


def _counts_pool(n=2000, seed=1):
    """Two services' queries wait (waiting, unit queries) and get connections at min(0.8 waiting, 80 - 0.2 active)
    (active, unit connections), released at 0.8 active; every flow a whole-number (Poisson) draw."""
    rng = np.random.default_rng(seed)
    t = np.arange(n)
    a_in = np.round(300 + 250 * np.sin(2 * math.pi * t / 288))
    b_in = np.round(250 + 200 * np.sin(2 * math.pi * (t + 30) / 288))
    W, A = [10.0], [60.0]
    for i in range(n - 1):
        q = rng.poisson(0.06 * a_in[i]) + rng.poisson(0.1 * b_in[i])
        got = min(W[i], rng.poisson(max(0.0, min(0.8 * W[i], 80 - 0.2 * A[i]))))
        out = min(A[i], rng.poisson(0.8 * A[i]))
        W.append(W[i] + q - got)
        A.append(A[i] + got - out)
    levels = {"svc_a": list(a_in), "svc_b": list(b_in), "waiting": W, "active": A}
    run = {"t": [float(x) for x in t], "levels": levels, "boundary_declared": True,
           "boundary": {"svc_a": {"in": ["estimate"], "out": ["estimate"]}, "svc_b": {"in": ["estimate"], "out": ["estimate"]},
                        "waiting": {"in": ["estimate", "estimate"]}, "active": {"out": ["estimate"]}}}
    stocks = [{"id": "svc_a", "unit": "requests"}, {"id": "svc_b", "unit": "requests"},
              {"id": "waiting", "unit": "queries"}, {"id": "active", "unit": "connections"}]
    return stocks, run


def test_forced_pairs_need_a_declared_boundary_and_one_stock_a_unit():
    stocks, run = _counts_pool(n=50)
    assert capmin.forced_pairs(stocks, run) == [("waiting", "active")]
    assert capmin.forced_pairs(stocks, {**run, "boundary_declared": False}) == []
    two = stocks + [{"id": "idle", "unit": "connections"}]
    assert capmin.forced_pairs(two, run) == []                       # active is not alone in its unit


def test_a_forced_pool_is_read_from_both_rows_on_counts():
    stocks, run = _counts_pool()
    wrong = [{"from": None, "to": "waiting", "rate": {"form": "linear", "c": -50.0, "terms": [{"stock": "svc_b", "k": 0.3}]}},
             {"from": "active", "to": None, "rate": {"form": "constant", "value": 7.0}},
             {"from": None, "to": "svc_a", "rate": {"form": "constant", "value": 0.0}}]
    r = pool.apply({"flows": wrong}, stocks, run, {})
    assert r.get("pool"), r
    got = {}
    for f in r["flows"]:
        got.setdefault((f["from"], f["to"]), []).append(f)
    expr = got[("waiting", "active")][0]["rate"]["expr"]
    for w, a in [(10.0, 60.0), (120.0, 80.0), (60.0, 79.0)]:
        val = eval(expr, {"__builtins__": {}}, {"min": min, "waiting": w, "active": a})
        assert abs(val - min(0.8 * w, 80 - 0.2 * a)) < 0.1 * min(0.8 * w, 80 - 0.2 * a)
    ins = {f["rate"]["stock"]: f["rate"]["k"] for f in got[(None, "waiting")]}
    assert abs(ins["svc_a"] - 0.06) < 0.006 and abs(ins["svc_b"] - 0.1) < 0.01
    assert abs(got[("active", None)][0]["rate"]["k"] - 0.8) < 0.08


def test_a_move_that_earns_nothing_is_dropped_and_a_real_one_kept():
    rng = np.random.default_rng(3)
    n = 1500
    t = np.arange(n)
    src = np.round(200 + 150 * np.sin(2 * math.pi * t / 288))
    Q, P, D = [50.0], [80.0], [0.0]
    for i in range(n - 1):
        inn = rng.poisson(0.3 * src[i])
        mv = min(Q[i], rng.poisson(0.6 * Q[i]))
        done = min(P[i], rng.poisson(0.5 * P[i]))
        Q.append(Q[i] + inn - mv)
        P.append(P[i] + mv - done)
        D.append(D[i] + done)
    run = {"t": [float(x) for x in t], "levels": {"src": list(src), "q": Q, "p": P, "d": D}, "boundary_declared": True,
           "boundary": {"src": {"in": ["estimate"], "out": ["estimate"]}, "q": {"in": ["estimate"]}}}
    stocks = [{"id": "src", "unit": "r"}, {"id": "q", "unit": "r"}, {"id": "p", "unit": "r"}, {"id": "d", "unit": "r", "final": True}]
    flows = [{"from": None, "to": "q", "rate": {"form": "proportional", "stock": "src", "k": 0.33}},
             {"from": "q", "to": "p", "rate": {"form": "proportional", "stock": "q", "k": 0.55}},
             {"from": "p", "to": "d", "rate": {"form": "proportional", "stock": "p", "k": 0.45}},
             {"from": "p", "to": "q", "rate": {"form": "proportional", "stock": "src", "k": 0.02}}]   # spurious
    r = earn.apply({"flows": flows}, stocks, run, {})
    assert r.get("earn"), r
    pairs = {(f["from"], f["to"]): f["rate"] for f in r["flows"]}
    assert ("p", "q") not in pairs and ("q", "p") in pairs and ("p", "d") in pairs
    assert abs(pairs[("q", "p")]["k"] - 0.6) < 0.03 and abs(pairs[(None, "q")]["k"] - 0.3) < 0.02
