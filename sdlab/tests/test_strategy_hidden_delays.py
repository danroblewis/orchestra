"""Experiment hidden_delays (docs/DISCOVERY-EXPERIMENTS.md): an unmeasured stock between two measured
ones, found as a delayed copy of the sender's level, on the smallest model that has one.

    a (measured) --0.2 x a--> h (NOT measured) --0.1 x h--> b (measured) --0.25 x b--> out

a is fed from outside at a rate that changes three times. The matrix method has no column for h's
arrivals into b, so it reads them as b's outside inflow in pieces (fitted to this run) and a's loss
as a drain to outside; run from other states with the true inputs, b is wrong. hidden_delays finds
a -> H -> b with H's own estimated level (result["inferred_levels"]).
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pytest
from synth import generate, skill

from sdlab.discovery.hidden import delayed
from sdlab.discovery.simulate import behaviour_error
from sdlab.discovery.strategies import load

_GRADE = Path(__file__).resolve().parent / "bench" / "grade.py"


def _grade():
    spec = importlib.util.spec_from_file_location("bench_grade_hd", _GRADE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def one_hidden(steps=2000, scale=1.0, changes=((400, 35), (900, 10), (1400, 25))):
    return generate(
        stocks=[{"id": "a", "initial": 100 * scale}, {"id": "h", "initial": 200 * scale, "measured": False}, {"id": "b", "initial": 80 * scale}],
        flows=[{"id": "in", "from": None, "to": "a", "rate": {"form": "constant", "value": 20 * scale}},
               {"id": "ah", "from": "a", "to": "h", "rate": {"form": "proportional", "stock": "a", "k": 0.2}},
               {"id": "hb", "from": "h", "to": "b", "rate": {"form": "proportional", "stock": "h", "k": 0.1}},
               {"id": "out", "from": "b", "to": None, "rate": {"form": "proportional", "stock": "b", "k": 0.25}}],
        steps=steps,
        schedule={"every": 0, "changes": [{"t": t, "set": {"in": {"form": "constant", "value": v * scale}}} for t, v in changes]},
    )


@pytest.fixture(scope="module")
def data():
    return one_hidden()


def test_the_delayed_copy_follows_the_recursion():
    x = np.array([10.0, 20.0, 20.0, 0.0])
    z = delayed(x, 0.5)
    assert z.tolist() == [10.0, 10.0, 15.0, 17.5]


def test_hidden_delays_recovers_the_unmeasured_stock(data):
    r = load("hidden_delays")(data["stocks"], data["run"], {"eras": data["eras"]})
    hidden = list(r.get("inferred_levels") or {})
    assert len(hidden) == 1, r["chosen"]
    h = hidden[0]
    into = [f for f in r["flows"] if f["to"] == h]
    out = [f for f in r["flows"] if f["from"] == h]
    assert [(f["from"], f["rate"]["form"]) for f in into] == [("a", "proportional")]
    assert [(f["to"], f["rate"]["form"]) for f in out] == [("b", "proportional")]
    assert into[0]["rate"]["k"] == pytest.approx(0.2, rel=0.1)            # found 0.208
    assert out[0]["rate"]["k"] == pytest.approx(0.1, rel=0.3)             # found 0.1 (delay grid 0.06 / 0.1 / 0.17)
    drain = next(f for f in r["flows"] if f["from"] == "b" and f["to"] is None)
    assert drain["rate"]["k"] == pytest.approx(0.25, rel=0.1)             # found 0.26
    assert not [f for f in r["flows"] if f["to"] == "b" and f["from"] is None]   # no outside inflow into b
    assert len(r["inferred_levels"][h]) == len(data["run"]["t"])
    assert skill(r, data, 20) > 0.9                                         # found 94%
    assert skill(r, data, 100) > 0.95                                       # found 98%


def test_the_matrix_reads_the_arrivals_as_pieces_and_misses(data):
    r = load("matrix")(data["stocks"], data["run"], {"eras": data["eras"]})
    assert any(f["to"] == "b" and f["from"] is None and f.get("inflow") for f in r["flows"])
    assert skill(r, data, 20) < 0.5                                         # found -25%


def test_without_inferred_stocks_the_grader_is_unchanged():
    """The grader's extension (a found model's own unmeasured stocks, started from its own estimate)
    leaves every other result graded exactly as before: values recorded with the grader before the
    extension."""
    d = one_hidden(steps=600, changes=((200, 35), (400, 10)))
    result = {"flows": [
        {"from": None, "to": "a", "rate": {"form": "constant", "value": 22}},
        {"from": "a", "to": "b", "rate": {"form": "proportional", "stock": "a", "k": 0.05}},
        {"from": "a", "to": None, "rate": {"form": "proportional", "stock": "a", "k": 0.15}},
        {"from": "b", "to": None, "rate": {"form": "proportional", "stock": "b", "k": 0.2}},
        {"from": None, "to": "b", "inflow": [{"from": 1, "to": 300, "value": 8}, {"from": 301, "to": 600, "value": 3}], "rate": {"form": "constant", "value": 5.5}},
    ]}
    g = _grade()
    before = {5: -2.264195381369197, 20: -0.6913557009353781, 100: 0.6940302801736358}
    for h, v in before.items():
        assert g.same_behaviour(result, d["model"], d["data"], horizon=h)["skill"] == v
        assert g.same_behaviour({**result, "inferred_levels": {}}, d["model"], d["data"], horizon=h)["skill"] == v


def test_the_grader_runs_a_found_unmeasured_stock_from_its_own_estimate(data):
    """The exact structure, with the found stock named like the truth's hidden one (kept apart) and
    started from its estimate (2 x a delayed by 0.1), never from the truth's level."""
    flows = [{"from": "a", "to": "h", "rate": {"form": "proportional", "stock": "a", "k": 0.2}},
             {"from": "h", "to": "b", "rate": {"form": "proportional", "stock": "h", "k": 0.1}},
             {"from": "b", "to": None, "rate": {"form": "proportional", "stock": "b", "k": 0.25}}]
    estimate = (2 * delayed(np.array(data["run"]["levels"]["a"], dtype=float), 0.1)).tolist()
    with_estimate = {"flows": flows, "inferred_levels": {"h": estimate}}
    assert skill(with_estimate, data, 20) > 0.99
    # a poor estimate is used as given, not the truth's level (before the extension, a found stock
    # named like the truth's hidden one was started from the truth's level: skill 100% here)
    poor = {"flows": flows, "inferred_levels": {"h": [0.0] * len(estimate)}}
    assert skill(poor, data, 20) < 0.5
    # without one, the grader takes the found model's own estimate from the measured levels
    # (observer.py: the grader extension of exp/mass-balance-hidden, which replaced this branch's
    # "start empty" when the two were brought together)
    assert skill({"flows": flows}, data, 20) > 0.9
    parts = _grade().found(with_estimate)
    assert parts["rel"] == {"a>b": "hidden"}


def test_the_judge_without_inferred_stocks_is_unchanged(data):
    flows = [{"from": "a", "to": None, "rate": {"form": "proportional", "stock": "a", "k": 0.2}}]
    ids = [s["id"] for s in data["stocks"]]
    t, lv = data["run"]["t"], data["run"]["levels"]
    assert behaviour_error(flows, ids, t, lv) == behaviour_error(flows, ids, t, lv, inferred={})
