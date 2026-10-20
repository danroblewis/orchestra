"""kalman_bayes: the block ensemble's inclusion probabilities and the posterior of a structure's numbers
(docs/research/kalman_bayes.md)."""

from __future__ import annotations

import time

import numpy as np

from sdlab.discovery.strategies.kalman_bayes import bag
from sdlab.discovery.strategies.kalman_bayes.posterior import mode, sample


def _chain(T: int = 400, seed: int = 3) -> dict:
    """outside -> A = 20, A -> B = 0.5 A, B -> outside = 0.2 B, Poisson counts, every step reported."""
    rng = np.random.default_rng(seed)
    a, b = 40.0, 100.0
    A, B = [], []
    for _ in range(T):
        A.append(a)
        B.append(b)
        i, m, o = rng.poisson(20), rng.poisson(0.5 * a), rng.poisson(0.2 * b)
        a, b = max(0.0, a + i - m), max(0.0, b + m - o)
    return {"t": list(range(1, T + 1)), "levels": {"A": A, "B": B}}


FLOWS = [{"from": None, "to": "A", "rate": {"form": "constant", "value": 21.0}},
         {"from": "A", "to": "B", "rate": {"form": "proportional", "stock": "A", "k": 0.45}},
         {"from": "B", "to": None, "rate": {"form": "proportional", "stock": "B", "k": 0.22}}]


def test_posterior_covers_the_truth_and_writes_its_summary():
    run = _chain()
    stocks = [{"id": "A"}, {"id": "B"}]
    m = mode(FLOWS, stocks, run, {}, {}, time.monotonic() + 20)
    got, info = sample(m, time.monotonic() + 40)
    assert got is not None, info
    truth = {("outside->A", "value"): 20.0, ("A->B", "k"): 0.5, ("B->outside", "k"): 0.2}
    for n in info["numbers"]:
        assert n["lo"] <= truth[(n["flow"], n["key"])] <= n["hi"], n
        assert n["sd"] > 0
    assert all(any(k.endswith("_post") for k in f["rate"]) for f in got)


def test_inclusion_counts_the_blocks_that_have_a_flow():
    a = [{"from": "A", "to": "B", "rate": {"form": "proportional", "stock": "A", "k": 0.5}}]
    b = a + [{"from": None, "to": "B", "rate": {"form": "proportional", "stock": "A", "k": 0.01}}]
    inc = bag.inclusion(a, [a, a, b, a])
    assert inc[bag.key(a[0])] == 1.0 and inc[bag.key(b[1])] == 0.25
    kept, dropped, added = bag.bagged(b, [a, a, b, a], bag.inclusion(b, [a, a, b, a]))
    assert len(kept) == 1 and dropped == ["outside->B reads A"] and not added


def test_a_block_is_an_ordinary_shorter_run():
    run = _chain(T=100)
    r, o = bag.block(run, {"injections": [{"t": 5, "stock": "A", "amount": 3}, {"t": 50, "stock": "A", "amount": 3}]}, 30, 100)
    assert r["t"][0] == 31 and len(r["levels"]["A"]) == 70
    assert [j["t"] for j in o["injections"]] == [50]


def test_a_rate_that_goes_below_zero_is_held_at_zero_by_the_prior():
    """Below 0 the engine floors a rate, the likelihood is flat there: the prior keeps k >= 0."""
    run = _chain(T=200)
    flows = [{"from": "B", "to": None, "rate": {"form": "proportional", "stock": "B", "k": 0.01}}]
    m = mode(flows, [{"id": "A"}, {"id": "B"}], run, {}, {}, time.monotonic() + 10)
    got, info = sample(m, time.monotonic() + 10)
    assert got is not None and all(n["lo"] >= 0 for n in info["numbers"])
