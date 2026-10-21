"""The declared boundary in six strategies that carry a copy of matrix/boundary.py (at 723f72c;
docs/research/declared-boundary.md, "For copiers"): hidden_transit, loop_transit, latent_eras,
drifting_drain, mass_balance, shared_noise. Each stays inside a declared boundary, lists its claims
where none is declared, its copy prices a hidden stock at nothing beyond its numbers (HIDDEN_PRICE 0)
and bounds the guard's refits (GUARD_FITS); the strategies' own searches propose outside flows only on
declared sides."""

from __future__ import annotations

import importlib

import numpy as np
import pytest

from sdlab.discovery.strategies import load

COPIES = ["hidden_transit", "loop_transit", "latent_eras", "drifting_drain", "mass_balance", "shared_noise"]
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


@pytest.mark.parametrize("name", COPIES)
def test_copy_prices_hidden_at_zero_and_bounds_the_guard(name):
    bd = importlib.import_module(f"sdlab.discovery.strategies.{name}.boundary")
    assert bd.HIDDEN_PRICE == 0.0 and bd.CLAIM_PRICE == 2.0 and bd.GUARD_FITS > 0
    run = {**_chain(), **DECLARED}
    b = bd.Boundary(run)
    flows = bd.guard(SPLIT, STOCKS, b, bd.Data(STOCKS, run, {}), [])
    assert not bd.violations(flows, ["A", "B"], b, set())
    assert any(f["from"] == "A" and f["to"] == "B" for f in flows), flows
    # past the budget the guard still keeps no flow outside the boundary (it drops them)
    data = bd.Data(STOCKS, run, {})
    data.fits = bd.GUARD_FITS
    log: list[str] = []
    assert not bd.violations(bd.guard(SPLIT, STOCKS, b, data, log), ["A", "B"], b, set())
    assert all("no refit" in x for x in log)


@pytest.mark.parametrize("name", COPIES)
def test_strategy_stays_inside_the_boundary_and_lists_claims(name):
    bd = importlib.import_module(f"sdlab.discovery.strategies.{name}.boundary")
    run = _chain()
    r = load(name)(STOCKS, {**run, **DECLARED}, {})
    assert not bd.violations(r["flows"], ["A", "B"], bd.Boundary(DECLARED), set()), r["flows"]
    assert r["boundary"]["declared"] and r["boundary_claims"] == []
    r = load(name)(STOCKS, run, {})
    assert not r["boundary"]["declared"] and r["boundary_claims"]


def test_hidden_transit_fits_b_without_a_drain():
    """Where B has no declared outflow the transit is fitted with kb = 0 (fit_transit's kb_on)."""
    from sdlab.discovery.strategies.hidden_transit.fit import fit_transit
    from sdlab.discovery.strategies.hidden_transit.kalman import Pair

    rng = np.random.default_rng(1)
    T, A, H, B = 300, [50.0], [10.0], [5.0]
    for _ in range(T):
        a, h, b = A[-1], H[-1], B[-1]
        A.append(a + 10 - 0.2 * a + rng.normal(0, 0.2))
        H.append(h + 0.2 * a - 0.25 * h)
        B.append(b + 0.25 * h + rng.normal(0, 0.2))
    z, inflow = np.zeros(T), np.full(T, 10.0)            # A's outside inflow, as the kept flows give it
    f = fit_transit(Pair(np.array(A), np.array(B), inflow, inflow, z, z, 0.0), False, True, kb_on=False)
    assert f is not None and f["kb"] == 0.0 and 2.0 < 1 / f["d"] < 6.0


def test_loop_transit_effect_placements_respect_the_boundary():
    """An effect's flow may end at outside only on a declared side (search.placement_fits' ok)."""
    from sdlab.discovery.strategies.loop_transit import search

    seen = []
    cand = {"base": "A", "stock": "B", "rows": [("A", 1.0), ("B", 1.0)]}
    search.placement_fits(cand, ["A", "B"], np.ones((2, 50)), np.zeros((2, 49)), {"knots": [3], "per_candidate": 2, "halves": False},
                          ok=lambda frm, to: seen.append((frm, to)) or False)
    assert seen and all(isinstance(x, tuple) for x in seen)
