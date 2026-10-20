"""Consistency evidence beside the pass (sdlab/ladder/consistency.py): the Cramer-Rao bound on every true
number and the likelihood ratio of a found model against the truth's refit, on the run discovery saw."""

import copy

import pytest

from sdlab.ladder import cases as casemod
from sdlab.ladder import consistency as C
from sdlab.ladder import score


@pytest.fixture(autouse=True)
def cache(tmp_path, monkeypatch):
    monkeypatch.setenv("SDLAB_LADDER_CACHE", str(tmp_path / "ladder"))


_cells: dict = {}


def cell(cid, variant):
    if (cid, variant) not in _cells:
        _cells[(cid, variant)] = C.Cell(casemod.load(cid), variant)
    return _cells[(cid, variant)]


def scaled(flows, factor, which=None):
    out = copy.deepcopy(flows)
    for f in out:
        if which and f["id"] != which:
            continue
        for g in f["byTime"]:
            r = g["rate"]
            for k in ("k", "value"):
                if k in r:
                    r[k] *= factor
            for t in r.get("terms") or []:
                t["k"] *= factor
    return out


def test_the_truth_is_within_the_bound_and_the_data_cannot_tell_it_from_its_refit():
    c = cell("300-k8s-requests-in-flight", "counts-short")
    res = C.check(c.case, c.variant, c.truth_flows, cell=c)
    b, lk = res["bound"], res["likelihood"]
    assert b["ok"] and b["worst_z"] < 1e-6 and not b["extra"]
    assert all(r["se"] > 0 and r["diagnosis"] == "within the bound" for r in b["parts"])
    assert b["joint"]["df"] == 2 and b["joint"]["chi2"] < 1e-9
    assert lk["verdict"] == "the data cannot tell them apart"
    assert lk["LR"] == pytest.approx(lk["LR_truth"]) and lk["LR"] >= 0
    assert lk["numbers"] == {"truth": 2, "truth_identifiable": 2, "found": 2, "extra": 0}


def test_a_drain_off_by_far_more_than_the_run_allows_is_rejected_and_located():
    c = cell("003-chain-2", "counts-long")
    flows = scaled(c.truth_flows, 0.85, which=c.truth_flows[-1]["id"])        # the last flow's number 15% low
    res = C.check(c.case, c.variant, flows, cell=c)
    b, lk = res["bound"], res["likelihood"]
    assert not b["ok"]
    bad = [r for r in b["parts"] if r["diagnosis"] != "within the bound"]
    assert len(bad) == 1 and bad[0]["diagnosis"].startswith("method error") and abs(bad[0]["z"]) > 3
    assert lk["rejected"] and lk["verdict"] == "the data reject the found model" and lk["p"] < 0.01
    assert lk["where"] and lk["where"][0]["loss"] > 0 and lk["where"][0]["kinds"]


def test_every_number_off_by_one_factor_is_named():
    c = cell("300-k8s-requests-in-flight", "meas-short")
    res = C.check(c.case, c.variant, scaled(c.truth_flows, 0.8), cell=c)
    assert any(k.startswith("common factor") for k in res["bound"]["kinds"])


def test_a_small_extra_term_is_within_the_noise_and_the_joint_test_gives_it_its_freedom():
    c = cell("300-k8s-requests-in-flight", "counts-short")
    flows = copy.deepcopy(c.truth_flows) + [{"id": "x", "from": None, "to": "inflight", "rate": {"form": "constant", "value": 0.01},
                                               "byTime": [{"from": 1, "to": 10 ** 6, "rate": {"form": "constant", "value": 0.01}}]}]
    res = C.check(c.case, c.variant, flows, cell=c)
    b, lk = res["bound"], res["likelihood"]
    assert [e["diagnosis"] for e in b["extra"]] == ["extra but within the noise"]
    assert b["joint"]["extra_terms"] == 1 and b["joint"]["p"] > 0.01 and b["ok"]
    assert lk["verdict"] == "the data cannot tell them apart" and lk["numbers"]["extra"] == 1


