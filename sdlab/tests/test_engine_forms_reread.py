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


def _killed_run(noise=0.0, n=300, seed=1):
    """The pod chain above plus kills: ready -> pending at ready x T(mem) (none below 480, rising after),
    counted by a final stock; mem a measured level rising and falling."""
    rng = np.random.default_rng(seed)
    t = np.arange(n)
    goal = np.round(8 + 4 * np.sin(2 * math.pi * t / 90))
    mem = np.round(450 + 40 * np.sin(2 * math.pi * t / 70), 4)
    table = lambda m: np.interp(m, [0, 480, 512, 5000], [0, 0, 0.3, 0.3])  # noqa: E731
    P, R, K = [0.0], [8.0], [0.0]
    for i in range(n - 1):
        created = max(0.0, goal[i] - P[i] - R[i])
        started = 0.5 * P[i]
        deleted = max(0.0, R[i] - goal[i])
        killed = R[i] * float(table(mem[i]))
        P.append(P[i] + created - started + killed)
        R.append(R[i] + started - deleted - killed)
        K.append(K[i] + killed)
    P, R, K = (np.round(np.array(x), 4) for x in (P, R, K))
    if noise:
        P, R, K = P + rng.normal(0, noise, n), R + rng.normal(0, noise, n), K + rng.normal(0, noise, n)
    run = _run(n=n)
    run["levels"] = {"goal": list(goal), "pending": list(P), "ready": list(R), "kills": list(K), "mem": list(mem)}
    run["boundary"] = {**run["boundary"], "kills": {"in": ["estimate"]}, "mem": {"in": ["estimate"], "out": ["estimate"]}}
    return run


KSTOCKS = STOCKS + [{"id": "kills", "unit": "pods", "final": True}, {"id": "mem", "unit": "MiB"}]
KWRONG = WRONG + [{"from": None, "to": "kills", "rate": {"form": "constant", "value": 0.02}},
                  {"from": None, "to": "mem", "rate": {"form": "constant", "value": 0.0}}]


def test_a_counter_that_is_a_level_times_a_table_is_a_measured_flow():
    r = reread.apply({"flows": KWRONG}, KSTOCKS, _killed_run(), {})
    assert r.get("reread"), r
    got = {(f["from"], f["to"]): f for f in r["flows"]}
    move = got[("ready", "pending")]
    assert move["rate"]["stock"] == "ready" and abs(move["rate"]["k"] - 1) < 1e-3
    assert move["effects"][0]["stock"] == "mem"
    pts = move["effects"][0]["points"]
    assert abs(np.interp(486.0, *zip(*pts)) - float(np.interp(486.0, [480, 512], [0, 0.3]))) < 1e-3
    assert got[(None, "kills")]["effects"][0]["stock"] == "mem"
    assert abs(_terms(got[("pending", "ready")])["pending"] - 0.5) < 1e-3


def test_a_noisy_counter_is_left_alone():
    r = reread.apply({"flows": KWRONG}, KSTOCKS, _killed_run(noise=0.3), {})
    assert not r.get("reread")


def test_a_table_with_no_start_inside_the_data_range_is_none():
    # Y sits on its two extremes (19 at 0, one at 1): every grid start is an end of the range, none inside it
    # (engine_forms 307 counts-long crashed with "'NoneType' object is not subscriptable" here).
    z = np.array([0.0] * 19 + [1.0])
    x = np.ones(20)
    y = x * (z == 0)
    assert reread._table(y, x, z, 1) is None
    assert reread._table(y, x, z, 2) is None


def _room_run(n=600):
    """(k-311) The pod chain with a node pool: a pending pod starts only into the room the nodes leave,
    started = min(0.3 pending, max(0, nodes - ready)) (one pod a node); nodes measured, added one by one."""
    t = np.arange(n)
    goal = np.round(8 + 4 * np.sin(2 * math.pi * t / 90))
    nodes = 4 + np.floor((t % 30) / 3)
    P, R = [0.0], [8.0]
    for i in range(n - 1):
        created = max(0.0, goal[i] - P[i] - R[i])
        started = min(0.3 * P[i], max(0.0, nodes[i] - R[i]))
        deleted = max(0.0, R[i] - goal[i])
        P.append(P[i] + created - started)
        R.append(R[i] + started - deleted)
    P, R = np.round(np.array(P), 4), np.round(np.array(R), 4)
    seconds = np.round(np.concatenate([[0.0], np.cumsum(R[:-1])]), 4)      # a linear counter: the data are exact
    run = _run(n=n)
    run["levels"] = {"goal": list(goal), "pending": list(P), "ready": list(R), "nodes": list(nodes), "pod_seconds": list(seconds)}
    run["boundary"] = {**run["boundary"], "nodes": {}, "pod_seconds": {"in": ["estimate"]}}
    return run


