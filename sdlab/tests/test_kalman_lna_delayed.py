"""kalman_lna's delayed inflow (docs/research/fixes/312-kalman_lna.md): a stock fed from outside through a hidden
first-order delay whose order is floored, H' = max(0, C . x) - a H, the stock gaining a H a step, beside a floored
outflow (delayed.py, rows.py `_with_delay`). A synthetic case with its own numbers (not the ladder's): machines are
ordered while the backlog per machine is above 8, arrive after a 4-step delay, and are retired while above a third
of the backlog; levels are reported to 4 decimals, and two announced injections take a machine away for a while."""

from __future__ import annotations

import math

import numpy as np

from sdlab.discovery.strategies.kalman_lna import capsteps, delayed, rows


def _sim(T=360):
    t = np.arange(T + 1)
    demand = 30.0 + 18.0 * np.sin(2 * np.pi * t / 97) + 8.0 * np.sin(2 * np.pi * t / 23)
    Bk, M, H = [20.0], [6.0], 0.0
    inj = []
    for k in range(T):
        b, m = Bk[-1], M[-1]
        order = 0.1 * max(0.0, b - 8.0 * m)
        retire = 0.04 * max(0.0, m - b / 3.0)
        served = min(0.5 * b, 4.0 * m)
        Bk.append(b + demand[k + 1] - served)
        M.append(m + 0.25 * H - retire)
        H = H + order - 0.25 * H
        if k + 1 in (120, 260):
            M[-1] -= 1.0
            inj.append({"t": float(k + 1), "stock": "machines", "amount": -1.0})
    lv = {"backlog": [round(x, 4) for x in Bk], "machines": [round(x, 4) for x in M]}
    stocks = [{"id": "backlog", "unit": "jobs"}, {"id": "machines", "unit": "machines"}]
    run = {"t": list(t), "levels": lv, "boundary_declared": True,
           "boundary": {"backlog": {"in": ["input"], "out": ["estimate"]}, "machines": {"in": ["estimate"], "out": ["estimate"]}}}
    return stocks, run, {"injections": inj, "inputs": {"demand": list(demand)}}


def _row(stocks, run, opts, S):
    ids, dy, read, inputs, states, t_end = rows._data(stocks, run, opts)
    T = dy.shape[1]
    names = list(ids) + list(inputs) + [None]
    X = np.vstack([read[i] for i in range(len(ids))] + [inputs[k] for k in inputs] + [np.ones(T)]).T
    y = dy[ids.index(S)]
    return X, y, names, rows.RESOLUTION * float(np.mean(y ** 2)) * T + 1e-300


def test_the_delay_and_the_order_are_read_off_the_row():
    stocks, run, opts = _sim()
    X, y, names, floor = _row(stocks, run, opts, "machines")
    b_cols = list(range(len(names)))

    def floored(z, a_cols, keep=None):
        keep = np.ones(len(z), dtype=bool) if keep is None else keep
        h = rows._floored(X[keep], z[keep], -1.0, floor, math.inf, a_cols, b_cols, (1.0, 4.0))
        return None if h is None else (h[1], h[2], h[3], h[4])

    got = delayed.fit(X, y, floor, math.inf, b_cols, b_cols, floored)
    assert got is not None and abs(got["a"] - 0.25) < 0.005
    order = dict(zip([names[j] for j in got["C"]], got["c"]))
    assert set(order) == {"backlog", "machines"}
    assert abs(order["backlog"] - 0.1) < 0.002 and abs(order["machines"] + 0.8) < 0.016
    out = dict(zip([names[j] for j in got["B"]], got["b"]))
    assert set(out) == {"backlog", "machines"} and abs(out["machines"] - 0.04) < 0.001


def test_rows_write_the_delay_as_a_hidden_stock():
    stocks, run, opts = _sim()
    proxy = [{"from": None, "to": "backlog", "ratio": 1, "rate": {"form": "proportional", "stock": "demand", "k": 1.0}},
             {"from": "backlog", "to": None, "ratio": 1, "rate": {"form": "proportional", "stock": "backlog", "k": 0.45}},
             {"from": None, "to": "machines", "ratio": 1, "rate": {"form": "proportional", "stock": "backlog", "k": 0.01}},
             {"from": "machines", "to": None, "ratio": 1, "rate": {"form": "proportional", "stock": "machines", "k": 0.05}}]
    r = rows.revise({"flows": proxy}, stocks, run, opts)
    got = {(f["from"], f["to"]): f for f in r["flows"]}
    assert ("machines_hidden", "machines") in got and (None, "machines_hidden") in got
    assert abs(got[("machines_hidden", "machines")]["rate"]["k"] - 0.25) < 0.005
    assert got[(None, "machines_hidden")]["rate"]["expr"].startswith("max(0, ")
    assert (None, "machines") not in got                                     # one flow on the side: the delayed one
    assert got[(None, "backlog")]["rate"] == {"form": "proportional", "stock": "demand", "k": 1.0}   # the input stays 1 x
    assert len(r["inferred_levels"]["machines_hidden"]) == len(run["t"])


def test_a_side_declared_input_takes_no_rebuilt_flow():
    assert rows._sides("q", True, {"q": {"in": ["input"], "out": ["estimate"]}}) == {"out"}
    assert rows._sides("q", True, {"q": {"in": ["estimate"], "out": []}}) == {"in"}
    f = {"from": None, "to": "q", "rate": {"form": "proportional", "stock": "traffic", "k": 1.0}}
    assert rows._fixed_input(f, True, {"q": {"in": ["input"]}}, ["traffic"])
    assert not rows._fixed_input(f, True, {"q": {"in": ["estimate"]}}, ["traffic"])


def test_capsteps_offers_a_limit_that_binds_on_few_steps():
    T = 300
    t = np.arange(T + 1)
    traffic = 100.0 + 20.0 * np.sin(2 * np.pi * t / 50) + 110.0 * (np.abs(t - 150) < 2)     # a burst: a few steps limited
    S = [4.0 + 0.5 * math.sin(k / 9.0) for k in range(T + 1)]                   # the capacity moves, without feedback
    Q, W = [50.0], [10.0]
    for k in range(T):
        go = min(0.6 * Q[-1], 40.0 * S[k])
        Q.append(Q[-1] + traffic[k + 1] - go)
        W.append(W[-1] + go - 0.5 * W[-1])
    lim = sum(0.6 * Q[k] > 40.0 * S[k] for k in range(T))
    assert 5 <= lim < 0.05 * T
    stocks = [{"id": "queue", "unit": "r"}, {"id": "work", "unit": "r"}, {"id": "servers", "unit": "s"}]
    run = {"t": list(t), "levels": {"queue": Q, "work": W, "servers": S}}
    o, cap = capsteps.offer(stocks, run, {"inputs": {"traffic": list(traffic)}})
    assert cap and (cap["source"], cap["cap"]) == ("queue", "servers") and abs(cap["theta"] - 40.0 / 0.6) < 0.5
