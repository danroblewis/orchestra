"""The scoring changes the user approved on 2026-10-19 (docs/LADDER.md, "The scoring changes of 19
October 2026, second round"): only truly exogenous inflows are swapped by the behaviour grader, and a
found c + k x inflow loses its c there; the thermostat's structure is the reference's (physics tests in
tests/test_ladder_physics.py); found two-way flows and signed stocks run unfloored (sim.py); a rate
reading a smoothing is a scored part."""

import pytest

from sdlab.ladder import cases as casemod
from sdlab.ladder import data, score
from sdlab.ladder import sim as ladder_sim
from sdlab.ladder.parts import parts
from sdlab.skill import exogenous, own_flows, truth_by_time


@pytest.fixture(autouse=True)
def cache(tmp_path, monkeypatch):
    monkeypatch.setenv("SDLAB_LADDER_CACHE", str(tmp_path / "ladder"))
    return tmp_path / "ladder"


def _load(cid, variant=None):
    c = casemod.load(cid)
    v = variant or c["variants"][0]["name"]
    return c, v, casemod.truth_model(c, v), data.load(c, v), data.load(c, v, fresh=True)


# ---- 1. only truly exogenous inflows are swapped ----

def test_a_constant_inflow_with_an_effect_is_not_exogenous():
    _, _, m, d, _ = _load("sd-sawmill")
    by = {f["id"]: f for f in m["flows"]}
    assert exogenous(by["deliver"]) and not exogenous(by["sharpen"])
    _, fed = truth_by_time(m, d["t"])
    assert fed == {"logs"}, "sharpness is fed by its own effect-carrying inflow: not swapped"
    assert not exogenous({"from": None, "to": "x", "rate": {"form": "constant", "value": 1}, "uses": [{"stock": "y", "per": 1}]})


def test_the_found_constant_into_an_endogenously_fed_stock_is_kept():
    flows = [{"from": None, "to": "sharpness", "rate": {"form": "constant", "value": 6}},
             {"from": None, "to": "logs", "rate": {"form": "constant", "value": 9}}]
    own = own_flows(flows, {"logs"})
    assert own == [flows[0]]


def test_a_found_c_plus_kx_inflow_has_its_c_swapped_and_keeps_its_link():
    f = {"from": None, "to": "a", "rate": {"form": "linear", "c": 5.0, "terms": [{"stock": "b", "k": 0.2}]}}
    (g,) = own_flows([f], {"a"})
    assert g["rate"]["c"] == 0 and g["rate"]["terms"] == f["rate"]["terms"]
    assert own_flows([f], set()) == [f], "into a stock the truth does not feed from outside: unchanged"
    with_effect = {**f, "effects": [{"stock": "b", "shape": "linear", "normal": 1}]}
    assert own_flows([with_effect], {"a"}) == [with_effect]


def test_a_truth_with_an_effect_on_its_outside_inflow_still_has_full_skill():
    c, v, m, d, fr = _load("160-effect-on-outside-inflow")
    _, fed = truth_by_time(m, d["t"])
    assert not fed
    true_flows, _ = truth_by_time(m, d["t"])                      # its schedule: the found model's own, nothing swapped
    b = score.behaviour(m, true_flows, d, None)
    assert b["in_sample"]["20"]["skill"] == pytest.approx(1.0, abs=1e-6)


# ---- 3. found two-way flows and signed stocks ----

def _xflow(**extra):
    return {"from": None, "to": "X", **extra,
            "rate": {"form": "linear", "c": 0.0, "terms": [{"stock": "u", "k": 1.0}, {"stock": "X", "k": -0.1}]}}


@pytest.mark.parametrize("cid", ["220-distilled-signed-stock-two-way-input", "221-distilled-two-way-flow-on-input"])
def test_a_two_way_found_flow_is_not_floored(cid):
    c, v, m, d, fr = _load(cid)
    one = score.score(c, casemod.variant(c, v)["noise"], m, [_xflow()], d, fr)
    marked = {"two_way": True, **({"signed": True} if cid.startswith("220") else {})}
    two = score.score(c, casemod.variant(c, v)["noise"], m, [_xflow(**marked)], d, fr)
    assert one["status"] == "fail" and two["status"] == "pass"
    assert two["behaviour"]["in_sample"]["20"]["skill"] > 0.999 > 0.5 > one["behaviour"]["in_sample"]["20"]["skill"]