def test_a_start_limited_by_room_is_a_min_move():
    stocks = STOCKS + [{"id": "nodes", "unit": "nodes"}, {"id": "pod_seconds", "unit": "s", "final": True}]
    r = reread.apply({"flows": WRONG}, stocks, _room_run(), {})
    assert r.get("reread"), r
    got = {(f["from"], f["to"]): f for f in r["flows"]}
    move = got[("pending", "ready")]
    assert move["rate"]["form"] == "expr" and move.get("id")
    expr = move["rate"]["expr"]
    env = {"min": min, "max": max}
    for p, rd, nd in [(4.0, 6.0, 12.0), (10.0, 10.0, 11.0), (6.0, 9.0, 8.0), (0.0, 5.0, 7.0)]:
        want = min(0.3 * p, max(0.0, nd - rd))
        assert abs(max(0.0, eval(expr, {"__builtins__": {}}, {**env, "pending": p, "ready": rd, "nodes": nd})) - want) < 1e-3
    created = _terms(got[(None, "pending")])
    assert all(abs(created.get(k, 0) - v) < 1e-3 for k, v in {"goal": 1, "pending": -1, "ready": -1}.items())


def test_collinear_columns_read_nothing():
    a = np.arange(1.0, 51.0)
    Z = np.vstack([a, 0.06 * a + 1e-9 * np.sin(a), np.ones(50)])
    assert not reread._posed(Z[:2].T)
    assert reread._posed(Z[[0, 2]].T)


def _pool_run(n=300):
    """(k8s-316) A connection pool: two services' queries wait (waiting, unit queries) and get connections at
    min(0.8 waiting, 80 - 0.2 active) (active, unit connections), released at 0.8 active; the cap binds in the
    peaks, where active sits at 80, so its slope in active shows only on the first step of each capped spell."""
    t = np.arange(n)
    a_in = np.round(300 + 250 * np.sin(2 * math.pi * t / 120), 4)
    b_in = np.round(250 + 200 * np.sin(2 * math.pi * (t + 30) / 120), 4)
    W, A = [10.0], [60.0]
    for i in range(n - 1):
        got = min(0.8 * W[i], 80 - 0.2 * A[i])
        W.append(W[i] + 0.06 * a_in[i] + 0.1 * b_in[i] - got)
        A.append(A[i] + got - 0.8 * A[i])
    levels = {"svc_a": list(a_in), "svc_b": list(b_in), "waiting": list(np.round(W, 4)), "active": list(np.round(A, 4))}
    return {"t": [float(x) for x in t], "levels": levels, "boundary_declared": True,
            "boundary": {"svc_a": {"in": ["estimate"], "out": ["estimate"]}, "svc_b": {"in": ["estimate"], "out": ["estimate"]},
                         "waiting": {"in": ["estimate", "estimate"]}, "active": {"out": ["estimate"]}}}


def test_a_pool_the_boundary_joins_across_units_is_a_min_move():
    stocks = [{"id": "svc_a", "unit": "requests"}, {"id": "svc_b", "unit": "requests"},
              {"id": "waiting", "unit": "queries"}, {"id": "active", "unit": "connections"}]
    run = _pool_run()
    W, A = np.array(run["levels"]["waiting"]), np.array(run["levels"]["active"])
    assert 0.2 < np.mean(0.8 * W > 80 - 0.2 * A) < 0.6                 # the cap binds on a good share of the steps
    wrong = [{"from": None, "to": "waiting", "rate": {"form": "proportional", "stock": "svc_b", "k": 0.2}},
             {"from": "active", "to": None, "rate": {"form": "proportional", "stock": "active", "k": 0.1}}]
    r = reread.apply({"flows": wrong}, stocks, run, {})
    assert r.get("reread"), r
    got = {}
    for f in r["flows"]:
        got.setdefault((f["from"], f["to"]), []).append(f)
    move = got[("waiting", "active")][0]["rate"]
    assert move["form"] == "expr" and "max" not in move["expr"]       # the cap's floor never binds: not written
    for w, a in [(10.0, 60.0), (120.0, 80.0), (90.0, 70.0), (50.0, 30.0)]:
        val = eval(move["expr"], {"__builtins__": {}}, {"min": min, "max": max, "waiting": w, "active": a})
        assert abs(val - min(0.8 * w, 80 - 0.2 * a)) < 1e-3
    ins = sorted((_terms(f) for f in got[(None, "waiting")]), key=lambda d: sorted(d))
    assert len(ins) == 2 and abs(ins[0]["svc_a"] - 0.06) < 1e-4 and abs(ins[1]["svc_b"] - 0.1) < 1e-4   # one flow a declared side
    assert abs(_terms(got[("active", None)][0])["active"] - 0.8) < 1e-4
