"""pairing.py (docs/research/k8s-306-s1.md, "What still fails": counts, MIN mis-routed): one identical copy per strategy; the offered MIN series' two
outside terms become one move; an input read where the declared boundary has no side is dropped unless an
opposite outside flow reads it too."""

from pathlib import Path

import pytest

from sdlab.discovery.strategies.common_cause import boundary, pairing

ROOT = Path(__file__).resolve().parents[1] / "sdlab" / "discovery" / "strategies"
COPIES = ["common_cause", "inflow_effects"]


def test_copies_identical():
    texts = {p: (ROOT / p / "pairing.py").read_text() for p in COPIES}
    assert len(set(texts.values())) == 1, sorted(texts)


def _lin(name, k):
    r = {"form": "linear", "c": 0, "terms": [{"stock": name, "k": k}]}
    return {"rate": r, "rates": [r]}


OPTS = {"inputs": {"traffic": [1.0] * 5, "capmin__q__r": [1.0] * 5}, "capmin": {"capmin__q__r": {"source": "q", "to": "f"}}}


def test_pair_joins_source_and_receiver():
    flows = [{"from": "q", "to": None, **_lin("capmin__q__r", 0.62)}, {"from": None, "to": "f", **_lin("capmin__q__r", 0.58)},
             {"from": None, "to": "q", **_lin("traffic", 1.0)}]
    out = pairing.pair(flows, OPTS)
    moves = [f for f in out if f["from"] == "q" and f["to"] == "f"]
    assert len(out) == 2 and len(moves) == 1
    assert moves[0]["rate"]["terms"][0]["k"] == pytest.approx(0.6)


def test_pair_leaves_other_receivers():
    flows = [{"from": "q", "to": None, **_lin("capmin__q__r", 0.6)}, {"from": None, "to": "x", **_lin("capmin__q__r", 0.6)}]
    assert pairing.pair(flows, OPTS) == flows


def test_unpaired_inputs():
    b = boundary.Boundary({"boundary_declared": True, "boundary": {"q": {"in": ["measured"]}}})
    keep = {"from": None, "to": "q", **_lin("traffic", 1.0)}
    lone = {"from": "f", "to": None, **_lin("traffic", 0.1)}
    assert pairing.unpaired_inputs([keep, lone], b, OPTS) == [keep]
    # an opposite flow on another undeclared stock reading the same input: a move the guard joins, kept
    other = {"from": None, "to": "g", **_lin("traffic", 0.1)}
    assert pairing.unpaired_inputs([keep, lone, other], b, OPTS) == [keep, lone, other]
    # no declared boundary: unchanged
    assert pairing.unpaired_inputs([keep, lone], boundary.Boundary({}), OPTS) == [keep, lone]
