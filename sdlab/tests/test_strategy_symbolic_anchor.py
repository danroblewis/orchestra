"""Mechanism test for experiment symbolic-addition-judge (strategy "symbolic_anchor",
docs/research/symbolic-addition-judge.md): symbolic effects accepted only when the model with them
predicts better than the model without them, both fed outside inflows the effects did not tailor.

  - a true effect (backlog -> done at k x backlog x table(skill)): the model with the effect, both
    models given a coarse outside inflow re-measured under their own dynamics (and with its own pieces
    against the base with the base's), beats the main line's
    model by more than the judge's noise: accepted, and it behaves much better than the main line's;
  - a spurious curve (a chain whose stage rates change at announced eras, no effect in the truth: the
    levels shift with the eras, so a curve of a level imitates the rate change): plain "symbolic"
    takes it (its judge runs each candidate with its own inflow pieces) and loses skill; the addition
    test finds no gain and keeps the main line's model;
  - fed the base model's own inflow pieces ("anchor", the hypothesis as first stated) even the true
    effect loses: the base's pieces already imitate it, and the effect counts it twice.
"""

from __future__ import annotations

import pytest
from synth import generate, skill
from test_strategy_symbolic import CASES, _model

from sdlab.discovery.addition import addition_test
from sdlab.discovery.strategies import load


def chain(seed: int = 1) -> dict:
    p = lambda s, k: {"form": "proportional", "stock": s, "k": k}  # noqa: E731
    stocks = [{"id": "in", "initial": 40}, {"id": "mid", "initial": 20}, {"id": "out", "initial": 30}]
    flows = [
        {"id": "arrive", "from": None, "to": "in", "rate": {"form": "constant", "value": 12}},
        {"id": "s1", "from": "in", "to": "mid", "rate": p("in", 0.3)},
        {"id": "s2", "from": "mid", "to": "out", "rate": p("mid", 0.4)},
        {"id": "s3", "from": "out", "to": None, "rate": p("out", 0.2)},
    ]
    ch = [{"t": 1, "label": "a", "set": {"s1": p("in", 0.3), "arrive": {"form": "constant", "value": 12}}, "announce": True},
          {"t": 121, "label": "b", "set": {"s1": p("in", 0.55)}, "announce": True},
          {"t": 251, "label": "c", "set": {"s2": p("mid", 0.2)}, "announce": True},
          {"t": 331, "label": "d", "set": {"s2": p("mid", 0.4)}, "announce": True},
          {"t": 401, "set": {"arrive": {"form": "constant", "value": 16}}}]
    return generate(stocks, flows, 2000, schedule={"every": 500, "changes": ch}, seed=seed)


@pytest.fixture(scope="module")
def effect():
    d = _model(**CASES["saturating"])
    o = {"eras": d["eras"]}
    return d, load("matrix")(d["stocks"], d["run"], o), load("symbolic_anchor")(d["stocks"], d["run"], o)


def test_a_true_effect_is_accepted(effect):
    d, base, r = effect
    assert r["chosen"].startswith("effects"), r["additions"]
    a = r["additions"][0]
    assert a["accept"] and a["gain"] > 2 * a["noise"], a
    assert any(e["stock"] == "skill" for f in r["flows"] for e in f.get("effects") or [])
    # 50% against the main line's -95%
    assert skill(r, d) > skill(base, d) + 0.5


def test_the_base_models_own_pieces_count_a_true_effect_twice(effect):
    d, base, r = effect
    t = addition_test(base["flows"], r["flows"], d["stocks"], d["run"], inflow="anchor")
    assert not t["accept"] and t["gain"] < 0, t


@pytest.mark.parametrize("seed", [1, 3])
def test_a_spurious_curve_is_refused(seed):
    d = chain(seed)
    o = {"eras": d["eras"]}
    base = load("matrix")(d["stocks"], d["run"], o)
    plain = load("symbolic")(d["stocks"], d["run"], o)
    r = load("symbolic_anchor")(d["stocks"], d["run"], o)
    # plain symbolic takes a curve the truth does not have, and behaves worse for it (0.88 -> 0.42, 0.99 -> 0.34)
    assert plain["chosen"].startswith("effects")
    assert skill(plain, d) < skill(base, d) - 0.2
    # the addition test sees no gain beyond its noise: the main line's model is kept
    assert r["additions"] and not any(a["accept"] for a in r["additions"]), r["additions"]
    assert r["flows"] == base["flows"]
