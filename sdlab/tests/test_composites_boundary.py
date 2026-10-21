"""The declared boundary in the composites (combined, combined2, combined_lean, combined_misfit, combined_r2,
archetypes): each carries its own copy of matrix/boundary.py (docs/research/declared-boundary.md) and uses
it in its own searches, its judge and on its answer."""

from __future__ import annotations

import importlib

import numpy as np
import pytest

from sdlab.discovery.strategies import load

COMPOSITES = ["combined", "combined2", "combined_lean", "combined_misfit", "combined_r2", "archetypes"]
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


def _bd(name: str):
    return importlib.import_module(f"sdlab.discovery.strategies.{name}.boundary")


@pytest.mark.parametrize("name", COMPOSITES)
def test_copy_prices_and_guards_as_the_reference(name):
    bd = _bd(name)
    assert bd.HIDDEN_PRICE == 0.0 and bd.CLAIM_PRICE == 2.0
    run = {**_chain(), **DECLARED}
    data = bd.Data(STOCKS, run, {})
    log: list[str] = []
    flows = bd.guard(SPLIT, STOCKS, bd.Boundary(run), data, log)
    assert not bd.violations(flows, ["A", "B"], bd.Boundary(run), set())
    moves = [f for f in flows if f["from"] == "A" and f["to"] == "B"]
    assert len(moves) == 1 and abs(moves[0]["rate"]["k"] - 0.4) < 0.01, flows


@pytest.mark.parametrize("name", COMPOSITES)
def test_guard_budget_drops_without_refit(name):
    bd = _bd(name)
    run = {**_chain(), **DECLARED}
    data = bd.Data(STOCKS, run, {})
    data.guard_fits = 0                       # the budget spent: nothing outside the boundary is kept, nothing refitted
    flows = bd.guard(SPLIT, STOCKS, bd.Boundary(run), data, [])
    assert not bd.violations(flows, ["A", "B"], bd.Boundary(run), set()) and data.fits == 0


@pytest.mark.parametrize("name", COMPOSITES)
def test_lna_atoms_only_on_declared_sides(name):
    bd = _bd(name)
    Atom = importlib.import_module(f"sdlab.discovery.strategies.{name}._vendored.lna.atoms").Atom
    allow = bd.atom_rule(DECLARED, ["A", "B"], 1)        # one measured input, row 2
    assert allow(Atom("in", dst=0)) and not allow(Atom("in", dst=1))
    assert not allow(Atom("out", src=0, driver=0)) and allow(Atom("out", src=1, driver=1))
    assert allow(Atom("move", src=0, dst=1, driver=0))
    assert not allow(Atom("link", dst=0, driver=2))          # A's inflow is "estimate", not "measured"
    assert bd.atom_rule({}, ["A", "B"], 1) is None           # nothing declared: every atom offered


@pytest.mark.parametrize("name", COMPOSITES)
def test_claim_price_only_without_a_boundary(name):
    bd = _bd(name)
    assert bd.claim_price(SPLIT, ["A", "B"], DECLARED, 5.0) == 0.0
    assert bd.claim_price(SPLIT, ["A", "B"], {}, 5.0) == pytest.approx(4 * 0.5 * 2.0 * 5.0)


@pytest.mark.parametrize("pkg", ["archetypes", "combined2._vendored.archetypes"])
def test_archetypes_search_inside_the_boundary(pkg):
    arch = importlib.import_module(f"sdlab.discovery.strategies.{pkg}")
    run = {**_chain(T=40), **DECLARED}
    r = arch.discover(STOCKS, run, {}, {**arch.DEFAULTS, "seconds": 10.0, "hidden": False})
    bd = _bd(pkg.split(".")[0])
    assert r and not bd.violations(r["flows"], ["A", "B"], bd.Boundary(run), set()), r and r["flows"]


def test_structures_search_inside_the_boundary():
    from sdlab.discovery.strategies.combined2._vendored.structures.discover import discover

    bd = _bd("combined2")
    run = {**_chain(), **DECLARED}
    r = discover(STOCKS, run, {}, seconds=20.0, chains=False, products=False)
    assert r and not bd.violations(r["flows"], ["A", "B"], bd.Boundary(run), set()), r and r["terms"]


@pytest.mark.parametrize("name", COMPOSITES)
def test_strategy_stays_inside_the_boundary(name):
    run = {**_chain(), **DECLARED}
    r = load(name)(STOCKS, run, {})
    bd = _bd(name)
    assert not bd.violations(r["flows"], ["A", "B"], bd.Boundary(DECLARED), set()), r["flows"]
    assert r["boundary"]["declared"] and r["boundary_claims"] == []
