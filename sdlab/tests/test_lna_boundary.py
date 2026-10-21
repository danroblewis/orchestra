"""The lna family's declared boundary (each strategy's own copy of matrix/boundary.py at 723f72c, in
lna/boundary.py and the lna_* strategies' _vendored/lna/boundary.py; docs/research/declared-boundary.md)."""

from __future__ import annotations

import numpy as np
import pytest

from sdlab.discovery.strategies import load
from sdlab.discovery.strategies.lna import boundary as bd
from sdlab.discovery.strategies.lna.atoms import Atom
from sdlab.discovery.strategies.lna.fit import Data, fit

FAMILY = ["lna", "lna_levels", "lna_loops", "lna_products", "lna_pulses", "lna_stack"]
STOCKS = [{"id": "A", "unit": "x"}, {"id": "B", "unit": "x"}]
DECLARED = {"boundary": {"A": {"in": ["estimate"], "out": []}, "B": {"in": [], "out": ["estimate"]}}, "boundary_declared": True}
# a boundary the data does not fit (B's outflow declared on A): the answer must still keep inside it
WRONG = {"boundary": {"A": {"in": ["estimate"], "out": ["estimate"]}, "B": {"in": [], "out": []}}, "boundary_declared": True}


def _counts(T: int = 400, seed: int = 0) -> dict:
    """outside -> A ~ Poisson(10), A -> B ~ Poisson(0.2 A), B -> outside ~ Poisson(0.1 B)."""
    rng = np.random.default_rng(seed)
    A, B = [50.0], [100.0]
    for _ in range(T):
        a, b = A[-1], B[-1]
        mv, bi, de = rng.poisson(0.2 * a), rng.poisson(10), rng.poisson(0.1 * b)
        A.append(a + bi - mv)
        B.append(b + mv - de)
    return {"t": list(range(T + 1)), "levels": {"A": A, "B": B}}


def test_atoms_inside_the_declared_boundary():
    test = bd.inside(bd.Boundary(DECLARED), ["A", "B"], n_inputs=1)
    assert test(Atom("in", dst=0)) and test(Atom("move", src=0, dst=1, driver=0)) and test(Atom("out", src=1, driver=1))
    assert not test(Atom("in", dst=1)) and not test(Atom("out", src=0, driver=0)) and not test(Atom("gap", dst=1, driver=0))
    assert not test(Atom("link", dst=0, driver=2))          # row 2 is the measured input: A's inflow is declared "estimate"
    assert test(Atom("link", dst=0, driver=1)) and test(Atom("link", dst=0, driver=7))   # a stock's or a stage's virtual row
    assert not test(Atom("drain", src=1, driver=2)) and not test(Atom("grow", dst=1, driver=1))
    assert bd.inside(bd.Boundary({}), ["A", "B"], 1) is None   # nothing declared: lna's search unchanged


def test_fit_holds_an_atom_outside_the_boundary_at_zero():
    run = _counts()
    lv = np.array([run["levels"]["A"], run["levels"]["B"]])
    d = Data(lv[:, :-1], np.diff(lv, axis=1), None)
    atoms = [Atom("in", dst=0), Atom("move", src=0, dst=1, driver=0), Atom("out", src=1, driver=1), Atom("in", dst=1)]
    free = fit(atoms, d)
    d.inside = bd.inside(bd.Boundary(DECLARED), ["A", "B"], 0)
    held = fit(atoms, d)
    assert held.theta[3] == 0 and held.theta[0] > 0 and held.theta[1] > 0 and held.theta[2] > 0
    assert free.nll <= held.nll + 1e-6


@pytest.mark.parametrize("name", FAMILY)
def test_family_stays_inside_the_boundary_and_lists_claims(name):
    run = _counts()
    for declared in (DECLARED, WRONG):
        r = load(name)(STOCKS, {**run, **declared}, {})
        assert not bd.violations(r["flows"], ["A", "B"], bd.Boundary(declared), set()), (declared, r["flows"])
        assert r["boundary"]["declared"] and r["boundary_claims"] == []
    r = load(name)(STOCKS, run, {})
    assert not r["boundary"]["declared"] and {(c["stock"], c["side"]) for c in r["boundary_claims"]} == {("A", "in"), ("B", "out")}
    assert any(f["from"] == "A" and f["to"] == "B" for f in r["flows"])
