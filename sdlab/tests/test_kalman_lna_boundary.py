"""kalman_lna inside the declared boundary (kalman_lna/boundary.py, a copy of matrix's at 723f72c; the
filter's and the vendored lna's atoms filtered by inside.Allow; the vendored combined judges guarded candidates)."""

from __future__ import annotations

import numpy as np

from sdlab.discovery.strategies import load
from sdlab.discovery.strategies.kalman_lna import boundary as bd
from sdlab.discovery.strategies.kalman_lna._vendored.lna.atoms import Atom, superset
from sdlab.discovery.strategies.kalman_lna.inside import Allow

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


def test_atoms_offered_only_on_declared_sides():
    allow = Allow(bd.Boundary(DECLARED), ["A", "B"], inputs={2})
    kept = allow.keep(superset(2, ["x", "x"], set(), [None, None]))
    assert {a.kind for a in kept if a.dst == 0 and a.src is None} == {"in", "grow", "link", "gap"}   # A: estimated inflows
    assert not any(a.kind in ("out", "drain") and a.src == 0 for a in kept)                   # A has no outflow
    assert not any(a.src is None and a.dst == 1 for a in kept)                                 # B has no inflow
    assert any(a.kind == "move" for a in kept)
    assert not allow(Atom("link", dst=0, driver=2))          # an input-driven inflow is "measured": not declared on A
    assert Allow(bd.Boundary({}), ["A", "B"]).keep(kept) == kept


def test_kalman_lna_stays_inside_the_boundary():
    r = load("kalman_lna")(STOCKS, {**_chain(), **DECLARED}, {})
    assert not bd.violations(r["flows"], ["A", "B"], bd.Boundary(DECLARED), set()), r["flows"]
    assert r["boundary"]["declared"] and r["boundary_claims"] == []
    r = load("kalman_lna")(STOCKS, _chain(), {})
    assert not r["boundary"]["declared"]
    assert r["boundary_claims"] == bd.claims(r["flows"], ["A", "B"], bd.Boundary({}), set())
