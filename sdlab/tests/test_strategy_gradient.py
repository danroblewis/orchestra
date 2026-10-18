"""Experiment gradient (sdlab/discovery/strategies/gradient.py): numbers fitted by gradient descent
through a differentiable simulator on multi-step error, on synthetic models where the answer is
known exactly. What the matrix method gets on each is stated beside it.

(a) a table effect of a third stock on a flow: the generous fit (an effect of every stock on every
    flow, group lasso; the matrix's links dropped; outside inflows learned from flat under a total
    variation price) recovers the curve. Matrix: no effect form; it reads the effect as links and
    as inflow pieces that follow the third stock's eras (skill@20 0.36).
(b) a hidden stock between two measured ones: routing the move through a hidden stock, its starting
    level fitted and its level stepped through the data, recovers both rates. Matrix: a direct move
    a -> b at 0.06 and a leak a -> outside at 0.157 (truth: 0.2 into the hidden stock, 0.1 out).
(c) a co-flow: the matrix's "c drains faster when a is high" link becomes a co-flow on the flow out
    of a, and its ratio is refitted. Matrix: the same loss as a link (0.229 x a, ratio 0.52), not a
    co-flow, so nothing stops when c runs out.
"""

from __future__ import annotations

import numpy as np
import pytest
from synth import generate, skill

pytest.importorskip("jax", reason="optional: uv sync --extra research")

from sdlab.discovery.diffsim import effect_table  # noqa: E402
from sdlab.discovery.gradfit import data_of  # noqa: E402
from sdlab.discovery.grad_hidden import fit_hidden  # noqa: E402
from sdlab.discovery.identify import identify as matrix  # noqa: E402
from sdlab.discovery.strategies.gradient import CLEAN  # noqa: E402
from sdlab.discovery.strategies.gradient import identify as gradient  # noqa: E402

TABLE = [[0, 0.2], [40, 0.35], [80, 0.8], [120, 1.0], [200, 1.0]]


def effect_model():
    stocks = [{"id": "a", "initial": 100}, {"id": "b", "initial": 50}, {"id": "c", "initial": 80, "unit": "tools"}]
    flows = [{"id": "in", "from": None, "to": "a", "rate": {"form": "constant", "value": 20}},
             {"id": "work", "from": "a", "to": "b", "rate": {"form": "proportional", "stock": "a", "k": 0.3},
              "effects": [{"stock": "c", "shape": "table", "points": TABLE}]},
             {"id": "out", "from": "b", "to": None, "rate": {"form": "proportional", "stock": "b", "k": 0.2}},
             {"id": "cin", "from": None, "to": "c", "rate": {"form": "constant", "value": 8}},
             {"id": "cout", "from": "c", "to": None, "rate": {"form": "proportional", "stock": "c", "k": 0.08}}]
    schedule = {"every": 200, "changes": [{"t": 1, "set": {"cin": {"form": "constant", "value": 8}}},
                                          {"t": 60, "set": {"cin": {"form": "constant", "value": 2}}},
                                          {"t": 120, "set": {"cin": {"form": "constant", "value": 12}}}]}
    return generate(stocks, flows, 2000, schedule=schedule)


def per_unit(flow: dict, x: np.ndarray, at: dict) -> np.ndarray:
    """A proportional flow's rate per unit of its source, as a function of stock c's level x (other
    effects read at the levels `at`)."""
    m = np.full(len(x), float(flow["rate"]["k"]))
    for e in flow.get("effects") or []:
        xp, fp = effect_table(e)
        m = m * np.maximum(0, np.interp(x if e["stock"] == "c" else np.full(len(x), at[e["stock"]]), xp, fp))
    return m


def test_a_table_effect_of_a_third_stock_is_recovered():
    d = effect_model()
    r = gradient(d["stocks"], d["run"], {"eras": d["eras"], "modes": ["refined", "generous-nolinks"], **CLEAN})
    assert r["chosen_gradient"] == "generous-nolinks"
    work = next(f for f in r["flows"] if f["from"] == "a" and f["to"] == "b")
    assert any(e["stock"] == "c" for e in work["effects"])
    c = np.asarray(d["run"]["levels"]["c"], float)
    x = np.linspace(*np.percentile(c, [5, 95]), 50)
    at = {s: float(np.mean(d["run"]["levels"][s])) for s in ("a", "b", "c")}
    truth = 0.3 * np.interp(x, [p[0] for p in TABLE], [p[1] for p in TABLE])
    error = np.sqrt(np.mean((per_unit(work, x, at) - truth) ** 2)) / truth.mean()
    assert error < 0.15                     # measured: 0.098 of the curve's mean over c's 5-95% range
    # no leak out of a is left (the matrix has a -> outside 0.084 standing in for the effect)
    assert not any(f["from"] == "a" and f["to"] is None for f in r["flows"])
    m = matrix(d["stocks"], d["run"], {"eras": d["eras"]})
    assert skill(m, d, 20) < 0.5 < 0.9 < skill(r, d, 20)        # matrix 0.36, gradient 0.97


