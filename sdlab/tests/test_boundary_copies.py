"""The declared boundary in the strategies that carry a copy of matrix/boundary.py (723f72c):
effect_hats, inflow_effects, coflow_hats, realistic_flows, realistic_hats, own_tables
(docs/research/declared-boundary.md)."""

from __future__ import annotations

import importlib

import numpy as np
import pytest

from sdlab.discovery.strategies import load

NAMES = ["effect_hats", "inflow_effects", "coflow_hats", "realistic_flows", "realistic_hats", "own_tables"]
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


def _flow(a, b, rate, **kw):
    return {"from": a, "to": b, "ratio": 1, "rate": rate, "rates": [rate], **kw}


SPLIT = [_flow(None, "A", {"form": "constant", "value": 20.0}),
         _flow("A", None, {"form": "proportional", "stock": "A", "k": 0.4}),
         _flow(None, "B", {"form": "linear", "c": 0, "terms": [{"stock": "A", "k": 0.4}]}, driver="A"),
         _flow("B", None, {"form": "proportional", "stock": "B", "k": 0.2})]


@pytest.mark.parametrize("name", NAMES)
def test_copy_is_the_reference_with_hidden_price_zero(name):
    bd = importlib.import_module(f"sdlab.discovery.strategies.{name}.boundary")
    assert bd.HIDDEN_PRICE == 0.0 and bd.CLAIM_PRICE == 2.0 and bd.GUARD_FITS > 0


@pytest.mark.parametrize("name", NAMES)
def test_keep_inside_makes_the_split_a_move(name):
    bd = importlib.import_module(f"sdlab.discovery.strategies.{name}.boundary")
    run = {**_chain(), **DECLARED}
    assert not bd.inside(SPLIT, STOCKS, run) and bd.inside(SPLIT, STOCKS, _chain())
    flows = bd.keep_inside(SPLIT, STOCKS, run)
    assert bd.inside(flows, STOCKS, run)
    assert any(f["from"] == "A" and f["to"] == "B" for f in flows), flows


@pytest.mark.parametrize("name", NAMES)
def test_placements_only_on_declared_sides(name):
    bd = importlib.import_module(f"sdlab.discovery.strategies.{name}.boundary")
    b = bd.Boundary(DECLARED)
    assert bd.placement_ok(b, None, "A") and not bd.placement_ok(b, "A", None)
    assert bd.placement_ok(b, "B", None) and not bd.placement_ok(b, None, "B") and bd.placement_ok(b, "A", "B")
    assert bd.placement_ok(bd.Boundary({}), "A", None)


@pytest.mark.parametrize("name", NAMES)
def test_strategy_stays_inside_the_boundary_and_lists_claims(name):
    bd = importlib.import_module(f"sdlab.discovery.strategies.{name}.boundary")
    run = _chain()
    r = load(name)(STOCKS, {**run, **DECLARED}, {})
    assert bd.inside(r["flows"], STOCKS, {**run, **DECLARED})
    assert r["boundary"]["declared"] and r["boundary_claims"] == []
    r = load(name)(STOCKS, run, {})
    assert not r["boundary"]["declared"] and r["boundary_claims"]


@pytest.mark.parametrize("name", NAMES)
def test_an_estimated_side_may_read_a_measured_input(name):
    # (these copies) the cases declare "estimate" for any outside flow not driven by inputs alone (217's
    # arrivals x a table of Q), so a flow reading an input is allowed there; a "measured" side still
    # takes no estimated form
    bd = importlib.import_module(f"sdlab.discovery.strategies.{name}.boundary")
    reads = [_flow(None, "A", {"form": "linear", "c": 0, "terms": [{"stock": "u", "k": 1.0}]}, input="u")]
    assert bd.violations(reads, ["A", "B"], bd.Boundary(DECLARED), {"u"}) == []
    assert bd.Boundary(DECLARED).inputs_ok("A")
    measured_only = {"boundary": {"A": {"in": ["measured"], "out": []}}, "boundary_declared": True}
    const = [_flow(None, "A", {"form": "constant", "value": 1.0})]
    assert bd.violations(const, ["A", "B"], bd.Boundary(measured_only), {"u"}) == [0]
