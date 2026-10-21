"""The numopt strategies' declared-boundary search (each package's boundary.py, a copy of
matrix/boundary.py at 723f72c; docs/research/declared-boundary.md)."""

from __future__ import annotations

import importlib
import importlib.util

import numpy as np
import pytest

from sdlab.discovery.strategies import load

STRATEGIES = ["numopt_bo", "numopt_cma", "numopt_nm", "numopt_powell"]
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


def _skip_missing(name: str) -> None:
    if name == "numopt_cma" and importlib.util.find_spec("cma") is None:
        pytest.skip("cma not installed (uv sync --extra research)")


@pytest.mark.parametrize("name", STRATEGIES)
def test_the_copy_prices_hidden_stocks_at_their_numbers_only(name):
    bd = importlib.import_module(f"sdlab.discovery.strategies.{name}.boundary")
    assert bd.HIDDEN_PRICE == 0.0 and bd.CLAIM_PRICE == 2.0


@pytest.mark.parametrize("name", STRATEGIES)
def test_numopt_stays_inside_the_boundary_and_lists_claims(name):
    _skip_missing(name)
    bd = importlib.import_module(f"sdlab.discovery.strategies.{name}.boundary")
    run = _chain()
    r = load(name)(STOCKS, {**run, **DECLARED}, {})
    assert not bd.violations(r["flows"], ["A", "B"], bd.Boundary(DECLARED), set()), r["flows"]
    assert any(f.get("from") == "A" and f.get("to") == "B" for f in r["flows"]), r["flows"]
    assert r["boundary"]["declared"] and r["boundary_claims"] == []
    r = load(name)(STOCKS, run, {})
    assert not r["boundary"]["declared"] and r["boundary_claims"]
