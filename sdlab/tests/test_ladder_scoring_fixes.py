"""The six scoring fixes the user approved on 2026-10-19 (docs/LADDER.md, Scoring):

1. a truth at a sub-step (dt < 1) is scored by its per-recorded-step equivalents (substep.py);
2. a hidden path fed from outside is a scored part (parts.py), with the hidden oracle's SEs;
3. measured inputs are columns of the equivalence check;
4. a truth with effects is checked for equivalence by what its flows compute;
5. a real case's twin is analysed on its training samples with its measurement error;
6. the analysis reads measured inputs, so a floor that binds is seen (125)."""

from __future__ import annotations

import copy

import pytest

from sdlab.ladder import analysis, data, score
from sdlab.ladder import cases as casemod
from sdlab.ladder.fisher import TruthParams
from sdlab.ladder.hidden_oracle import HiddenOracle
from sdlab.ladder.parts import parts, windows
from sdlab.ladder.substep import per_step
from sdlab.skill import truth_by_time


@pytest.fixture(autouse=True)
def cache(tmp_path, monkeypatch):
    monkeypatch.setenv("SDLAB_LADDER_CACHE", str(tmp_path / "ladder"))


def setup(case_id, variant):
    c = casemod.load(case_id)
    model = casemod.truth_model(c, variant)
    return c, model, data.load(c, variant)


def scored(case_id, variant, flows):
    c, model, d = setup(case_id, variant)
    return score.equations(c, casemod.variant(c, variant)["noise"], model, flows, d)


def with_rate(f, rate):
    return {**f, "rate": rate, "byTime": [{**g, "rate": rate} for g in f.get("byTime") or [{"from": 0, "to": 10 ** 9}]]}


# ---- 1. dt < 1 ----

def test_a_drain_at_a_sub_step_becomes_its_per_step_equivalent():
    c, model, d = setup("104-canonical-teacup", "none-short")
    flows, _ = per_step(truth_by_time(model, d["t"])[0], d, model)
    r = flows[0]["byTime"][0]["rate"]
    k = 1 - (1 - 0.1 / 8) ** 8                          # a drain k recorded every 8 sub-steps
    assert r["terms"][0]["k"] == pytest.approx(k, rel=1e-6)
    assert r["c"] == pytest.approx(-70 * k, rel=1e-6)    # the goal stays at 70: -7 x the same factor / 0.1


def test_the_per_step_numbers_pass_and_the_continuous_ones_do_not():
    c, model, d = setup("104-canonical-teacup", "none-short")
    continuous = truth_by_time(model, d["t"])[0]
    assert scored("104-canonical-teacup", "none-short", per_step(continuous, d, model)[0])["status"] == "pass"
    assert scored("104-canonical-teacup", "none-short", continuous)["status"] != "pass"    # 0.1 against 0.0957: 4.5% off


def test_a_truth_at_dt_1_is_unchanged():
    c, model, d = setup("003-chain-2", "counts-short")
    flows = truth_by_time(model, d["t"])[0]
    assert per_step(flows, d, model)[0] is flows


# ---- 2. hidden paths fed from outside ----

def test_a_supply_line_fed_from_outside_is_a_scored_part():
    c, model, d = setup("133-hidden-supply-line", "none-short")
    p, notes = parts(model["flows"], {"I"}, (1, 300))
    assert p[("hidden", None, "I")] == {"delay": 4.0}
    assert p[("via", None, "I", "1")] == 60 and p[("via", None, "I", "I")] == pytest.approx(-0.2)
    assert not notes


def test_a_found_chain_through_stages_has_the_mean_time_through_them():
    flows = [{"from": None, "to": "h1", "rate": {"form": "linear", "c": 75, "terms": [{"stock": "I", "k": -0.125}]}},
             {"from": "h1", "to": "h2", "rate": {"form": "proportional", "stock": "h1", "k": 0.5}},
             {"from": "h2", "to": "h3", "rate": {"form": "proportional", "stock": "h2", "k": 0.5}},
             {"from": "h3", "to": "I", "rate": {"form": "proportional", "stock": "h3", "k": 0.5}}]
    p, _ = parts(flows, {"I"}, (1, 10))
    assert p[("hidden", None, "I")]["delay"] == pytest.approx(6.0)
    assert p[("via", None, "I", "1")] == 75


def test_without_the_hidden_stage_133_fails_and_with_it_passes():
    c, model, d = setup("133-hidden-supply-line", "none-short")
    truth = truth_by_time(model, d["t"])[0]
    assert scored("133-hidden-supply-line", "none-short", truth)["status"] == "pass"
    plain = [f for f in truth if f["id"] == "i_out"] + [with_rate({"from": None, "to": "I"}, {"form": "linear", "c": 60, "terms": [{"stock": "I", "k": -0.2}]})]
    s = scored("133-hidden-supply-line", "none-short", plain)
    assert s["status"] == "fail"
    assert not next(p for p in s["parts"] if p["key"] == "outside -> (hidden) -> I")["found"]


def test_a_found_hidden_path_the_truth_lacks_is_spurious():
    c, model, d = setup("003-chain-2", "none-short")
    flows = truth_by_time(model, d["t"])[0] + [{"from": None, "to": "x~h", "rate": {"form": "constant", "value": 20}},
                                               {"from": "x~h", "to": "B", "rate": {"form": "proportional", "stock": "x~h", "k": 0.5}}]
    s = scored("003-chain-2", "none-short", flows)
    assert s["status"] == "fail" and any("(hidden)" in x["key"] for x in s["spurious"])


