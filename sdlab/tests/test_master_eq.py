"""master_eq (sdlab/discovery/strategies/master_eq, docs/research/master_eq.md): per-region transition
probabilities fitted to counted levels; other data go to the main line."""

import numpy as np

from sdlab.discovery.strategies.master_eq import fit as F
from sdlab.discovery.strategies.master_eq.earned import main_line as own_main_line
from sdlab.discovery.strategies.master_eq import ml as ML
from sdlab.discovery.strategies.master_eq import terms as T
from sdlab.discovery.strategies.master_eq.run import identify


def particles(n=2000, seed=0):
    """Units fed into A at a measured rate, A <-> B exchanged both ways, B drained; every unit moves
    on its own (a multinomial per region), so the mean-field model is exact."""
    rng = np.random.default_rng(seed)
    feed = 4 + 3 * (np.arange(n) // 300 % 2)
    pa = {"B": 0.05, "out": 0.0}
    a, b = 60, 40
    A, B = [], []
    for k in range(n):
        ab = rng.binomial(a, pa["B"])
        mv = rng.multinomial(b, [0.03, 0.06, 0.91])          # B -> A, B -> outside, stay
        a, b = a - ab + mv[0] + rng.poisson(feed[k]), b + ab - mv[0] - mv[1]
        A.append(a)
        B.append(b)
    stocks = [{"id": "A", "unit": "things"}, {"id": "B", "unit": "things"}]
    run = {"t": list(range(1, n + 1)), "levels": {"A": A, "B": B}}
    return stocks, run, {"inputs": {"feed": [float(x) for x in feed]}}


def found(r):
    out = {}
    for f in r["flows"]:
        key = (f["from"], f["to"], f["rate"].get("stock"))
        out[key] = f["rate"].get("k", f["rate"].get("value"))
    return out


def test_two_way_exchange_and_its_feed_are_recovered():
    stocks, run, opts = particles()
    r = identify(stocks, run, opts)
    got = found(r)
    assert set(got) == {("A", "B", "A"), ("B", "A", "B"), ("B", None, "B"), (None, "A", "feed")}, got
    assert abs(got[("A", "B", "A")] - 0.05) < 0.005
    assert abs(got[("B", "A", "B")] - 0.03) < 0.004
    assert abs(got[("B", None, "B")] - 0.06) < 0.006
    assert abs(got[(None, "A", "feed")] - 1.0) < 0.1
    assert r["master_eq"]["mode"] == "binomial"


def test_ml_gradient_matches_differences():
    stocks, run, opts = particles(n=300)
    from sdlab.discovery.strategies.master_eq.run import prepare
    D, *_ = prepare(stocks, run, opts)
    P = F.Problem(D, T.conservative(2, 1, ["things", "things"]))
    cols = np.arange(len(P.pool))
    th = np.full(len(cols), 0.02)
    for mode in ("poisson", "binomial"):
        f = ML.objective(P, cols, mode)
        v, g = f(th)
        h = 1e-7
        num = np.array([(f(th + h * np.eye(len(th))[j])[0] - v) / h for j in range(len(th))])
        assert np.allclose(g, num, rtol=1e-3, atol=1e-2 * np.abs(g).max())


def test_levels_not_counted_go_to_the_main_line():
    stocks, run, opts = particles(n=300)
    run = {"t": run["t"], "levels": {k: [x + 0.5 for x in v] for k, v in run["levels"].items()}}
    r = identify(stocks, run, opts)
    assert r["chosen_by"].startswith("levels not counted")
    # master_eq's own main line (its copy of earned_pieces, earned.py), not the shared identify
    assert r["flows"] == own_main_line(stocks, run, dict(opts))["flows"]
