"""The replay (sd/experiments/replay.py): the base and the experiment over a past window, on its
measured inputs, against what was measured; the backtest that tells an equation that explains
what happened from one tuned to an outcome."""

import gzip
import json
from pathlib import Path

import pytest
from experiment_systems import chain, history_of

from orchestra.sd.experiments.edits import apply
from orchestra.sd.experiments.replay import replay
from orchestra.sd.model import Model
from orchestra.sd.strategies import sd_installed

pytestmark = pytest.mark.skipif(not sd_installed(), reason="simulating needs orchestra[sd]")

BAKERY = Path(__file__).parent.parent / "fixtures" / "sd" / "bakery-whatif.json.gz"


def draft(m, *edits):
    return apply(m, {}, m, list(edits), "x-000000000000", "tester").model


def test_the_true_equation_scores_better_than_a_wrong_one_on_data_it_made():
    truth = chain()
    # the ready stock starts far above where it settles, so the drain's form shows in the data
    h = history_of(truth, minutes=60, start_levels={"queue": 0.0, "ready": 60.0}, seed=3)
    # a wrong drain: a constant at the rate the true one has at its settled level (0.3 × 20)
    wrong = draft(truth, {"op": "replace_flow", "id": "drain", "equation": "c", "params": {"c": 6.0}})
    r = replay(truth, wrong, h)
    d = r["flows"]["drain"]
    assert d["versus_base"] == "worse", d
    assert d["experiment"]["one_step"]["deviance"] > d["base"]["one_step"]["deviance"] + 20, "far more than chance (one number is worth 2)"
    assert d["base"]["one_step"]["d2"] > 0.2 > d["experiment"]["one_step"]["d2"], "the true law explains the counts; a constant does not"
    ready = r["stocks"]["ready"]
    assert ready["versus_base"] == "worse" and ready["error"]["experiment"] > 2 * ready["error"]["base"]
    assert r["flows"]["arrive"]["versus_base"] == "same" and r["stocks"]["queue"]["versus_base"] == "same"
    # and the other way about: a base with the wrong equation, the experiment with the true one
    back = replay(wrong, draft(wrong, {"op": "replace_flow", "id": "drain", "equation": "k * ready", "params": {"k": 0.3}}), h)
    assert back["flows"]["drain"]["versus_base"] == "better" and back["stocks"]["ready"]["versus_base"] == "better"
    assert back["summary"] == {"stocks": {"better": 1, "same": 1, "worse": 0}, "flows": {"better": 1, "same": 3, "worse": 0}}


def test_observed_against_simulated_on_the_windows_own_grid():
    truth = chain()
    h = history_of(truth, minutes=30, start_levels={"queue": 0.0, "ready": 60.0}, seed=4)
    r = replay(truth, truth, h, points=31)
    assert r["t"][0] == 0 and r["t"][-1] == pytest.approx(1800) and len(r["t"]) == 31
    ready = r["stocks"]["ready"]
    assert ready["measured"][0] == [0.0, 60.0] and ready["base"][0] == 60.0 == ready["experiment"][0]
    assert ready["base"][-1] == pytest.approx(20.0 + 40 * 0.0, abs=4.0), "settled near 20"
    assert r["flows"]["drain"]["measured_total"] > 0 and r["flows"]["drain"]["base"]["total"] > 0


def test_a_flow_written_observed_replays_what_was_counted():
    truth = chain()
    h = history_of(truth, minutes=30, seed=5)
    r = replay(truth, draft(truth, {"op": "replace_flow", "id": "arrive", "equation": "observed()"}), h)
    a = r["flows"]["arrive"]
    assert a["experiment"]["one_step"] is None, "nothing to score: it is the measurement"
    assert a["experiment"]["total"] == pytest.approx(a["measured_total"], rel=0.03)


def test_a_replay_runs_on_what_was_measured():
    truth = chain()
    h = history_of(truth, minutes=10)
    reads_input = apply(truth, {}, truth, [{"op": "set_input", "input": "price", "scenario": {"kind": "value", "value": 1}},
                                           {"op": "replace_flow", "id": "arrive", "equation": "3 * price"}], "x-000000000000", "t").model
    with pytest.raises(ValueError, match="reads input price, not measured in the window"):
        replay(truth, reads_input, h)
    with pytest.raises(ValueError, match="end after it starts"):
        replay(truth, truth, h, start=h["at"], end=h["start"])


def test_on_the_bakery_the_base_replays_its_last_hour_and_an_experiment_is_scored_against_it():
    with gzip.open(BAKERY, "rt") as fh:
        d = json.load(fh)
    m, h = Model.from_json(d["model"]), d["history"]
    r = replay(m, m, h)
    assert r["summary"]["flows"]["worse"] == 0 and r["summary"]["stocks"]["worse"] == 0
    scored = {fid: f["base"]["one_step"] for fid, f in r["flows"].items() if f["base"]["one_step"]}
    assert len(scored) >= 15 and all(s["stretches"] >= 2 for s in scored.values())
    # the last hour again, with the ovens baking at half the fitted rate: inspections starve
    slow = draft(m, {"op": "set_params", "flow": "bakery_orders_baked_total", "params": {"k": 0.5}})
    c = replay(m, slow, h)
    assert c["flows"]["bakery_orders_baked_total"]["versus_base"] == "worse", "the fitted rate explains the hour better"
    assert c["flows"]["bakery_orders_baked_total"]["experiment"]["total"] < c["flows"]["bakery_orders_baked_total"]["base"]["total"]
