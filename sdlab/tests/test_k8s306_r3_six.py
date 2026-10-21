"""Kubernetes 306 round 3 (docs/research/k8s-306-r3-six.md): held_out pairs the offered MIN series' two
outside halves, z3exact's "ends" class lets a move read the offered series of its source, and milp moves
only between stocks of one unit."""

from __future__ import annotations

from sdlab.discovery.strategies.held_out.pairing import pair
from sdlab.discovery.strategies.milp import candidates as milp_candidates
from sdlab.discovery.strategies.milp.steps import Steps
from sdlab.discovery.strategies.z3exact import capmin as z3_capmin, core as z3core

from sdlab.ladder import cases as casemod, data

CASE = "306-k8s-ready-replicas-cap"
M = "capmin__queue__ready"


def _args(case_id: str, variant: str):
    c = casemod.load(case_id)
    model = casemod.truth_model(c, variant)
    d = {**data.load(c, variant), **casemod.announced(c)}
    opts = {"eras": None, "injections": [{"t": j["t"], "stock": j["stock"], "amount": j["amount"]} for j in d.get("injections") or []],
            "inputs": {k: list(v) for k, v in (d.get("inputs") or {}).items()}}
    run = {"t": d["t"], "levels": d["levels"], "boundary": d["boundary"], "boundary_declared": True}
    return casemod.page_stocks(model), run, opts


def _lin(name, k, c=0.0, more=()):
    return {"form": "linear", "c": c, "terms": [{"stock": name, "k": k}, *more]}


def test_pair_joins_the_two_halves():
    flows = [{"from": "queue", "to": None, "rate": _lin(M, 0.6)},
             {"from": None, "to": "inflight", "rate": _lin(M, 0.5, more=[{"stock": "traffic", "k": 0.1}])},
             {"from": "queue", "to": "retries", "rate": {"form": "proportional", "stock": "queue", "k": 0.08}}]
    out = pair(flows, {M: ("queue", "inflight")})
    moves = [f for f in out if f["from"] == "queue" and f["to"] == "inflight"]
    assert len(moves) == 1 and abs(moves[0]["rate"]["terms"][0]["k"] - 0.55) < 1e-12
    rest = [f for f in out if f["from"] is None and f["to"] == "inflight"]
    assert rest and rest[0]["rate"]["terms"] == [{"stock": "traffic", "k": 0.1}]       # what else it read is kept
    assert not any(f["from"] == "queue" and f["to"] is None for f in out)


def test_pair_leaves_a_lone_half():
    flows = [{"from": "queue", "to": None, "rate": _lin(M, 0.6)}]
    assert pair(flows, {M: ("queue", "inflight")}) == flows


def test_z3exact_ends_class_reads_the_offered_series():
    stocks, run, opts = _args(CASE, "none-short")
    o, cap = z3_capmin.offer(stocks, run, opts)
    assert cap and cap["to"] == "inflight"
    p = z3core.prepare(stocks, run, o, moves="ends", boundary="kinds")
    reads = {(t.kind, t.a, t.b) for t in p.terms if p.cols[t.col].name == cap["name"]}
    assert ("move", "queue", "inflight") in reads or ("move", "inflight", "queue") in reads
    assert not any(k == "outside" for k, _, _ in reads)                               # only the limited flow reads it


def test_milp_moves_keep_one_unit():
    stocks, run, opts = _args(CASE, "none-short")
    st = Steps(stocks, run, opts)
    terms, mins = milp_candidates.build(st, milp_candidates.Boundary(run))
    assert not any(t.src and t.dst and "ready" in (t.src, t.dst) for t in terms)     # pods never move into requests
    assert not any(m.dst and "ready" in (m.src, m.dst) for m in mins)
    assert any(m.src == "queue" and m.dst == "inflight" and m.cap == "ready" for m in mins)   # a capacity may read pods
