"""matrix's declared-boundary search (sdlab/discovery/strategies/matrix/boundary.py,
docs/research/declared-boundary.md)."""

from __future__ import annotations

import numpy as np

from sdlab.discovery.strategies import load
from sdlab.discovery.strategies.matrix import boundary as bd

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


def test_boundary_reads_the_announcement():
    b = bd.Boundary(DECLARED)
    assert b.declared and b.may("A", "in", "estimate") and not b.may("A", "out") and not b.may("C", "in")
    assert b.must_tie("A") and not b.must_tie("B") and b.inputs_ok("A") and b.pieces_ok("B")   # an estimate side may read inputs
    assert b.may("A", "in", "measured") and not b.may("C", "in", "measured")
    open_ = bd.Boundary({})
    assert not open_.declared and open_.may("A", "out", "measured") and not open_.must_tie("A")


def test_violations_follow_the_scorers_ends():
    b = bd.Boundary(DECLARED)
    assert bd.violations(SPLIT, ["A", "B"], b, set()) == [1, 2]
    hidden = [_flow(None, "H", {"form": "constant", "value": 1.0}), _flow("H", "B", {"form": "proportional", "stock": "H", "k": 0.1})]
    assert bd.ends(hidden, ["A", "B"])[0] == [("B", "in")]
    assert bd.violations(hidden, ["A", "B"], b, set()) == [0]
    measured = [_flow(None, "A", {"form": "linear", "c": 0, "terms": [{"stock": "u", "k": 1.0}]}, input="u")]
    assert bd.kind_of(measured[0], {"u"}) == "measured"
    assert bd.violations(measured, ["A", "B"], b, {"u"}) == []        # an estimate side may hold an inflow reading an input
    valve = [_flow(None, "A", {"form": "linear", "c": 75.0, "terms": [{"stock": "A", "k": -0.25}, {"stock": "u", "k": 0.8}]})]
    assert bd.kind_of(valve[0], {"u"}) == "estimate"                  # 208's valve reads a stock and a constant: estimate
    only_measured = bd.Boundary({"boundary": {"A": {"in": ["measured"]}}, "boundary_declared": True})
    assert bd.violations(valve, ["A", "B"], only_measured, {"u"}) == [0] and not bd.violations(measured, ["A", "B"], only_measured, {"u"})


def test_guard_makes_the_split_a_move():
    run = {**_chain(), **DECLARED}
    data = bd.Data(STOCKS, run, {})
    log: list[str] = []
    flows = bd.guard(SPLIT, STOCKS, bd.Boundary(run), data, log)
    assert not bd.violations(flows, ["A", "B"], bd.Boundary(run), set())
    moves = [f for f in flows if f["from"] == "A" and f["to"] == "B"]
    assert len(moves) == 1 and abs(moves[0]["rate"]["k"] - 0.4) < 0.01, flows
    assert len(flows) == 3 and log


def test_claims_are_priced_without_a_boundary():
    run = _chain()
    data = bd.Data(STOCKS, run, {})
    b = bd.Boundary(run)
    log: list[str] = []
    flows = bd.price_claims(bd.pair_moves(SPLIT, STOCKS, b, data, log), STOCKS, b, data, log)
    assert any(f["from"] == "A" and f["to"] == "B" for f in flows), flows
    assert bd.price(bd.Fit(flows, data), data, b) < bd.price(bd.Fit(SPLIT, data), data, b)
    claims = bd.claims(flows, ["A", "B"], b, set())
    assert {(c["stock"], c["side"]) for c in claims} == {("A", "in"), ("B", "out")}


def test_matrix_stays_inside_the_boundary_and_lists_claims():
    run = _chain()
    r = load("matrix")(STOCKS, {**run, **DECLARED}, {})
    assert not bd.violations(r["flows"], ["A", "B"], bd.Boundary(DECLARED), set())
    assert r["boundary"]["declared"] and r["boundary_claims"] == []
    r = load("matrix")(STOCKS, run, {})
    assert not r["boundary"]["declared"] and r["boundary_claims"]


def test_no_self_move_and_no_declared_side_left_empty():
    """(fixes ported from the copies, d5cd56a and c2a4894) An inflow into B is never "replaced" by moving
    B's own drain into B; and the guard and pair_moves never take away the last flow of a declared side."""
    run = {**_chain(), **DECLARED}
    data = bd.Data(STOCKS, run, {})
    b = bd.Boundary(run)
    alts = bd.alternatives(SPLIT, 2, STOCKS, b, data)            # flow 2: outside -> B, undeclared
    assert not any(f["from"] == f["to"] == "B" for _, cand in alts for f in cand)
    assert all(bd.kept_sides(SPLIT, cand, ["A", "B"], b) for _, cand in alts if "B -> outside" not in _)
    chain = [SPLIT[0], _flow("A", "B", {"form": "proportional", "stock": "A", "k": 0.4}), SPLIT[3]]
    closed = [_flow("B", "A", {"form": "proportional", "stock": "B", "k": 0.2}), chain[1]]
    assert bd.kept_sides(chain, chain, ["A", "B"], b) and not bd.kept_sides(chain, closed, ["A", "B"], b)
    assert bd.kept_sides(chain, closed, ["A", "B"], bd.Boundary({}))
    flows = bd.pair_moves(chain, STOCKS, b, data, [])
    assert {(c, s) for e in bd.ends(flows, ["A", "B"]) for c, s in e} == {("A", "in"), ("B", "out")}
