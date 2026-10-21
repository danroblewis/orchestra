"""kalman_lna's derived.py with rows.py (docs/research/fixes/310-kalman_lna.md): a switch column X max(0, Y - theta)
moving pods between two stocks and counted, a per-unit rate X / max(1, Y), and a hidden integrator behind a row."""

from __future__ import annotations

import numpy as np

from sdlab.discovery.strategies.kalman_lna import derived, rows


def _sim(T=300):
    """ready loses 0.01 ready max(0, mem - 300) to pending (counted in kills); pending gets 2 a step and moves 0.5 of
    itself to ready; ready drains 0.1; load follows traffic; mem gets 20 + 0.5 h + load / max(1, ready) and drains
    0.5; h (hidden) gets 1 a step and loses 0.02 h max(0, mem - 300)."""
    t = np.arange(T + 1)
    traffic = 100 + 60 * np.sin(2 * np.pi * t / 47)
    R, P, K, M, Ld, H = [10.0], [2.0], [0.0], [200.0], [100.0], [0.0]
    for k in range(T):
        kill = 0.01 * R[-1] * max(0.0, M[-1] - 300)
        reset = 0.02 * H[-1] * max(0.0, M[-1] - 300)
        R.append(R[-1] + 0.5 * P[-1] - 0.1 * R[-1] - kill)
        P.append(P[-1] + 2.0 - 0.5 * P[-1] + kill)
        K.append(K[-1] + kill)
        M.append(M[-1] + 20 + 0.5 * H[-1] + Ld[-1] / max(1.0, R[-2]) - 0.5 * M[-1])
        Ld.append(Ld[-1] + traffic[k + 1] - 0.5 * Ld[-1])
        H.append(H[-1] + 1 - reset)
    lv = {"ready": R, "pending": P, "kills": K, "mem": M, "load": Ld}
    lv = {k: [round(x, 7) for x in v] for k, v in lv.items()}
    stocks = [{"id": "ready", "unit": "pods"}, {"id": "pending", "unit": "pods"}, {"id": "kills", "unit": "pods", "final": True},
              {"id": "mem", "unit": "MiB"}, {"id": "load", "unit": "requests"}]
    run = {"t": list(t), "levels": lv, "boundary_declared": True,
           "boundary": {"ready": {"in": [], "out": ["estimate"]}, "pending": {"in": ["estimate"], "out": []},
                        "kills": {"in": ["estimate"], "out": []}, "mem": {"in": ["estimate"], "out": ["estimate"]},
                        "load": {"in": ["input"], "out": ["estimate"]}}}
    return stocks, run, {"inputs": {"traffic": list(traffic)}}


def test_integrator_columns():
    h0, h1 = derived.integrator(0.0, np.ones(5))
    assert list(h1) == [0, 1, 2, 3, 4] and list(h0) == [1] * 5


def test_rows_find_the_switch_move_the_ratio_and_the_hidden_drive():
    stocks, run, opts = _sim()
    M = np.array(run["levels"]["mem"])
    assert M.max() > 300                                     # the switch acts
    proxy = [{"from": None, "to": "pending", "ratio": 1, "rate": {"form": "constant", "value": 2.0}},
             {"from": "pending", "to": "ready", "ratio": 1, "rate": {"form": "proportional", "stock": "pending", "k": 0.5}},
             {"from": "ready", "to": None, "ratio": 1, "rate": {"form": "proportional", "stock": "ready", "k": 0.1}},
             {"from": None, "to": "kills", "ratio": 1, "rate": {"form": "constant", "value": 0.05}},
             {"from": None, "to": "mem", "ratio": 1, "rate": {"form": "constant", "value": 150.0}},
             {"from": "mem", "to": None, "ratio": 1, "rate": {"form": "proportional", "stock": "mem", "k": 0.5}},
             {"from": None, "to": "load", "ratio": 1, "rate": {"form": "proportional", "stock": "traffic", "k": 1.0}},
             {"from": "load", "to": None, "ratio": 1, "rate": {"form": "proportional", "stock": "load", "k": 0.5}}]
    r = rows.revise({"flows": proxy}, stocks, run, opts)
    got = {(f["from"], f["to"]): f for f in r["flows"]}
    kill = got[("ready", "pending")]
    assert kill["rate"]["stock"] == "ready" and abs(kill["rate"]["k"] - 0.01) < 1e-4
    assert kill["effects"][0]["stock"] == "mem" and abs(kill["effects"][0]["points"][0][0] - 300) < 0.05
    assert got[(None, "kills")]["effects"][0]["stock"] == "mem"          # the counter reads the same switch
    inflow = got[(None, "mem")]
    assert "load / max(1, ready)" in inflow["rate"]["expr"] and inflow.get("byTime")
    assert abs(got[("mem", None)]["rate"]["k"] - 0.5) < 0.01
