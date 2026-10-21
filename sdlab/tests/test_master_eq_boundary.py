"""master_eq inside the declared boundary (master_eq/boundary.py, a copy of matrix's at 723f72c; the term pool
filtered by terms.inside, claims priced in ml.bic)."""

from __future__ import annotations

import numpy as np

from sdlab.discovery.strategies import load
from sdlab.discovery.strategies.master_eq import boundary as bd
from sdlab.discovery.strategies.master_eq import terms as T

STOCKS = [{"id": "A", "unit": "x"}, {"id": "B", "unit": "x"}]
DECLARED = {"boundary": {"A": {"in": ["estimate"], "out": []}, "B": {"in": [], "out": ["estimate"]}}, "boundary_declared": True}


def _counted(T_: int = 600, seed: int = 0) -> dict:
    """Counted units: outside -> A Poisson(6), A -> B binomial(0.1), B -> outside binomial(0.05)."""
    rng = np.random.default_rng(seed)
    a, b, A, B = 60, 100, [60], [100]
    for _ in range(T_):
        ab, bo = rng.binomial(a, 0.1), rng.binomial(b, 0.05)
        a, b = a - ab + rng.poisson(6), b + ab - bo
        A.append(a)
        B.append(b)
    return {"t": list(range(T_ + 1)), "levels": {"A": A, "B": B}}


def test_pool_holds_only_declared_outside_terms():
    pool = T.inside(T.conservative(2, 1, ["x", "x"]) + T.extras(2, ["x", "x"], True), bd.Boundary(DECLARED), ["A", "B"])
    sides = {(s, side, kind) for t in pool for s, side, kind in T.outside_sides(t)}
    assert sides <= {(0, "in", "estimate"), (0, "in", "measured"), (1, "out", "estimate")}   # an estimate side may read inputs
    assert {(0, "in", "estimate"), (1, "out", "estimate")} <= sides
    assert any(t.kind == "move" and (t.src, t.dst) == (0, 1) for t in pool)
    every = T.conservative(2, 1, ["x", "x"])
    assert T.inside(every, bd.Boundary({}), ["A", "B"]) == every


def test_master_eq_stays_inside_the_boundary():
    run = _counted()
    r = load("master_eq")(STOCKS, {**run, **DECLARED}, {})
    assert not bd.violations(r["flows"], ["A", "B"], bd.Boundary(DECLARED), set()), r["flows"]
    assert any(f["from"] == "A" and f["to"] == "B" for f in r["flows"])
    assert r["boundary"]["declared"] and r["boundary_claims"] == []
    # a declared side's flow exists (boundary.kept_sides, this copy): the declared inflow and drain are
    # not made a closed loop B -> A, which fits these counts nearly as well for one number fewer
    assert {(f["from"], f["to"]) for f in r["flows"]} == {("A", "B"), (None, "A"), ("B", None)}, r["flows"]
    r = load("master_eq")(STOCKS, run, {})
    assert not r["boundary"]["declared"]
    assert r["boundary_claims"] == bd.claims(r["flows"], ["A", "B"], bd.Boundary({}), set())