def test_a_hidden_stock_between_two_measured_ones_is_recovered():
    stocks = [{"id": "a", "initial": 50}, {"id": "h", "initial": 60, "measured": False}, {"id": "b", "initial": 30}]
    flows = [{"id": "in", "from": None, "to": "a", "rate": {"form": "constant", "value": 10}},
             {"id": "go", "from": "a", "to": "h", "rate": {"form": "proportional", "stock": "a", "k": 0.2}},
             {"id": "arrive", "from": "h", "to": "b", "rate": {"form": "proportional", "stock": "h", "k": 0.1}},
             {"id": "out", "from": "b", "to": None, "rate": {"form": "proportional", "stock": "b", "k": 0.3}}]
    schedule = {"every": 120, "changes": [{"t": 1, "set": {"in": {"form": "constant", "value": 10}}},
                                          {"t": 40, "set": {"in": {"form": "constant", "value": 25}}},
                                          {"t": 70, "set": {"in": {"form": "constant", "value": 4}}}]}
    d = generate(stocks, flows, 2000, schedule=schedule)
    m = matrix(d["stocks"], d["run"], {"eras": d["eras"]})
    ids = [s["id"] for s in d["stocks"]]
    h = fit_hidden(m["flows"], ids, d["run"]["t"], data_of(d["run"]["levels"], ids))
    assert h["hidden"], "a hidden stock pays for itself"
    hid = h["hidden"][0]["id"]
    into = next(f for f in h["flows"] if f["from"] == "a" and f["to"] == hid)["rate"]["k"]
    out = next(f for f in h["flows"] if f["from"] == hid and f["to"] == "b")["rate"]["k"]
    assert abs(into - 0.2) < 0.02 and abs(out - 0.1) < 0.01          # measured: 0.196 and 0.104
    leak = sum(f["rate"]["k"] for f in h["flows"] if f["from"] == "a" and f["to"] is None)
    assert leak < 0.05                                               # matrix: 0.157 (truth 0)
    assert abs(next(f for f in h["flows"] if f["from"] == "b")["rate"]["k"] - 0.3) < 0.02   # matrix: 0.093


def test_a_co_flow_ratio_is_recovered():
    stocks = [{"id": "a", "initial": 50}, {"id": "b", "initial": 30}, {"id": "c", "initial": 200, "unit": "kg"}]
    flows = [{"id": "in", "from": None, "to": "a", "rate": {"form": "constant", "value": 20}},
             {"id": "work", "from": "a", "to": "b", "rate": {"form": "proportional", "stock": "a", "k": 0.4}, "uses": [{"stock": "c", "per": 0.5}]},
             {"id": "out", "from": "b", "to": None, "rate": {"form": "proportional", "stock": "b", "k": 0.25}},
             {"id": "restock", "from": None, "to": "c", "rate": {"form": "gap", "stock": "c", "goal": 300, "time": 10}}]
    schedule = {"every": 200, "changes": [{"t": 1, "set": {"in": {"form": "constant", "value": 20}}},
                                          {"t": 70, "set": {"in": {"form": "constant", "value": 32}}},
                                          {"t": 120, "set": {"in": {"form": "constant", "value": 10}}}]}
    d = generate(stocks, flows, 2000, schedule=schedule)
    r = gradient(d["stocks"], d["run"], {"eras": d["eras"], **CLEAN, "modes": ["generous-nolinks"]})
    work = next(f for f in r["flows"] if f["from"] == "a" and f["to"] == "b")
    per = next(u["per"] for u in work.get("uses") or [] if u["stock"] == "c")
    assert abs(per - 0.5) < 0.075                                    # measured: about 0.53
    assert not any(f.get("driver") for f in r["flows"])              # the link is gone: it is a co-flow now
