"""combined2's capacity limits on a pool's room and announced injections (capmin.py, minrefit.py, hinge.py),
docs/research/fixes/311-combined2.md."""

import numpy as np

from sdlab.discovery.strategies.combined2 import capmin, hinge, minrefit


def _setup(n=400):
    """Jobs arrive (an input) into `waiting`, start into `running` at min(0.5 waiting, max(0, 4 hosts - running))
    (4 slots a host), and `running` finishes to outside at 0.1. A host fails at t=150 (its 3 jobs back to
    waiting) and returns at t=180: announced injections, added before their step's flows."""
    t = np.arange(n + 1, dtype=float)
    arrive = 0.8 + 0.6 * np.sin(2 * np.pi * t / 80)
    inj = [{"t": 150.0, "stock": "hosts", "amount": -1.0}, {"t": 150.0, "stock": "running", "amount": -3.0},
           {"t": 150.0, "stock": "waiting", "amount": 3.0}, {"t": 180.0, "stock": "hosts", "amount": 1.0}]
    w, r, h = np.zeros(n + 1), np.zeros(n + 1), np.zeros(n + 1)
    w[0], r[0], h[0] = 2.0, 6.0, 3.0
    for i in range(n):
        lw, lr, lh = w[i], r[i], h[i]
        for j in inj:
            if j["t"] == t[i + 1]:
                if j["stock"] == "hosts":
                    lh += j["amount"]
                elif j["stock"] == "running":
                    lr += j["amount"]
                else:
                    lw += j["amount"]
        start = max(0.0, min(0.5 * lw, max(0.0, 4 * lh - lr)))
        w[i + 1] = lw + arrive[i + 1] - start
        r[i + 1] = lr + start - 0.1 * lr
        h[i + 1] = lh
    lv = {"waiting": list(w), "running": list(r), "hosts": list(h)}
    run = {"t": list(t), "levels": lv, "boundary_declared": True,
           "boundary": {"waiting": {"in": ["input"]}, "running": {"out": ["estimate"]}}}
    stocks = [{"id": "waiting", "unit": "jobs"}, {"id": "running", "unit": "jobs"}, {"id": "hosts", "unit": "hosts"}]
    return stocks, run, {"inputs": {"arrive": list(arrive)}, "injections": inj}


def _true(start="min(0.5 * waiting, max(0, 4.0 * hosts + -1.0 * running))"):
    return [{"from": None, "to": "waiting", "ratio": 1, "input": "arrive", "rate": {"form": "proportional", "stock": "arrive", "k": 1.0}},
            {"id": "start", "from": "waiting", "to": "running", "ratio": 1, "rate": {"form": "expr", "expr": start}},
            {"from": "running", "to": None, "ratio": 1, "rate": {"form": "proportional", "stock": "running", "k": 0.1}}]


def test_rows_take_the_injections_off():
    stocks, run, opts = _setup()
    levels, cols, n = hinge.columns(run, opts)
    for x in ("waiting", "running", "hosts"):
        r, sides = hinge.row_error(x, _true(), levels, cols, n)
        assert np.max(np.abs(r - sides["in"] + sides["out"])) < 1e-9, x


def test_expressions_are_evaluated_but_not_switches():
    cols = {"a": np.array([1.0, 5.0]), "b": np.array([2.0, 1.0])}
    assert np.allclose(hinge.expr_amount("min(2 * a, max(0, 3.0 * b + -1 * a))", cols, 2), [2.0, 0.0])
    assert hinge.expr_amount("1.0 * ((a - b) > 0)", cols, 2) is None
    assert hinge.expr_amount("min(a, c)", cols, 2) is None


def test_a_limit_on_the_room_left_is_offered():
    stocks, run, opts = _setup()
    _, cap = capmin.offer(stocks, run, opts)
    caps = [cap] + list(cap.get("more") or [])
    room = [c for c in caps if c.get("room")]
    assert room, caps
    c = room[0]
    assert (c["source"], c["cap"], c["room"], c.get("to")) == ("waiting", "hosts", "running", "running")
    assert abs(c["beta"] - 4.0) < 0.2


def test_the_limit_numbers_are_refitted_on_its_rows():
    stocks, run, opts = _setup()
    rough = _true("min(0.61 * waiting, max(0, 3.83 * hosts + -0.96 * running))")
    out = minrefit.apply({"flows": rough}, stocks, run, opts)
    p = minrefit.parse(next(f for f in out["flows"] if f.get("id") == "start")["rate"]["expr"])
    assert abs(p["k"] - 0.5) < 1e-6 and abs(p["cap"][0][0] - 4.0) < 1e-6 and abs(p["cap"][1][0] + 1.0) < 1e-6, p
    drain = next(f for f in out["flows"] if f["from"] == "running" and f["to"] is None)
    assert abs(hinge._linear(drain["rate"])[1]["running"] - 0.1) < 1e-6


def test_an_offered_limit_is_read_only_by_the_flow_it_limits():
    cap = {"name": "capmin__waiting__hosts__running", "source": "waiting", "to": "running", "cap": "hosts", "room": "running",
           "beta": 4.0, "theta": 1.0, "k": 0.5}
    flows = [{"from": "running", "to": None, "ratio": 1, "rate": {"form": "linear", "c": 0.0, "terms": [
                 {"stock": "running", "k": 0.1}, {"stock": cap["name"], "k": -0.4}]}},
             {"from": None, "to": "total", "ratio": 1, "rate": {"form": "proportional", "stock": cap["name"], "k": 0.2}}]
    out = capmin.place({"flows": flows}, cap)
    got = {(f["from"], f["to"]): f["rate"] for f in out["flows"]}
    assert got[("running", None)] == {"form": "linear", "c": 0.0, "terms": [{"stock": "running", "k": 0.1}]}
    assert (None, "total") not in got
    assert got[("waiting", "running")]["terms"] == [{"stock": cap["name"], "k": 0.5}]
