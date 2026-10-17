"""Mechanism tests for the numopt strategies (sdlab/discovery/numopt.py): a whole model's numbers,
and optional effects, co-flows and hidden stocks, fitted by multi-step error with the exact
simulator and a numerical optimiser.

Three of the smallest models where the answer is known exactly (tests/synth.py):
(a) a table effect of a third stock on a move, (b) a hidden stock between two measured ones,
(c) a co-flow (a move that uses up a third stock).
"""

from __future__ import annotations

import numpy as np
from synth import generate, skill

from sdlab.discovery import numopt
from sdlab.discovery.identify import identify
from sdlab.discovery.optimisers import METHODS, minimise
from sdlab.discovery.strategies import load
from sdlab.discovery.terms import output_flows


def effect_model(seed: int = 1, steps: int = 1500) -> dict:
    """a -> b at 0.3 x a x curve(c); c wanders between ~40 and ~170 on its own (an unannounced
    square wave in its inflow)."""
    stocks = [{"id": "a", "initial": 60}, {"id": "b", "initial": 40}, {"id": "c", "initial": 100, "unit": "points"}]
    flows = [
        {"id": "in_a", "from": None, "to": "a", "rate": {"form": "constant", "value": 20}},
        {"id": "ab", "from": "a", "to": "b", "rate": {"form": "proportional", "stock": "a", "k": 0.3},
         "effects": [{"stock": "c", "shape": "table", "points": EFFECT_POINTS}]},
        {"id": "b_out", "from": "b", "to": None, "rate": {"form": "proportional", "stock": "b", "k": 0.2}},
        {"id": "in_c", "from": None, "to": "c", "rate": {"form": "constant", "value": 6}},
        {"id": "c_out", "from": "c", "to": None, "rate": {"form": "proportional", "stock": "c", "k": 0.05}},
    ]
    sch = {"every": 200, "changes": [{"t": 1, "set": {"in_c": {"form": "constant", "value": 2.5}}},
                                     {"t": 101, "set": {"in_c": {"form": "constant", "value": 7.5}}}]}
    return generate(stocks, flows, steps, schedule=sch, seed=seed)


EFFECT_POINTS = [[40, 0.5], [80, 0.7], [120, 0.95], [160, 1.0]]


def hidden_model(seed: int = 1, steps: int = 1500) -> dict:
    """a -> h (unmeasured) -> b: a loses 0.2 a step into h, which releases 0.1 of what it holds."""
    stocks = [{"id": "a", "initial": 50}, {"id": "h", "initial": 100, "measured": False}, {"id": "b", "initial": 40}]
    flows = [
        {"id": "in_a", "from": None, "to": "a", "rate": {"form": "constant", "value": 10}},
        {"id": "ah", "from": "a", "to": "h", "rate": {"form": "proportional", "stock": "a", "k": 0.2}},
        {"id": "hb", "from": "h", "to": "b", "rate": {"form": "proportional", "stock": "h", "k": 0.1}},
        {"id": "b_out", "from": "b", "to": None, "rate": {"form": "proportional", "stock": "b", "k": 0.25}},
    ]
    sch = {"every": 120, "changes": [{"t": 1, "set": {"in_a": {"form": "constant", "value": 4}}},
                                     {"t": 61, "set": {"in_a": {"form": "constant", "value": 16}}}]}
    return generate(stocks, flows, steps, schedule=sch, seed=seed)


def coflow_model(seed: int = 1, steps: int = 1500) -> dict:
    """a -> b at 0.3 x a, using up 0.5 kg of c for each thing moved; c restocked from outside."""
    stocks = [{"id": "a", "initial": 60}, {"id": "b", "initial": 40}, {"id": "c", "initial": 30, "unit": "kg"}]
    flows = [
        {"id": "in_a", "from": None, "to": "a", "rate": {"form": "constant", "value": 20}},
        {"id": "ab", "from": "a", "to": "b", "rate": {"form": "proportional", "stock": "a", "k": 0.3}, "uses": [{"stock": "c", "per": 0.5}]},
        {"id": "b_out", "from": "b", "to": None, "rate": {"form": "proportional", "stock": "b", "k": 0.2}},
        {"id": "in_c", "from": None, "to": "c", "rate": {"form": "constant", "value": 12}},
    ]
    sch = {"every": 200, "changes": [{"t": 1, "set": {"in_c": {"form": "constant", "value": 13}}},
                                     {"t": 101, "set": {"in_c": {"form": "constant", "value": 8}}}]}
    return generate(stocks, flows, steps, schedule=sch, seed=seed)


MODELS = {"effect": effect_model, "hidden": hidden_model, "coflow": coflow_model}


def fit_term(d: dict, term: str, method: str = "fd", budget: int = 60, **opts):
    """identify()'s model, then one optional term fitted (with the rates beside it) by multi-step
    error; returns (configuration, multi-step error before, after, identify()'s result)."""
    r = identify(d["stocks"], d["run"], {"eras": d["eras"]})
    F = numopt._Fitter(d["stocks"], d["run"], r["flows"], method, {**numopt.DEFAULTS, "hidden": True, "inflows": "profile", **opts})
    cfg, x, c0 = F.start()
    tm = {t.name: t for t in F.candidates(cfg)}[term]
    cc = F.config(cfg.terms + (tm,), cfg.values(x))
    x1, c1 = F.fit(cc, cc.x0, cc.index(cc.term_slots(tm)), budget)
    cc.put(x1)
    return cc, c0, c1, r


