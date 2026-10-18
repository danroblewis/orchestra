"""Injections: announced interventions (add an amount to a stock at a step) in the ground-truth engine,
the discovery simulator, the grader and discovery itself."""

import json
import sys
from pathlib import Path

import numpy as np

from sdlab.discovery import identify
from sdlab.discovery.simulate import Model
from sdlab.sdtruth import Truth

ROOT = Path(__file__).resolve().parents[1]
CHAIN = {"id": "t", "seed": 1, "steps": 300, "noise": {},
         "stocks": [{"id": "a", "name": "a", "unit": "x", "initial": 50}, {"id": "b", "name": "b", "unit": "x", "initial": 10}],
         "flows": [{"id": "in", "name": "in", "from": None, "to": "a", "rate": {"form": "constant", "value": 10}},
                   {"id": "ab", "name": "ab", "from": "a", "to": "b", "rate": {"form": "proportional", "stock": "a", "k": 0.2}},
                   {"id": "out", "name": "out", "from": "b", "to": None, "rate": {"form": "proportional", "stock": "b", "k": 0.1}}]}


def truth(tmp_path, model):
    p = tmp_path / "truth.model.json"
    p.write_text(json.dumps(model))
    return Truth(p)


def test_an_injection_adds_to_a_stock_at_the_start_of_its_step_and_is_reported(tmp_path):
    t = truth(tmp_path, CHAIN)
    calm, kicked = t.run(steps=120), t.run(steps=120, injections=[{"t": 100, "stock": "a", "amount": 500}])
    assert calm["levels"]["a"][98] == kicked["levels"]["a"][98], "nothing changes before the injection"
    # at step 100 the 500 arrive before that step's flows, so a fifth of them already leaves for b
    assert abs((kicked["levels"]["a"][99] - calm["levels"]["a"][99]) - 400) < 1e-6
    assert abs((kicked["levels"]["b"][99] - calm["levels"]["b"][99]) - 100) < 1e-6
    assert kicked["injections"] == [{"t": 100, "stock": "a", "amount": 500.0}] and "injections" not in calm
    m = t.measured(steps=120, injections=[{"t": 100, "stock": "a", "amount": 500}])
    assert m["injections"] == kicked["injections"]


def test_a_stock_never_goes_below_zero_and_the_reported_amount_is_what_was_taken(tmp_path):
    r = truth(tmp_path, CHAIN).run(steps=120, injections=[{"t": 100, "stock": "b", "amount": -10_000}])
    assert r["injections"][0]["amount"] < 0 and min(r["levels"]["b"]) >= 0


def test_the_simulator_makes_injections_as_the_engine_does(tmp_path):
    t = truth(tmp_path, CHAIN)
    inj = [{"t": 100, "stock": "a", "amount": 500}]
    engine = t.run(steps=150, injections=inj)["levels"]
    L = Model([dict(f) for f in CHAIN["flows"]], ["a", "b"]).run(np.array([[50.0], [10.0]]), np.arange(1, 151, dtype=float)[:, None], inj)
    assert abs(L[0, 0] - engine["a"][-1]) < 1e-3 and abs(L[1, 0] - engine["b"][-1]) < 1e-3


def test_the_grader_makes_the_injections_in_both_models_so_the_truth_grades_perfectly(tmp_path):
    sys.path.insert(0, str(ROOT / "tests" / "bench"))
    from grade import same_behaviour

    model = {**CHAIN, "noise": {"counts": True}}
    t = truth(tmp_path, model)
    inj = [{"t": k, "stock": "a", "amount": 300} for k in range(50, 300, 50)]
    m = t.measured(steps=300, injections=inj)
    data = {**m, "all_levels": t.run(steps=300, injections=inj)["levels"]}
    perfect = {"flows": [f for f in model["flows"] if f["id"] != "in"]}   # the outside inflow comes from the truth
    assert same_behaviour(perfect, model, data, horizon=20)["skill"] > 0.999


def test_discovery_takes_announced_injections_as_known_changes(tmp_path):
    model = {**CHAIN, "noise": {"counts": True}, "steps": 600}
    t = truth(tmp_path, model)
    inj = [{"t": k, "stock": "a", "amount": 400} for k in range(60, 600, 60)]
    m = t.measured(steps=600, injections=inj)
    stocks = [{"id": "a", "unit": "x"}, {"id": "b", "unit": "x"}]
    r = identify(stocks, {"t": m["t"], "levels": m["levels"]}, {"injections": m["injections"]})
    move = next(f for f in r["flows"] if f["from"] == "a" and f["to"] == "b" and not f.get("driver"))
    assert abs(move["rate"]["k"] - 0.2) < 0.02
    inflow = next(f for f in r["flows"] if not f["from"] and f["to"] == "a" and not f.get("driver"))
    assert abs(inflow["rate"]["value"] - 10) < 1.5, "the injections are not mistaken for outside inflow"
