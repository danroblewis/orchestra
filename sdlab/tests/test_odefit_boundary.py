"""odefit inside the declared boundary (odefit/boundary.py, a copy of matrix's at 723f72c; odefit/inside.py)."""

from __future__ import annotations

import numpy as np

from sdlab.discovery.strategies import load
from sdlab.discovery.strategies.odefit import boundary as bd
from sdlab.discovery.strategies.odefit import fit as F
from sdlab.discovery.strategies.odefit.inside import Region

STOCKS = [{"id": "A", "unit": "x"}, {"id": "B", "unit": "x"}]
DECLARED = {"boundary": {"A": {"in": ["estimate"], "out": []}, "B": {"in": [], "out": ["estimate"]}}, "boundary_declared": True}


def _chain(T: int = 300, seed: int = 0, meas: float = 0.0) -> dict:
    """outside -> A = 20, A -> B = 0.4 A, B -> outside = 0.2 B, small noise on the changes (and on the levels)."""
    rng = np.random.default_rng(seed)
    A, B = [10.0], [5.0]
    for _ in range(T):
        a, b = A[-1], B[-1]
        A.append(a + 20 - 0.4 * a + rng.normal(0, 0.3))
        B.append(b + 0.4 * a - 0.2 * b + rng.normal(0, 0.3))
    A = list(np.array(A) + rng.normal(0, meas, T + 1))
    B = list(np.array(B) + rng.normal(0, meas, T + 1))
    return {"t": list(range(T + 1)), "levels": {"A": A, "B": B}}


def test_region_masks_undeclared_columns_and_ties_sources():
    reg = Region(bd.Boundary(DECLARED), STOCKS)
    sp = F.Spec(2, 1, region=reg)                     # columns: A, B, input u, constant
    assert reg.ties == {0: [1]}                        # A has no outflow to outside: its drain is all moves
    assert sp.mask.tolist() == [[False, True, True, True], [True, True, True, True]]   # estimate sides may read u (728efec)
    W = sp.unpack(np.array([0.0, 0.0, 20.0, 0.4, -0.2, 0.0, 0.0]))[0]   # (A,B) (A,u) (A,1) (B,A) (B,B) (B,u) (B,1)
    assert W[0, 0] == -0.4                             # A's own number: minus what B gains from it
    open_ = F.Spec(2, 1, region=Region(bd.Boundary({}), STOCKS))
    assert open_.mask.all() and not open_.ties


def test_odefit_stays_inside_the_boundary_and_lists_claims():
    for meas in (0.0, 0.5):
        run = _chain(meas=meas)
        r = load("odefit")(STOCKS, {**run, **DECLARED}, {})
        assert not bd.violations(r["flows"], ["A", "B"], bd.Boundary(DECLARED), set()), r["flows"]
        assert any(f["from"] == "A" and f["to"] == "B" for f in r["flows"])
        assert r["boundary"]["declared"] and r["boundary_claims"] == []
    r = load("odefit")(STOCKS, _chain(), {})
    assert not r["boundary"]["declared"] and r["boundary_claims"]
