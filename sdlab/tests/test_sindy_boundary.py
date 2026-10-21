"""sindy inside the declared boundary (sindy/boundary.py, a copy of matrix's at 723f72c; rows fitted inside it)."""

from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("pysindy", reason="optional: uv sync --extra research")

from sdlab.discovery.strategies import load  # noqa: E402
from sdlab.discovery.strategies.sindy import boundary as bd  # noqa: E402

STOCKS = [{"id": "A", "unit": "x"}, {"id": "B", "unit": "x"}]
DECLARED = {"boundary": {"A": {"in": ["estimate"], "out": []}, "B": {"in": [], "out": ["estimate"]}}, "boundary_declared": True}


def _chain(T: int = 300, seed: int = 0, meas: float = 0.0) -> dict:
    rng = np.random.default_rng(seed)
    A, B = [10.0], [5.0]
    for _ in range(T):
        a, b = A[-1], B[-1]
        A.append(a + 20 - 0.4 * a + rng.normal(0, 0.3))
        B.append(b + 0.4 * a - 0.2 * b + rng.normal(0, 0.3))
    return {"t": list(range(T + 1)), "levels": {"A": list(np.array(A) + rng.normal(0, meas, T + 1)), "B": list(np.array(B) + rng.normal(0, meas, T + 1))}}


def test_sindy_stays_inside_the_boundary():
    for meas in (0.0, 0.5):
        r = load("sindy")(STOCKS, {**_chain(meas=meas), **DECLARED}, {})
        assert not bd.violations(r["flows"], ["A", "B"], bd.Boundary(DECLARED), set()), r["flows"]
        assert r["boundary"]["declared"] and r["boundary_claims"] == []
    r = load("sindy")(STOCKS, _chain(), {})
    assert r["boundary_claims"] == bd.claims(r["flows"], ["A", "B"], bd.Boundary({}), set())
