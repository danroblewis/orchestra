"""combined_lean (sdlab/discovery/strategies/combined_lean): inflow change places re-chosen at a
modified-BIC price, weak flows dropped, the truth left as it is."""

import copy

import numpy as np
import pytest

from sdlab.discovery.strategies.combined_lean._vendored.combined import judge as J
from sdlab.discovery.strategies.combined_lean.prune import _segment, change_places, drop_flows, lean, resegment
from sdlab.ladder import cases as casemod
from sdlab.ladder import data
from sdlab.skill import truth_by_time


@pytest.fixture(autouse=True)
def cache(tmp_path, monkeypatch):
    monkeypatch.setenv("SDLAB_LADDER_CACHE", str(tmp_path / "ladder"))
    return tmp_path / "ladder"


def cell(case_id, variant):
    c = casemod.load(case_id)
    model = casemod.truth_model(c, variant)
    d = data.load(c, variant)
    stocks = casemod.page_stocks(model)
    run = {"t": d["t"], "levels": d["levels"]}
    return model, d, run, J.Data(stocks, run, None, d.get("inputs"))


def test_segmentation_keeps_a_real_step_and_drops_a_place_the_noise_made():
    rng = np.random.default_rng(1)
    r = np.r_[np.full(100, 3.0), np.full(100, 7.0)] + rng.normal(0, 1, 200)
    w = np.ones(200)
    assert _segment(r, w, [0, 50, 100, 150], cost=1.5 * np.log(200)) == [0, 100]


def test_a_pieced_constant_inflow_is_merged_into_one():
    model, d, run, D = cell("002-inflow-outflow", "counts-short")
    truth = truth_by_time(model, d["t"])[0]
    pieced = copy.deepcopy(truth)
    t = d["t"]
    for f in pieced:
        if not f.get("from"):
            v = f["byTime"][0]["rate"]["value"]
            f.pop("byTime")
            f["rate"] = {"form": "constant", "value": v}
            f["inflow"] = [{"from": t[1], "to": t[120], "value": v * 0.97}, {"from": t[121], "to": t[-1], "value": v * 1.03}]
    assert change_places(pieced) == 1
    seg = resegment(pieced, D, 1.5)
    assert seg is not None and change_places(seg) == 0


def test_a_flow_that_moves_nothing_is_dropped():
    model, d, run, D = cell("003-chain-2", "counts-long")
    truth = [{k: v for k, v in f.items() if k != "byTime"} for f in truth_by_time(model, d["t"])[0]]
    extra = truth + [{"from": "B", "to": None, "rate": {"form": "linear", "c": 0, "terms": [{"stock": "A", "k": 1e-4}]}}]
    out = drop_flows(extra, D, 1.5, 1.0)
    assert len(out) == len(truth)


@pytest.mark.parametrize("case_id,variant", [("003-chain-2", "counts-long"), ("012-rework", "counts-short"), ("020-unannounced-step", "counts-long")])
def test_the_truth_is_left_as_it_is(case_id, variant):
    model, d, run, D = cell(case_id, variant)
    truth = truth_by_time(model, d["t"])[0]
    flows = []
    for f in truth:                                  # an unannounced step written as inflow pieces, as a found model writes it
        segs = f.get("byTime") or []
        g = {k: v for k, v in f.items() if k != "byTime"}
        if len({repr(s["rate"]) for s in segs}) > 1:
            g["inflow"] = [{"from": s["from"], "to": s["to"], "value": s["rate"]["value"]} for s in segs]
            g["rate"] = segs[0]["rate"]
        flows.append(g)
    out, report = lean(flows, D, run)
    assert len(out) == len(flows) and change_places(out) == change_places(flows), report


def test_a_model_with_an_unmeasured_stock_is_returned_unchanged():
    model, d, run, D = cell("015-hidden-stock", "none-short")
    truth = truth_by_time(model, d["t"])[0]
    out, report = lean(truth, D, run)
    assert out is truth and report["skipped"] == "unmeasured stocks"
