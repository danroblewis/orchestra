"""Inflow attribution (docs/research/inflow-attribution.md): a bakery-like model where orders arrive from
outside at a changing rate and are baked at 0.5 x orders while flour lasts. When flour runs out the
orders pile up, and over the whole run the orders' row looks like a random walk: the main line gives
it no inflow and a drain near 0 (fed the true arrivals, its orders grow without limit). Counting noise
flags the row (its residuals vary ~100x more than its terms can explain), the drain measured within
stretches is ~0.5, and the inflow recovered with it held is the arrivals."""

from __future__ import annotations

import numpy as np
import pytest
from synth import generate, skill

from sdlab.discovery.attribution import Data, diagnose, refit
from sdlab.discovery.counting import ratio
from sdlab.discovery.identify import identify as main_line
from sdlab.discovery.stretches import stretch_fit
from sdlab.discovery.strategies import load

STOCKS = [
    {"id": "orders", "initial": 80, "unit": "loaves"},
    {"id": "shelf", "initial": 100, "unit": "loaves"},
    {"id": "flour", "initial": 400, "unit": "kg"},
]
FLOWS = [
    {"id": "order", "from": None, "to": "orders", "rate": {"form": "constant", "value": 40}},
    {"id": "bake", "from": "orders", "to": "shelf", "rate": {"form": "proportional", "stock": "orders", "k": 0.5},
     "uses": [{"stock": "flour", "per": 0.5}]},
    {"id": "pickup", "from": "shelf", "to": None, "rate": {"form": "proportional", "stock": "shelf", "k": 0.25}},
    {"id": "restock", "from": None, "to": "flour", "rate": {"form": "gap", "stock": "flour", "goal": 600, "time": 10}},
]
SCHEDULE = {"every": 250, "changes": [
    {"t": 1, "set": {"order": {"form": "constant", "value": 40}, "restock": {"form": "gap", "stock": "flour", "goal": 600, "time": 10}}},
    {"t": 61, "set": {"restock": {"form": "gap", "stock": "flour", "goal": 600, "time": 60}}},
    {"t": 121, "set": {"restock": {"form": "gap", "stock": "flour", "goal": 600, "time": 10}}},
    {"t": 151, "set": {"order": {"form": "constant", "value": 55}}},
    {"t": 201, "set": {"order": {"form": "constant", "value": 30}}},
]}


@pytest.fixture(scope="module")
def bakery():
    return generate(STOCKS, FLOWS, steps=1000, schedule=SCHEDULE, seed=2)


def orders_row(r):
    return next(x for x in r["matrix"] if x["id"] == "orders")


def mean_inflow(row):
    pcs = row["inflow"]
    if not pcs:
        return 0.0
    return sum(p["value"] * (p["to"] - p["from"] + 1) for p in pcs) / sum(p["to"] - p["from"] + 1 for p in pcs)


def test_main_line_drops_the_inflow_and_collapses_the_drain(bakery):
    r = main_line(bakery["stocks"], bakery["run"], {})
    row = orders_row(r)
    assert -row["coef"].get("orders", 0.0) < 0.1          # truth 0.5
    assert mean_inflow(row) < 15                            # truth ~42 on average
    assert skill(r, bakery) < 0


def test_counting_noise_flags_the_row(bakery):
    r = main_line(bakery["stocks"], bakery["run"], {})
    d = Data(bakery["stocks"], bakery["run"], {})
    s = d.ids.index("orders")
    assert diagnose(s, orders_row(r), d, {})["z"] > 20     # residuals vary far more than the row can explain
    # control: a row with the true numbers accounts for the throughput (ratio near 1)
    y, x = d.dy[s], d.prev[s]
    clean = d.levels[2, :-1] > 100                        # flour on hand: the true row holds
    res = (y - (42 - 0.5 * x))[clean]
    assert 0.5 < ratio(res, (42 + 0.5 * x)[clean]) < 2


def test_stretches_recover_the_drain_and_the_inflow(bakery):
    d = Data(bakery["stocks"], bakery["run"], {})
    s = d.ids.index("orders")
    fit = stretch_fit(d.dy[s], d.prev[s][None, :], own=0)
    assert fit["beta"][0] == pytest.approx(-0.5, abs=0.08)
    # without the short-stretch bias correction the drain is found too fast
    assert stretch_fit(d.dy[s], d.prev[s][None, :])["beta"][0] < fit["beta"][0] - 0.05
    # a pooled fit over the whole run, for contrast, collapses
    A = np.c_[np.ones(d.T), d.prev[s]]
    assert np.linalg.lstsq(A, d.dy[s], rcond=None)[0][1] > -0.1
    row = refit(s, orders_row(main_line(bakery["stocks"], bakery["run"], {})), d, {})
    assert -row["coef"]["orders"] == pytest.approx(0.5, abs=0.08)
    assert mean_inflow(row) > 30                           # the arrivals recovered with the drain held


def test_strategy_recovers_behaviour(bakery):
    r = load("inflow_attribution")(bakery["stocks"], bakery["run"], {})
    row = orders_row(r)
    assert -row["coef"]["orders"] == pytest.approx(0.5, abs=0.08)
    assert mean_inflow(row) > 30
    assert skill(r, bakery) > 0.3
    assert skill(r, bakery) > skill(main_line(bakery["stocks"], bakery["run"], {}), bakery) + 1


def test_pieces_gate_keeps_the_changing_inflow(bakery):
    """The matrix's last form choice: the orders' pieces beat 'none' by far in BIC but are vetoed
    because a few short pile-up pieces make their values spread; tested against the mean's own
    standard error (opts["pieces_gate"] = "noise") they stay. The drain stays biased (pieces of 5+
    steps): that is the attribution strategy's job."""
    row = orders_row(main_line(bakery["stocks"], bakery["run"], {}))
    gated = orders_row(load("pieces_gate")(bakery["stocks"], bakery["run"], {}))
    assert not row["inflow"] and gated["inflow"]
    assert mean_inflow(gated) > 0 and -gated["coef"]["orders"] < 0.2


def test_a_right_row_is_left_alone():
    d0 = generate([{"id": "q", "initial": 50}], [
        {"id": "in", "from": None, "to": "q", "rate": {"form": "constant", "value": 20}},
        {"id": "out", "from": "q", "to": None, "rate": {"form": "proportional", "stock": "q", "k": 0.4}},
    ], steps=600, seed=5)
    r = load("inflow_attribution")(d0["stocks"], d0["run"], {})
    base = main_line(d0["stocks"], d0["run"], {})
    assert not r["chosen"].endswith("inflows attributed")
    assert r["chosen"] == base["chosen"] and r["matrix"][0]["coef"] == base["matrix"][0]["coef"]
