"""common_cause inside the declared boundary (common_cause/boundary.py, a copy of matrix's at 723f72c; rows,
shared places and ties searched inside it, refit.py)."""

from __future__ import annotations

import numpy as np

from sdlab.discovery.strategies import load
from sdlab.discovery.strategies.common_cause import boundary as bd

STOCKS = [{"id": "A", "unit": "x"}, {"id": "B", "unit": "x"}]
DECLARED = {"boundary": {"A": {"in": ["estimate"], "out": []}, "B": {"in": [], "out": ["estimate"]}}, "boundary_declared": True}


def _chain(T: int = 300, seed: int = 0) -> dict:
    rng = np.random.default_rng(seed)
    A, B = [10.0], [5.0]
    for _ in range(T):
        a, b = A[-1], B[-1]
        A.append(a + 20 - 0.4 * a + rng.normal(0, 0.3))
        B.append(b + 0.4 * a - 0.2 * b + rng.normal(0, 0.3))
    return {"t": list(range(T + 1)), "levels": {"A": A, "B": B}}


def test_common_cause_stays_inside_the_boundary():
    r = load("common_cause")(STOCKS, {**_chain(), **DECLARED}, {})
    assert not bd.violations(r["flows"], ["A", "B"], bd.Boundary(DECLARED), set()), r["flows"]
    assert {(f["from"], f["to"]) for f in r["flows"]} == {("A", "B"), (None, "A"), ("B", None)}
    assert r["boundary"]["declared"] and r["boundary_claims"] == []
    r = load("common_cause")(STOCKS, _chain(), {})
    assert not r["boundary"]["declared"]
    assert r["boundary_claims"] == bd.claims(r["flows"], ["A", "B"], bd.Boundary({}), set())
