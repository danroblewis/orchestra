"""kalman_lna's capped move (docs/research/fixes/311-kalman_lna.md): a move X -> T limited by the room other levels
leave, min(a X, max(0, B . z)), read off the rows (derived.py 4, rows.py `_capped`). A synthetic case with its own
numbers (not the ladder's): jobs arrive in batches and queue for slots on racks, 3 a rack; racks fail and come back by
announced injections. The cap is first read off what the receiver gains or the source loses, whichever is more, so
it needs steps where one of the two rows carries nothing else (here: between batches; on the ladder: the HPA moves
only now and then)."""

from __future__ import annotations

import numpy as np

from sdlab.discovery.strategies.kalman_lna import derived, rows


def _sim(T=400):
    t = np.arange(T + 1)
    arrivals = (t % 4 == 0) * (6.0 + 4.8 * np.sin(2 * np.pi * t / 61))       # batches: waiting's row is clean between
    W, R, K = [0.0], [6.0], [5.0]
    quota = 14.0 - 6.0 * (np.sin(2 * np.pi * t / 53) > 0.6)                  # running jobs above it are stopped
    inj = []
    for k in range(T):
        start = min(0.35 * W[-1], max(0.0, 3.0 * K[-1] - R[-1]))
        W.append(W[-1] + arrivals[k + 1] - start)
        R.append(R[-1] + start - max(0.0, R[-1] - quota[k + 1]))
        K.append(K[-1])
        if k + 1 in (90, 250):
            K[-1] -= 1.0
            inj.append({"t": float(k + 1), "stock": "racks", "amount": -1.0})
        if k + 1 in (130, 290):
            K[-1] += 1.0
            inj.append({"t": float(k + 1), "stock": "racks", "amount": 1.0})
    lv = {"waiting": W, "running": R, "racks": K}
    lv = {k: [round(x, 7) for x in v] for k, v in lv.items()}
    stocks = [{"id": "waiting", "unit": "jobs"}, {"id": "running", "unit": "jobs"}, {"id": "racks", "unit": "racks"}]
    run = {"t": list(t), "levels": lv, "boundary_declared": True,
           "boundary": {"waiting": {"in": ["estimate"], "out": []}, "running": {"in": [], "out": ["estimate"]}}}
    return stocks, run, {"injections": inj, "inputs": {"arrivals": list(arrivals), "quota": list(quota)}}


def test_capfit_reads_the_two_regimes():
    rng = np.random.default_rng(3)
    x = rng.uniform(0, 20, 300)
    z = rng.uniform(0, 4, 300)
    f = np.minimum(0.4 * x, np.maximum(0.0, 2.0 * z))
    Z = z[:, None]
    sse, a, b = derived.capfit(f, x, Z, lower=True)
    assert abs(a - 0.4) < 1e-6 and abs(b[0] - 2.0) < 1e-6 and sse < 1e-12


def test_rows_find_the_capped_move():
    stocks, run, opts = _sim()
    W, R, K = (np.array(run["levels"][k]) for k in ("waiting", "running", "racks"))
    room = 3 * K[:-1] - R[:-1]
    assert np.sum(room < 0.35 * W[:-1]) > 20 and np.sum(room >= 0.35 * W[:-1]) > 20    # both regimes act
    proxy = [{"from": None, "to": "waiting", "ratio": 1, "rate": {"form": "proportional", "stock": "arrivals", "k": 1.0}},
             {"from": "waiting", "to": "running", "ratio": 1, "rate": {"form": "proportional", "stock": "waiting", "k": 0.2}},
             {"from": "running", "to": None, "ratio": 1, "rate": {"form": "proportional", "stock": "running", "k": 0.1}}]
    r = rows.revise({"flows": proxy}, stocks, run, opts)
    got = {(f["from"], f["to"]): f for f in r["flows"]}
    move = got[("waiting", "running")]
    e = move["rate"]["expr"]
    assert e.startswith("min(") and "racks" in e and "running" in e
    states = [{"waiting": w, "running": x, "racks": k} for w, x, k in zip(W[:-1], R[:-1], K[:-1])]
    amt = np.array([eval(e, {"min": min, "max": max}, s) for s in states])
    true = np.minimum(0.35 * W[:-1], np.maximum(0.0, room))
    assert np.max(np.abs(amt - true)) < 0.02 * np.max(true)                 # within 2% of the move at its largest
