"""structures' capmin offer of a fixed pool, MIN(X, max(0, a - b Z)) (k8s 316, docs/research/fixes/316-structures.md)."""

import numpy as np

from sdlab.discovery.strategies.structures import capmin


def _run(T: int = 300):
    t = np.arange(T, dtype=float)
    u = 40 + 30 * np.sin(2 * np.pi * t / 96)               # queries arriving per step
    w, a = [10.0], [60.0]
    for k in range(T - 1):
        got = min(0.8 * w[-1], max(0.0, 80 - 0.2 * a[-1]))
        w.append(w[-1] + u[k] - got)
        a.append(a[-1] + got - 0.8 * a[-1])
    stocks = [{"id": "waiting", "unit": "queries"}, {"id": "active", "unit": "connections"}]
    run = {"t": list(t), "levels": {"waiting": w, "active": a}}
    return stocks, run, {"inputs": {"arrivals": list(u)}}


def test_the_pool_limit_is_offered_with_its_numbers():
    stocks, run, opts = _run()
    o, cap = capmin.offer(stocks, run, opts)
    assert cap is not None and cap["cap"] is None
    assert (cap["source"], cap["occupant"], cap["to"]) == ("waiting", "active", "active")
    assert abs(cap["a"] - 100) < 0.5 and abs(cap["b"] - 0.25) < 0.005
    text = capmin._min_text(0.8, {**cap, "name": "x"})
    assert text.startswith("min(0.8 * waiting, max(0, ")


def test_no_offer_without_a_limit():
    stocks, run, opts = _run()
    w = np.asarray(run["levels"]["waiting"])
    run["levels"]["active"] = list(50 + 0.3 * w)              # no kink anywhere
    _, cap = capmin.offer(stocks, run, opts)
    assert cap is None or cap["cap"] is not None
