"""capmin_pair.py (effect_hats, sindy; 2026-10-21): the offered MIN series' halves joined into one move."""

from sdlab.discovery.strategies.effect_hats import capmin_pair as A
from sdlab.discovery.strategies.sindy import capmin_pair as B

OPTS = {"capmin": {"capmin__queue__ready": {"source": "queue", "to": "inflight"}}}


def _lin(name, k):
    r = {"form": "linear", "c": 0, "terms": [{"stock": name, "k": k}]}
    return {"rate": r, "rates": [r]}


def test_halves_joined_and_strays_dropped():
    m = "capmin__queue__ready"
    flows = [{"from": "queue", "to": None, **_lin(m, 0.6)}, {"from": None, "to": "inflight", **_lin(m, 0.5)},
             {"from": None, "to": "responses_total", **_lin(m, 0.04)},
             {"from": "inflight", "to": "responses_total", "rate": {"form": "proportional", "stock": "inflight", "k": 0.5}}]
    for mod in (A, B):
        out = mod.pair(flows, OPTS)
        moves = [f for f in out if any(t.get("stock") == m for t in (f["rate"].get("terms") or []))]
        assert len(moves) == 1 and moves[0]["from"] == "queue" and moves[0]["to"] == "inflight"
        assert abs(moves[0]["rate"]["terms"][0]["k"] - 0.55) < 1e-12
        assert len(out) == 2


def test_nothing_offered_unchanged():
    flows = [{"from": "a", "to": None, **_lin("x", 1.0)}]
    assert A.pair(flows, {}) == flows and B.pair(flows, {}) == flows
