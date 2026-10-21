"""The declared boundary in six strategies that carry a copy of matrix/boundary.py (at 723f72c;
docs/research/declared-boundary.md, "For copiers"): structures, blockwise, censored, earned_pieces,
gap_prior, schedules. Each stays inside a declared boundary, lists its claims where none is declared,
and its copy prices a hidden stock at nothing beyond its numbers (HIDDEN_PRICE 0)."""

from __future__ import annotations

import importlib

import numpy as np
import pytest

from sdlab.discovery.strategies import load

COPIES = ["earned_pieces", "blockwise", "censored", "schedules", "gap_prior", "structures"]
STOCKS = [{"id": "A", "unit": "x"}, {"id": "B", "unit": "x"}]
DECLARED = {"boundary": {"A": {"in": ["estimate"], "out": []}, "B": {"in": [], "out": ["estimate"]}}, "boundary_declared": True}


def _chain(T: int = 300, seed: int = 0) -> dict:
    """outside -> A = 20, A -> B = 0.4 A, B -> outside = 0.2 B, with small noise on the changes."""
    rng = np.random.default_rng(seed)
    A, B = [10.0], [5.0]
    for _ in range(T):
        a, b = A[-1], B[-1]
        A.append(a + 20 - 0.4 * a + rng.normal(0, 0.3))
        B.append(b + 0.4 * a - 0.2 * b + rng.normal(0, 0.3))
    return {"t": list(range(T + 1)), "levels": {"A": A, "B": B}}


def _bd(name: str):
    return importlib.import_module(f"sdlab.discovery.strategies.{name}.boundary")


@pytest.mark.parametrize("name", COPIES)
def test_copy_prices_hidden_stocks_at_their_numbers(name):
    bd = _bd(name)
    assert bd.HIDDEN_PRICE == 0.0 and bd.CLAIM_PRICE == 2.0


@pytest.mark.parametrize("name", COPIES)
def test_strategy_stays_inside_the_declared_boundary(name):
    run = _chain()
    bd = _bd(name)
    r = load(name)(STOCKS, {**run, **DECLARED}, {})
    assert r["flows"], r
    assert not bd.violations(r["flows"], ["A", "B"], bd.Boundary(DECLARED), set()), r["flows"]
    assert r["boundary"]["declared"] and r["boundary_claims"] == []
    assert any(f.get("from") == "A" and f.get("to") == "B" for f in r["flows"]), r["flows"]


@pytest.mark.parametrize("name", COPIES)
def test_strategy_lists_claims_without_a_boundary(name):
    r = load(name)(STOCKS, _chain(), {})
    assert not r["boundary"]["declared"] and r["boundary_claims"]


@pytest.mark.parametrize("name", COPIES)
def test_kinds_are_read_as_the_cases_declare_them(name):
    """docs/LADDER.md "Declared": "measured" only for an outside inflow reading only measured inputs;
    every other outside flow (an outflow reading an input, an inflow also reading a stock) is
    "estimate", and an estimate side may read inputs (208: H -> outside = demand, declared estimate)."""
    bd = _bd(name)
    lin = lambda *ts, c=0: {"form": "linear", "c": c, "terms": [{"stock": s, "k": 1.0} for s in ts]}  # noqa: E731
    out_demand = {"from": "H", "to": None, "rate": lin("demand"), "input": "demand"}
    valve = {"from": None, "to": "H", "rate": lin("H", "demand", c=75)}
    feed = {"from": None, "to": "H", "rate": lin("demand"), "input": "demand"}
    assert bd.kind_of(out_demand, {"demand"}) == "estimate" and bd.kind_of(valve, {"demand"}) == "estimate"
    assert bd.kind_of(feed, {"demand"}) == "measured"
    est = bd.Boundary({"boundary": {"H": {"in": ["estimate"], "out": ["estimate"]}}, "boundary_declared": True})
    assert est.inputs_ok("H") and not bd.violations([out_demand, valve, feed], ["H"], est, {"demand"})
    meas = bd.Boundary({"boundary": {"H": {"in": ["measured"], "out": []}}, "boundary_declared": True})
    assert bd.violations([out_demand, valve, feed], ["H"], meas, {"demand"}) == [0, 1]
