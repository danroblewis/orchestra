"""z3robust (docs/research/z3robust.md) on tiny synthetic data: the structure with noise and outliers,
the noise-free structure, and the encodings' building blocks."""

import random

import numpy as np

from sdlab.discovery.strategies import load
from sdlab.discovery.strategies.z3robust import core, robust


def _chain(noise: float = 0.0, outliers: int = 0, steps: int = 200):
    """outside -> A -> B -> outside from far off equilibrium (excited), levels with noise."""
    rng = random.Random(3)
    x = {"A": 0.0, "B": 600.0}
    lv = {"A": [], "B": []}
    bad = set(rng.sample(range(steps), outliers))
    for i in range(steps):
        for s, v in x.items():
            e = rng.gauss(0, noise) if noise else 0.0
            if i in bad and s == "A":
                e += 40 * noise
            lv[s].append(round(v + e, 4))
        a, b = x["A"], x["B"]
        x = {"A": a + 20.0 - 0.1 * a, "B": b + 0.1 * a - 0.05 * b}
    run = {"t": list(range(1, steps + 1)), "levels": lv, "boundary_declared": True,
           "boundary": {"A": {"in": ["estimate"], "out": []}, "B": {"in": [], "out": ["estimate"]}}}
    return [{"id": "A", "name": "A"}, {"id": "B", "name": "B"}], run


def test_noise_free_chain():
    stocks, run = _chain()
    r = load("z3robust")(stocks, run, {})
    got = {(f["from"], f["to"]) for f in r["flows"]}
    assert ("A", "B") in got and ("B", None) in got


def test_noisy_chain_with_outliers_keeps_the_moves():
    stocks, run = _chain(noise=0.05, outliers=4)
    r = load("z3robust")(stocks, run, {})
    rates = {(f["from"], f["to"]): f["rate"] for f in r["flows"]}
    assert ("A", "B") in rates and ("B", None) in rates
    assert abs(rates[("A", "B")]["k"] - 0.1) < 0.02
    assert r["z3robust"]["seconds"] < 60


def test_noise_scale_is_at_least_the_rounding():
    stocks, run = _chain()
    p = core.prepare(stocks, run, {}, pooled=True)
    B = robust.Compressed(p)
    sigma = robust.noise_scales(p, B)
    assert np.all(sigma >= np.array([float(e) for e in p.eps]) - 1e-15)
    assert B.n <= len(p.cols) and B.Y.shape == (2, B.n)


def test_counters_are_not_readers_and_skipped_rows_are_out():
    """(port-z3robust) a final stock's level is no term's reader; a skipped stock has no row and no term, but
    stays a column the other rows may read."""
    stocks, run = _chain()
    stocks = stocks + [{"id": "C", "name": "C", "final": True}]
    run = {**run, "levels": {**run["levels"], "C": [float(i) for i in range(len(run["t"]))]}}
    p = core.prepare(stocks, run, {}, pooled=True)
    assert not any(p.cols[t.col].name == "C" for t in p.terms)
    q = core.prepare(stocks, run, {}, pooled=True, skip=frozenset({"B"}))
    assert q.ids == ["A", "C"] and any(c.name == "B" for c in q.cols)
    assert not any(t.a == "B" or t.b == "B" for t in q.terms)


def test_negligible_move_is_dropped():
    from sdlab.discovery.strategies.z3robust.post import negligible
    stocks, run = _chain()
    flows = [{"from": "A", "to": "B", "rate": {"form": "proportional", "stock": "A", "k": 0.1}},
             {"from": "B", "to": "A", "rate": {"form": "proportional", "stock": "B", "k": 1e-7}},
             {"from": "B", "to": None, "rate": {"form": "proportional", "stock": "B", "k": 0.0}}]
    kept, note = negligible.refine(flows, stocks, run, {})
    assert [(f["from"], f["to"]) for f in kept] == [("A", "B"), ("B", None)] and note == {"dropped": ["B->A"]}