def test_the_oscillator_written_two_way_and_signed_behaves_as_the_truth():
    import numpy as np
    from scipy.linalg import expm
    c, v, m, d, fr = _load("113-canonical-harmonic-oscillator")
    M = expm(np.array([[0.0, 1.0], [-0.05, 0.0]]))               # the exact one-step map of the truth (dt 0.01 in the engine)
    lin = lambda a, b: {"form": "linear", "c": 0.0, "terms": [{"stock": "position", "k": a}, {"stock": "speed", "k": b}]}  # noqa: E731
    found = [{"from": None, "to": "position", "rate": lin(M[0, 0] - 1, M[0, 1]), "two_way": True, "signed": True},
             {"from": None, "to": "speed", "rate": lin(M[1, 0], M[1, 1] - 1), "two_way": True, "signed": True}]
    b = score.behaviour(m, found, d, fr)
    assert b["in_sample"]["20"]["skill"] > 0.999 and b["in_sample"]["100"]["skill"] > 0.99
    floored = [{k: v for k, v in f.items() if k not in ("two_way", "signed")} for f in found]
    assert score.behaviour(m, floored, d, None)["in_sample"]["20"]["skill"] < 0.5


def test_signed_model_without_marks_steps_as_simulate():
    import numpy as np
    from sdlab.discovery.simulate import Model
    flows = [{"from": "a", "to": "b", "rate": {"form": "proportional", "stock": "a", "k": 0.3}},
             {"from": None, "to": "a", "rate": {"form": "constant", "value": 2}},
             {"from": "b", "to": None, "rate": {"form": "linear", "c": -1, "terms": [{"stock": "b", "k": 0.2}]}}]
    L = np.array([[5.0, 0.0], [1.0, 3.0]])
    t = np.array([[1.0, 1.0], [2.0, 2.0], [3.0, 3.0]])
    assert np.allclose(ladder_sim.SignedModel(flows, ["a", "b"]).run(L, t), Model(flows, ["a", "b"]).run(L, t))
    assert isinstance(ladder_sim.found_model(flows, ["a", "b"]), Model) and not ladder_sim.says_signed(flows)


def test_a_two_way_flow_back_out_of_an_unsigned_stock_is_limited_by_what_it_holds():
    import numpy as np
    f = [{"from": None, "to": "x", "two_way": True, "rate": {"form": "constant", "value": -5}}]
    m = ladder_sim.SignedModel(f, ["x"])
    assert np.allclose(m.step(np.array([[3.0]]), np.array([1.0])), [[0.0]])
    s = ladder_sim.SignedModel([{**f[0], "signed": True}], ["x"])
    assert np.allclose(s.step(np.array([[3.0]]), np.array([1.0])), [[-2.0]])


# ---- 4. a rate reading a smoothing is a part ----

def test_graduation_reading_a_smoothing_is_a_scored_part():
    c, v, m, d, _ = _load("115-canonical-enrolment-pipeline")
    s = score.equations(c, casemod.variant(c, v)["noise"], m, m["flows"], d)
    rows = {r["key"]: r for r in s["parts"]}
    assert s["status"] == "pass" and rows["Students -> outside [smooth(enrolment)]"]["ok"]
    assert rows["Students -> outside [smooth(enrolment)]"]["true"] == pytest.approx({"gain": 1.0, "delay": 4.0})
    # a found graduation reading the input directly (no smoothing) is not the part, and is spurious
    wrong = [f for f in m["flows"] if f["id"] == "enrolment"] + [
        {"from": "Students", "to": None, "rate": {"form": "proportional", "stock": "enrolment", "k": 1.0}}]
    w = score.equations(c, casemod.variant(c, v)["noise"], m, wrong, d)
    assert w["status"] == "fail" and not {r["key"]: r for r in w["parts"]}["Students -> outside [smooth(enrolment)]"]["found"]


def test_a_found_single_smoothing_with_the_same_delay_is_right():
    c, v, m, d, _ = _load("115-canonical-enrolment-pipeline")
    found = [f for f in m["flows"] if f["id"] == "enrolment"] + [
        {"from": None, "to": "S", "rate": {"form": "proportional", "stock": "enrolment", "k": 0.25}},
        {"from": "S", "to": None, "rate": {"form": "proportional", "stock": "S", "k": 0.25}},
        {"from": "Students", "to": None, "rate": {"form": "proportional", "stock": "S", "k": 1.0}}]
    p, notes = parts(found, {"Students"}, (1, 10), {"enrolment"})
    assert p[("smooth", "Students", None, "enrolment")] == pytest.approx({"gain": 1.0, "delay": 4.0}) and not notes
    s = score.equations(c, casemod.variant(c, v)["noise"], m, found, d)
    assert s["status"] == "pass", s["parts"]
    slow = [dict(f) for f in found]
    slow[2] = {**slow[2], "rate": {"form": "proportional", "stock": "S", "k": 0.125}}
    slow[1] = {**slow[1], "rate": {"form": "proportional", "stock": "enrolment", "k": 0.125}}
    assert score.equations(c, casemod.variant(c, v)["noise"], m, slow, d)["status"] == "fail", "delay 8, not 4"