def test_noise_free_data_use_the_floor_and_have_no_likelihood():
    c = cell("300-k8s-requests-in-flight", "none-short")
    res = C.check(c.case, c.variant, scaled(c.truth_flows, 1.01), cell=c)
    b = res["bound"]
    assert b["noise_free"] and res["likelihood"] is None and "joint" not in b
    assert all(r["se"] == pytest.approx(C.FLOOR_REL * abs(r["true"])) for r in b["parts"])
    assert all(abs(r["z"]) == pytest.approx(10.0) for r in b["parts"])          # 1% off with a 0.1% floor


def test_effects_are_not_covered_and_say_why():
    c = cell("017-linear-effect", "counts-short")
    res = C.check(c.case, c.variant, c.truth_flows, cell=c)
    assert res == {"covered": False, "why": C.NOT_COVERED, "bound": None, "likelihood": None}


def test_a_found_stock_of_its_own_is_not_covered_by_the_likelihood():
    c = cell("300-k8s-requests-in-flight", "counts-short")
    flows = copy.deepcopy(c.truth_flows) + [{"id": "h", "from": "inflight", "to": "H", "rate": {"form": "proportional", "stock": "inflight", "k": 0.01}}]
    lk = C.likelihood_check(c, flows)
    assert lk["covered"] is False and "stock of its own (H)" in lk["why"]


def test_found_numbers_count_placed_breakpoints_not_announced_ones():
    pieces = {"from": None, "to": "A", "rate": {"form": "constant", "value": 5}, "levels": 2,
              "inflow": [{"from": 1, "to": 99, "value": 3}, {"from": 100, "to": 150, "value": 7}, {"from": 151, "to": 300, "value": 3}]}
    drain = {"from": "A", "to": None, "rate": {"form": "linear", "c": 0, "terms": [{"stock": "A", "k": 0.1}]}}
    assert C.found_numbers([drain]) == 1                                         # a zero constant is not a number
    assert C.found_numbers([pieces, drain]) == 2 + 2 + 1
    assert C.found_numbers([pieces, drain], {101}) == 2 + 1 + 1                  # 100 is an announced era's start (within a step)


def test_the_checks_are_not_in_the_score_hash():
    import inspect
    assert "consistency" not in inspect.getsource(score.score_hash)


def test_a_biased_variant_gives_the_found_model_its_bias():
    """bias-short reports B x 1.2: the truth in true units was rejected (no bias in the found model's likelihood);
    with the bias free, as the refit has it, the truth cannot be told from its refit and the bias is recovered."""
    c = cell("080-noisy-chain-2", "bias-short")
    lk = C.likelihood_check(c, c.truth_flows)
    assert not lk["rejected"] and lk["verdict"] == "the data cannot tell them apart"
    assert lk["bias"]["B"] == pytest.approx(1.2, abs=0.05)
    assert lk["LR_vs_true_numbers"] <= 1e-6


def test_the_reference_is_never_below_the_true_numbers():
    """Weekly means: the refit can end below the true numbers; the reference is then the true numbers (LR_truth 0)."""
    c = cell("082-noisy-link-loop", "weekly-long")
    lk = C.likelihood_check(c, c.truth_flows)
    assert lk["LR_truth"] >= 0 and lk["LR"] >= -1e-9
    assert lk["verdict"] == "the data cannot tell them apart"


def test_where_the_noise_model_rejects_the_truth_itself_a_found_model_is_judged_against_the_true_numbers():
    """025 empties its stock (a floor the linear model does not have): the truth's refit beats the true numbers by far
    more than chi-square allows, so the truth is not rejected, a model far off still is; the unidentified numbers (the
    empty eras' constants) are reported, not held against the model."""
    c = cell("025-runs-empty", "counts-long")
    lk = C.likelihood_check(c, c.truth_flows)
    assert lk["noise_model_misfit"] and lk["LR"] > lk["critical"] and not lk["rejected"]
    assert lk["verdict"].startswith("the data cannot tell it from the truth at its true numbers")
    far = C.likelihood_check(c, scaled(c.truth_flows, 0.7))
    assert far["rejected"] and far["LR_vs_true_numbers"] > far["critical"]
    b = C.bound_check(c, c.truth_flows)
    assert b["ok"] and b["unidentified"]
