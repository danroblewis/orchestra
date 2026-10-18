"""Experiment starved-coflows (docs/research/starved-coflows.md): a co-flow found where the used stock
runs dry.

Orders arrive at 40 an hour and are baked onto the shelf at 0.5 x orders, each loaf using 0.5 kg of
flour; the shelf empties at 0.25. Flour is restocked toward 600 kg over 10 hours, but for 60 hours of
every 250 (unannounced) the supplier is six times slower and the flour runs dry: baking is cut to
what the flour allows and the orders pile up. The main line fits the orders' row through both
regimes, so its drain is a fraction of the truth and, fed the true orders, its model runs away. Fitted
on the steps where flour did not run dry, the bake is 0.5 x orders using 0.5 flour, and the simulator
applies the cap itself.
"""

from __future__ import annotations

import numpy as np
import pytest
from synth import generate, skill

from sdlab.discovery.identify import identify as matrix
from sdlab.discovery.matrix import identify_one
from sdlab.discovery.starvation import as_coflows
from sdlab.discovery.strategies import load
from sdlab.discovery.strategies.starved_coflows import masks

starved_coflows = load("starved_coflows")

SLOW = {"every": 250, "changes": [
    {"t": 1, "set": {"restock": {"form": "gap", "stock": "flour", "goal": 600, "time": 10}}},
    {"t": 61, "set": {"restock": {"form": "gap", "stock": "flour", "goal": 600, "time": 60}}},
    {"t": 121, "set": {"restock": {"form": "gap", "stock": "flour", "goal": 600, "time": 10}}},
]}


def bakery(schedule: dict | None, coflow: bool = True) -> dict:
    stocks = [{"id": "orders", "initial": 80, "unit": "loaves"}, {"id": "shelf", "initial": 160, "unit": "loaves"},
              {"id": "flour", "initial": 400, "unit": "kg"}]
    bake = {"id": "bake", "from": "orders", "to": "shelf", "rate": {"form": "proportional", "stock": "orders", "k": 0.5}}
    flows = [{"id": "order", "from": None, "to": "orders", "rate": {"form": "constant", "value": 40}},
             {**bake, "uses": [{"stock": "flour", "per": 0.5}]} if coflow else bake,
             {"id": "pickup", "from": "shelf", "to": None, "rate": {"form": "proportional", "stock": "shelf", "k": 0.25}},
             {"id": "restock", "from": None, "to": "flour", "rate": {"form": "gap", "stock": "flour", "goal": 600, "time": 10}}]
    if not coflow:
        # flour used in step with the orders, but not by the bake: nothing caps the bake
        flows.append({"id": "use", "from": "flour", "to": None, "rate": {"form": "linear", "c": 0, "terms": [{"stock": "orders", "k": 0.25}]}})
    return generate(stocks=stocks, flows=flows, steps=1000, schedule=schedule, seed=3)


def bake_flow(r: dict) -> dict | None:
    return next((f for f in r["flows"] if f.get("from") == "orders" and f.get("to") == "shelf"), None)


@pytest.fixture(scope="module")
def slow():
    return bakery(SLOW)


def test_the_main_line_fits_the_orders_through_both_regimes_and_runs_away(slow):
    r = matrix(slow["stocks"], slow["run"], {})
    drain = -(next(row for row in r["matrix"] if row["id"] == "orders")["coef"].get("orders") or 0.0)
    assert drain < 0.25
    assert skill(r, slow) < 0


def test_the_steps_left_out_are_the_steps_where_the_flour_ran_dry(slow):
    # the truth caps the bake on 150 steps (found by rerunning the engine with its flow counters);
    # the mask, found from the levels alone, covers all of them and 13 more
    (used, m), = masks(slow["stocks"], slow["run"], {})
    assert used == ["flour"]
    assert 150 <= m.sum() <= 180


def test_rows_fitted_on_the_kept_steps_give_the_bake_and_its_flour(slow):
    # the mechanism in isolation: with the dry steps left out (and a constant outside inflow, so the
    # main line's chance inflow pieces do not move the drain), the orders drain at 0.5 and the bake
    # moved what the flour held / 0.5 where the cap bound
    (used, m), = masks(slow["stocks"], slow["run"], {})
    r = identify_one(slow["stocks"], slow["run"], {"changes": False, "keep": np.flatnonzero(~m)})
    orders = next(row for row in r["matrix"] if row["id"] == "orders")
    assert orders["coef"]["orders"] == pytest.approx(-0.5, abs=0.01)
    lv = np.array([slow["run"]["levels"][s["id"]] for s in slow["stocks"]], float)
    _, found = as_coflows(r["flows"], r["matrix"], slow["stocks"], lv, slow["run"]["t"], m, used, per_from="dry")
    (f,) = found
    assert (f["source"], f["flow_to"]) == ("orders", "shelf")
    assert f["per_dry"] == pytest.approx(0.5, abs=0.02)
    assert f["t"] > 2


def test_fitted_where_the_flour_did_not_run_dry_the_bake_uses_flour(slow):
    # the co-flow candidates alone (the judge, which feeds each model its own inflow pieces, prefers
    # the main line here: its pieces replay the pile-ups); with the main line's changing inflows the
    # orders' chance pieces pull the drain to 0.57
    r = starved_coflows(slow["stocks"], slow["run"], {"starved_only": True})
    f = bake_flow(r)
    assert f is not None and f["rate"]["form"] == "proportional"
    assert f["rate"]["k"] == pytest.approx(0.5, abs=0.08)
    assert [u["stock"] for u in f.get("uses") or []] == ["flour"]
    assert f["uses"][0]["per"] == pytest.approx(0.5, abs=0.12)
    assert skill(r, slow) > 0.8
    assert skill(starved_coflows(slow["stocks"], slow["run"], {"starved_only": True, "per_from": "dry"}), slow) > 0.85


def test_control_a_flour_that_never_runs_dry_gives_the_main_line():
    d = bakery(None)
    assert min(d["run"]["levels"]["flour"]) > 200
    mine = starved_coflows(d["stocks"], d["run"], {})
    main = matrix(d["stocks"], d["run"], {})
    assert not any(f.get("uses") for f in mine["flows"])
    assert mine["chosen"] == main["chosen"]
    assert abs(skill(mine, d) - skill(main, d)) < 0.01


def test_control_an_outflow_of_flour_driven_by_orders_that_does_not_cap_the_bake_gets_no_uses():
    d = bakery(SLOW, coflow=False)
    assert min(d["run"]["levels"]["flour"]) < 20                  # the flour does run dry
    r = starved_coflows(d["stocks"], d["run"], {})
    assert not any(f.get("uses") for f in r["flows"])