def curve_error(flow: dict, d: dict) -> float:
    """RMS of the found rate multiplier (k x table) against the truth's (0.3 x curve) over the
    levels of c the data shows, relative to the truth's mean there."""
    c = np.asarray(d["run"]["levels"]["c"], dtype=float)
    x = np.linspace(np.quantile(c, 0.02), np.quantile(c, 0.98), 50)
    pts = np.array(flow["effects"][0]["points"])
    found = flow["rate"]["k"] * np.interp(x, pts[:, 0], pts[:, 1])
    tp = np.array(EFFECT_POINTS)
    truth = 0.3 * np.interp(x, tp[:, 0], tp[:, 1])
    return float(np.sqrt(((found - truth) ** 2).mean()) / truth.mean())


def shape_error(flow: dict, d: dict) -> float:
    """The same, with each curve divided by its own mean over the observed range (shape only)."""
    c = np.asarray(d["run"]["levels"]["c"], dtype=float)
    x = np.linspace(np.quantile(c, 0.02), np.quantile(c, 0.98), 50)
    pts = np.array(flow["effects"][0]["points"])
    found = np.interp(x, pts[:, 0], pts[:, 1])
    tp = np.array(EFFECT_POINTS)
    truth = np.interp(x, tp[:, 0], tp[:, 1])
    return float(np.sqrt(((found / found.mean() - truth / truth.mean()) ** 2).mean()))


def _host(cfg, f_from, f_to):
    return next(f for f in output_flows(cfg) if f.get("from") == f_from and f.get("to") == f_to)


# ---- (a) a table effect of a third stock on a move ----

def test_effect_curve_recovered_when_offered():
    """matrix reads a -> b at 0.3 x a x curve(c) as a plain move plus two links driven by c ("b gains
    with c", "a drains faster when c is high") and fine inflow pieces into a: skill@20 below -8 on
    both seeds. Offered the effect in place of the links (a's inflow re-measured), the multi-step fit
    recovers the curve's shape within 6% on both seeds; with its scale, within 10% on seed 1 (seed 2:
    the rate trades with a's re-measured inflow, ~35% high)."""
    for seed, total in ((1, 0.10), (2, None)):
        d = effect_model(seed=seed)
        cfg, c0, c1, r = fit_term(d, "effect:0:c-3.5")
        assert skill(r, d, 20) < -5                       # matrix
        ab = _host(cfg, "a", "b")
        assert shape_error(ab, d) < 0.06
        if total:
            assert curve_error(ab, d) < total
            assert c1 < c0                                # the data prefers it on seed 1 only


def test_effect_strategy_seed_1():
    d = effect_model(seed=1)
    r = load("numopt_fd_profile")(d["stocks"], d["run"], {"eras": d["eras"]})
    assert "kept + effect:0:c-3.5" in r["chosen"]
    ab = next(f for f in r["flows"] if f.get("from") == "a" and f.get("to") == "b")
    assert curve_error(ab, d) < 0.10
    assert skill(r, d, 20) > 0.8 and skill(r, d, 100) > 0.9


# ---- (b) a hidden stock between two measured ones ----

def test_hidden_stock_delay_recovered():
    """a -> h -> b, h unmeasured (delay 10, a loses 0.2 a step): matrix splits a's drain into a -> b
    (0.064) and a -> outside (0.17). A hidden stock on the move a -> b, fitted with its neighbours
    (a's inflow re-measured), recovers the delay (10.3 / 9.6) and the flow (0.191 / 0.179 of a), and
    cuts the multi-step error 15%. The bench grader cannot start a found hidden stock (its level is
    not in the data), so the strategy gives it back as a direct move with `via`, which behaves worse
    than matrix's: the judge rejects it and numopt keeps hidden stocks off by default."""
    for seed in (1, 2):
        d = hidden_model(seed=seed)
        cfg, c0, c1, r = fit_term(d, "hidden:0:")
        h = cfg.hidden[0]
        assert 8 < h["delay"] < 12.5
        assert 0.16 < h["into"]["rate"]["k"] < 0.22
        assert c1 < 0.9 * c0


# ---- (c) a co-flow ratio ----

def test_coflow_ratio():
    """a -> b uses 0.5 of c per unit moved. matrix reads it as a link "c drains faster when a is
    high", ratio to the move 0.645 (seed 1) / 0.507 (seed 2); seed 1 runs off (skill@20 -0.26).
    The co-flow in place of the link, fitted by multi-step error (c's inflow held: the link and the
    co-flow take the same from it), gives per 0.502 / 0.560: right on seed 1 (skill@20 0.76), worse
    on seed 2. The data cannot tell them apart (error within 0.5%), so the judge keeps matrix's."""
    pers = []
    for seed in (1, 2):
        d = coflow_model(seed=seed)
        cfg, c0, c1, r = fit_term(d, "coflow:0:c-1")
        ab = _host(cfg, "a", "b")
        pers.append(ab["uses"][0]["per"])
        assert abs(c1 - c0) < 0.01 * c0
    assert abs(pers[0] - 0.5) < 0.03
    assert abs(pers[1] - 0.5) < 0.08


# ---- the optimisers ----

def test_every_optimiser_reduces_a_quadratic():
    target = np.array([0.3, 2.0, 0.7])
    for m in METHODS:
        res = minimise(m, lambda x: (x - target) / [0.1, 1, 0.5], np.array([0.1, 1.0, 1.0]), np.zeros(3), np.full(3, 5.0), 150)
        assert res.cost < 0.05 * res.start_cost, m
        assert res.evals <= 150, m
