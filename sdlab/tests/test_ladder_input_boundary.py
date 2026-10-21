"""The boundary kind "input" (the user, 2026-10-21): an outside inflow that IS a measured input series,
exactly 1 x it, never rescaled or supplemented. The scorer fails an "input" side's flow whose gain is not
1 (beyond float rounding) or that carries anything else ("input altered"), and a second outside flow on
any declared side (an "invented boundary": one flow per declared flow)."""

import pytest

from sdlab.ladder import cases as casemod
from sdlab.ladder import data, score
from sdlab.ladder.caseformat import compile_case
from sdlab.ladder.substep import per_step
from sdlab.skill import truth_by_time

TANK = """title: Tank fed by a measured series
level: 2
tags: [input]
tests: an inflow that is the measured series itself
seed: 5
inputs:
  pump: pulse_train(30, 10, 8, 50) + 20
stocks: {A: 100}
flows:
  outside -> A: 1 * pump
  A -> outside: 0.1 * A
boundary:
  A: {in: input, out: estimate}
"""


@pytest.fixture(autouse=True)
def cache(tmp_path, monkeypatch):
    monkeypatch.setenv("SDLAB_LADDER_CACHE", str(tmp_path / "ladder"))


def scored(flows, text=TANK, variant="none-short"):
    case = casemod._build("901-input", compile_case(text, "901-input.yaml"))["case"]
    model = casemod.truth_model(case, variant)
    d = data.load(case, variant)
    return score.equations(case, casemod.variant(case, variant)["noise"], model, flows(model, d), d)


def perfect(model, d):
    return per_step(truth_by_time(model, d["t"])[0], d, model)[0]


def inflow(k, c=0.0):
    rate = {"form": "linear", "c": c, "terms": [{"stock": "pump", "k": k}]}
    return {"from": None, "to": "A", "rate": rate, "input": "pump"}


DRAIN = {"from": "A", "to": None, "rate": {"form": "proportional", "stock": "A", "k": 0.1}}


def test_the_truth_passes():
    s = scored(perfect)
    assert s["status"] == "pass" and "input_altered" not in s


def test_exactly_one_passes_a_rescaled_input_fails():
    assert scored(lambda m, d: [inflow(1.0), DRAIN])["status"] == "pass"
    s = scored(lambda m, d: [inflow(0.99), DRAIN])
    assert s["status"] == "fail" and s["input_altered"] == 1
    assert any(n.startswith("input altered: the outside inflow to A reads pump x 0.99") for n in s["notes"])


def test_a_constant_beside_the_input_fails():
    s = scored(lambda m, d: [inflow(1.0, c=0.5), DRAIN])
    assert s["status"] == "fail" and any(n.startswith("input altered") for n in s["notes"])


def test_a_second_outside_flow_on_a_declared_side_is_invented():
    second = {"from": None, "to": "A", "rate": {"form": "min", "terms": [{"stock": "A", "k": 0.01}, {"stock": "pump", "k": 0.1}]}}
    s = scored(lambda m, d: [inflow(1.0), DRAIN, second])
    assert s["status"] == "fail" and s["invented_boundary"] == 1
    assert any("one flow per declared side" in n for n in s["notes"])


def test_measured_keeps_its_estimated_gain():
    text = TANK.replace("1 * pump", "2 * pump").replace("in: input", "in: measured")
    s = scored(lambda m, d: [inflow(2.01), DRAIN], text)
    assert s["status"] == "pass" and "input_altered" not in s