@pytest.mark.parametrize("case_id", ["133-hidden-supply-line", "134-delayed-measured-input"])
def test_the_hidden_oracle_covers_a_stock_fed_from_outside(case_id):
    c, model, d = setup(case_id, "counts-long")
    o = HiddenOracle(truth_by_time(model, d["t"])[0], d, windows(model, d["t"]), "counts")
    assert o.ok
    b = o.fit["B"]
    se = o.hidden_se(("hidden", None, b), 0)
    assert 0.1 < se["delay"] < 2.0                         # the delay (4 or 8 steps) to within about a step
    reader = "pump" if case_id.startswith("134") else "I"
    assert 0 < o.part_se(("via", None, b, reader), 0) < 0.5
    assert 0 < o.part_se(("flow", b, None, b), 0) < 0.05


# ---- 3. measured inputs in the equivalence ----

def test_an_exact_equivalent_reading_a_measured_input_is_equivalent():
    """125's hiring (desired - R) / 6 written as an inflow desired / 6 and a larger drain of R: the same
    linear system of the level and the input (the floor aside)."""
    c, model, d = setup("125-floored-gap-to-measured-target", "none-short")
    flows = [with_rate({"from": None, "to": "R"}, {"form": "linear", "c": 0, "terms": [{"stock": "desired", "k": 1 / 6}]}),
             with_rate({"from": "R", "to": None}, {"form": "proportional", "stock": "R", "k": 1 / 6 + 0.025})]
    assert scored("125-floored-gap-to-measured-target", "none-short", flows)["status"] == "equivalent"
    flows[0] = with_rate(flows[0], {"form": "linear", "c": 0, "terms": [{"stock": "desired", "k": 0.12}]})
    assert scored("125-floored-gap-to-measured-target", "none-short", flows)["status"] == "fail"


# ---- 4. effects in the equivalence ----

def swapped(model, d, scale=1.0):
    """101's infection 0.01 S x I / 20 written with the roles swapped: 0.0005 I x S."""
    out = copy.deepcopy(truth_by_time(model, d["t"])[0])
    inf = next(f for f in out if f["id"] == "infection")
    out[out.index(inf)] = with_rate({**inf, "effects": [{"stock": "Susceptible", "shape": "linear", "normal": 1, "max": 1e9}]},
                                    {"form": "proportional", "stock": "Infectious", "k": 0.0005 * scale})
    return out


def test_a_product_with_its_roles_swapped_is_equivalent():
    c, model, d = setup("101-canonical-seir", "none-short")
    assert scored("101-canonical-seir", "none-short", swapped(model, d))["status"] == "equivalent"


def test_a_product_that_computes_something_else_is_not():
    c, model, d = setup("101-canonical-seir", "none-short")
    assert scored("101-canonical-seir", "none-short", swapped(model, d, 1.3))["status"] == "fail"


def test_an_adoption_twin_read_through_the_other_stock_is_equivalent():
    """N = 100 - A on every sample of an adoption twin: rates that read A in place of N compute the same."""
    from sdlab.ladder.real import data as real_data
    c = casemod.load("real-adoption-internet")
    model = casemod.truth_model(c, "twin")
    d = real_data.load(c, "twin")
    alt = copy.deepcopy(truth_by_time(model, d["t"])[0])
    for i, f in enumerate(alt):
        r = f["rate"]
        k = r["terms"][0]["k"]
        alt[i] = with_rate(f, {"form": "linear", "c": r.get("c", 0) + 100 * k, "terms": [{"stock": "A", "k": -k}]})
    assert score.equations(c, "counts", model, alt, d)["status"] == "equivalent"


# ---- 5. twins ----

def test_a_twin_is_analysed_on_its_training_samples_with_its_measurement_error():
    a = analysis.analyse("real-gause-a3-pa", "twin")
    c = casemod.load("real-gause-a3-pa")
    assert a["points"] == c["real"]["train"]
    assert a["label"] in ("achievable", "data-limited") and a["parts"]
    assert all(p["source"] == "output error (twin)" for p in a["parts"])


def test_an_adoption_twin_cannot_say_which_of_two_complementary_stocks_a_rate_reads():
    a = analysis.analyse("real-adoption-internet", "twin")
    assert a["label"] == "unidentifiable"
    assert any("collinear" in w for w in a["why"])


# ---- 6. floors and inputs in the analysis ----

def test_the_bound_reads_measured_inputs():
    c, model, d = setup("125-floored-gap-to-measured-target", "counts-long")
    tp = TruthParams(model, d, "counts")
    hiring = next(i for i, f in enumerate(tp.flows) if f["id"] == "hiring")
    q = tp.rates(tp.theta0)[hiring]
    assert q.max() > 10 and (q == 0).any()                 # it moves people, and its floor binds on some steps


@pytest.mark.parametrize("variant", ["counts-long", "none-long"])
def test_a_floor_that_binds_makes_125_identifiable(variant):
    a = analysis.analyse("125-floored-gap-to-measured-target", variant)
    assert a["label"] != "unidentifiable", a["why"]
