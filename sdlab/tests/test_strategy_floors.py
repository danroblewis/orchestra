"""The floors strategy's mechanisms on the smallest models where they matter (docs/DISCOVERY-EXPERIMENTS.md).

1. A floor: a -> b runs at max(0, -30 + 0.2 a), shut half the time (a swings between ~70 and ~230
   as its outside inflow changes, unannounced, between 4 and 20 a step). The matrix method draws a
   straight line through the kink: a -> b = 0.140 a, b's row takes 73 outside inflow pieces to copy
   what the line misses, and its model, fed the true inflow, scores skill@20 -5%. A hinge column
   max(0, a - theta), its threshold chosen from the data, recovers the flow in its own form.
2. A cap: s sells 15 a step but often holds less (it is emptied on about a third of the steps), so
   the engine sells what it has. The matrix method reads the sale as 0.0165 s plus 9.5 a step
   (skill@20 70%). Adding back what the emptied steps hid (EM for censored data) and fitting again
   moves it toward 15 (skill@20 89%); a hinge on s writes the cap itself, min(k s, 15), in floored
   forms the model can step (skill@20 98%).
"""

from __future__ import annotations

import numpy as np
from synth import generate, skill

from sdlab.discovery.simulate import Model
from sdlab.discovery.strategies import load

floors, matrix = load("floors"), load("matrix")
BY_BIC = {"hinges": True, "select": "bic"}      # the floors chosen by the rows' BIC (see the experiment log)


def floor_model():
    sched = {"every": 200, "changes": [{"t": 1, "set": {"in": {"form": "constant", "value": 4}}},
                                       {"t": 101, "set": {"in": {"form": "constant", "value": 20}}}]}
    return generate(stocks=[{"id": "a", "initial": 100}, {"id": "b", "initial": 50}],
                    flows=[{"id": "in", "to": "a", "rate": {"form": "constant", "value": 4}},
                           {"id": "move", "from": "a", "to": "b", "rate": {"form": "linear", "c": -30, "terms": [{"stock": "a", "k": 0.2}]}},
                           {"id": "leak", "from": "a", "rate": {"form": "proportional", "stock": "a", "k": 0.05}},
                           {"id": "out", "from": "b", "rate": {"form": "proportional", "stock": "b", "k": 0.1}}],
                    steps=2000, schedule=sched)


def cap_model():
    sched = {"every": 200, "changes": [{"t": 1, "set": {"order": {"form": "constant", "value": 10}}},
                                       {"t": 141, "set": {"order": {"form": "constant", "value": 20}}}]}
    return generate(stocks=[{"id": "p", "initial": 60}, {"id": "s", "initial": 50}],
                    flows=[{"id": "order", "to": "p", "rate": {"form": "constant", "value": 10}},
                           {"id": "deliver", "from": "p", "to": "s", "rate": {"form": "proportional", "stock": "p", "k": 0.25}},
                           {"id": "sell", "from": "s", "rate": {"form": "constant", "value": 15}}],
                    steps=2000, schedule=sched)


def test_a_floored_move_is_recovered_in_its_own_form():
    d = floor_model()
    a = np.array(d["run"]["levels"]["a"][:-1], dtype=float)
    assert 0.3 < ((0.2 * a - 30) < 0).mean() < 0.7, "the floor binds a good share of the time"

    base = matrix(d["stocks"], d["run"], {})
    move = next(f for f in base["flows"] if f["from"] == "a" and f["to"] == "b")
    assert move["rate"]["form"] == "proportional" and abs(move["rate"]["k"] - 0.14) < 0.01   # a straight line through the kink
    assert skill(base, d) < 0.1

    r = floors(d["stocks"], d["run"], dict(BY_BIC))
    assert any(h["base"] == "a" and abs(h["theta"] - 150) <= 5 for h in r["hinges"]), r["hinges"]
    move = next(f for f in r["flows"] if f["from"] == "a" and f["to"] == "b" and f.get("floor"))
    c, (term,) = move["rate"]["c"], move["rate"]["terms"]
    assert term["stock"] == "a" and abs(term["k"] - 0.2) <= 0.015, move["rate"]              # truth 0.2 (found 0.190)
    assert abs(c + 30) <= 3, move["rate"]                                                   # truth -30 (found -28.4)
    assert abs(-c / term["k"] - 150) <= 5                                                   # the threshold, truth 150
    assert not any(f.get("inflow") and f["to"] == "b" for f in r["flows"]), "b needs no outside inflow pieces"
    assert skill(r, d) > 0.9 and skill(r, d, 100) > 0.95                                    # matrix: -5% and 80%


def sold(r: dict, levels: list[float]) -> np.ndarray:
    """What the found model takes out of s in one step from each level (nothing in p, so nothing
    arrives)."""
    L = np.array([[0.0] * len(levels), levels])
    after = Model(r["flows"], ["p", "s"]).step(L, np.full(len(levels), 50.0))
    return L[1] - after[1]


def test_an_emptied_stock_cap_is_undone():
    d = cap_model()
    s = np.array(d["run"]["levels"]["s"][:-1], dtype=float)
    assert 0.25 < (s < 15).mean() < 0.5, "s is emptied on a good share of the steps"

    base = matrix(d["stocks"], d["run"], {})
    assert 0.6 < skill(base, d) < 0.8
    drift = next(f for f in base["flows"] if f["from"] == "s" and f["rate"]["form"] == "proportional")
    assert drift["rate"]["k"] > 0.015                                                        # a sale that grows with s

    em = floors(d["stocks"], d["run"], {})                                                   # the default: caps by EM
    assert "outflows uncut" in em["chosen"]
    assert skill(em, d) > skill(base, d) + 0.1                                              # 70% -> 89%
    k = sum(f["rate"]["k"] for f in em["flows"] if f["from"] == "s" and f["rate"]["form"] == "proportional")
    assert k < 0.6 * drift["rate"]["k"]                                                     # 0.0165 -> 0.0098

    hinged = floors(d["stocks"], d["run"], dict(BY_BIC))
    assert any(h["base"] == "s" for h in hinged["hinges"])
    assert skill(hinged, d) > 0.95 and skill(hinged, d, 100) > 0.95
    out = sold(hinged, [5.0, 100.0, 300.0])
    assert out[0] <= 5.5 and abs(out[1] - 15) <= 2 and abs(out[2] - 15) <= 2.5, out        # min(what it holds, 15)
