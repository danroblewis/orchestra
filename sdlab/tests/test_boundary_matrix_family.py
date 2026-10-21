"""The declared boundary in matrix_v2, held_out, recession, starved_coflows and periodic_inflows, each
carrying its own copy of matrix/boundary.py (at 723f72c; docs/research/declared-boundary.md, "For
copiers") wired into its own search: each stays inside a declared boundary (the split A -> outside,
outside -> B is never offered), lists its claims where none is declared, and its copy prices a hidden
stock at nothing beyond its numbers (HIDDEN_PRICE 0)."""

from __future__ import annotations

import importlib

import numpy as np
import pytest

from sdlab.discovery.strategies import load

COPIES = ["matrix_v2", "held_out", "recession", "starved_coflows", "periodic_inflows"]
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
    bd = _bd(name)
    r = load(name)(STOCKS, {**_chain(), **DECLARED}, {})
    assert r["flows"], r
    assert not bd.violations(r["flows"], ["A", "B"], bd.Boundary(DECLARED), set()), r["flows"]
    assert r["boundary"]["declared"] and r["boundary_claims"] == []
    assert any(f.get("from") == "A" and f.get("to") == "B" for f in r["flows"]), r["flows"]


@pytest.mark.parametrize("name", COPIES)
def test_strategy_lists_claims_without_a_boundary(name):
    r = load(name)(STOCKS, _chain(), {})
    assert not r["boundary"]["declared"] and r["boundary_claims"]


@pytest.mark.parametrize("name", ["matrix_v2", "held_out", "recession", "starved_coflows", "periodic_inflows"])
def test_rows_are_fitted_inside_the_boundary(name):
    """The search itself (not only the final guard): with nothing outside declared on B, no candidate
    the judge saw had B -> outside (each row refitted inside, the source tied; then guarded)."""
    closed = {"boundary": {"A": {"in": ["estimate"], "out": []}}, "boundary_declared": True}
    bd = _bd(name)
    rng = np.random.default_rng(1)
    A, B = [10.0], [5.0]
    for _ in range(300):
        a, b = A[-1], B[-1]
        A.append(a + 20 - 0.4 * a + 0.1 * b + rng.normal(0, 0.3))
        B.append(b + 0.4 * a - 0.1 * b + rng.normal(0, 0.3))
    r = load(name)(STOCKS, {"t": list(range(301)), "levels": {"A": A, "B": B}, **closed}, {})
    assert not bd.violations(r["flows"], ["A", "B"], bd.Boundary(closed), set()), r["flows"]


def test_matrix_v2_rows_hold_no_outside_term_where_none_is_declared():
    from sdlab.discovery.strategies.matrix_v2.matrix import identify_one

    r = identify_one(STOCKS, {**_chain(), "boundary": {"A": {"in": ["estimate"], "out": []}}, "boundary_declared": True},
                     {"keep_fit": True, "rss_floor": True})
    rows = {row["id"]: row for row in r["fit"]["rows"]}
    assert not rows["B"]["cuts"] and rows["A"]["cuts"]


def test_held_out_fold_guard_sees_only_its_steps():
    from sdlab.discovery.strategies.held_out import _seen

    run = _chain(50)
    steps = np.ones(50, bool)
    steps[10:20] = False
    seen = _seen(run, steps)
    a = np.asarray(seen["levels"]["A"])
    assert np.isnan(a[11:21]).all() and np.isfinite(a[:11]).all() and np.isfinite(a[21:]).all()
