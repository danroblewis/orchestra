"""combined2's sparseblock: a unit's block of plain rows the pick leaves above the rounding is re-read from the
levels (docs/research/fixes/315-combined2.md)."""

import numpy as np

from sdlab.discovery.strategies.combined2 import sparseblock


def _case(n=300):
    """u -> a; a -> b (0.6); outside -> c reads a (0.3); outside -> d reads a (0.15): c and d share a's shape."""
    t = np.arange(n + 1, dtype=float)
    u = 4.0 + 2.0 * np.sin(2 * np.pi * t / 60)
    a, b, c, d = (np.zeros(n + 1) for _ in range(4))
    a[0], b[0], c[0], d[0] = 5.0, 2.0, 3.0, 1.0
    for i in range(n):
        a[i + 1] = a[i] + u[i + 1] - 0.6 * a[i]
        b[i + 1] = b[i] + 0.6 * a[i] - 0.5 * b[i]
        c[i + 1] = c[i] + 0.3 * a[i] - 0.4 * c[i]
        d[i + 1] = d[i] + 0.15 * a[i] - 0.5 * d[i]
    lv = {k: list(np.round(v, 4)) for k, v in zip("abcd", (a, b, c, d))}
    stocks = [{"id": k, "unit": "req"} for k in "abcd"]
    run = {"t": list(t), "levels": lv, "boundary_declared": True,
           "boundary": {"a": {"in": ["input"]}, "b": {"out": ["estimate"]}, "c": {"in": ["estimate"], "out": ["estimate"]},
                        "d": {"in": ["estimate"], "out": ["estimate"]}}}
    return stocks, run, {"inputs": {"u": list(u)}}


def _truth():
    return [{"from": None, "to": "a", "ratio": 1, "rate": {"form": "proportional", "stock": "u", "k": 1.0}},
            {"from": "a", "to": "b", "ratio": 1, "rate": {"form": "proportional", "stock": "a", "k": 0.6}},
            {"from": "b", "to": None, "ratio": 1, "rate": {"form": "proportional", "stock": "b", "k": 0.5}},
            {"from": None, "to": "c", "ratio": 1, "rate": {"form": "linear", "c": 0.0, "terms": [{"stock": "a", "k": 0.3}]}},
            {"from": "c", "to": None, "ratio": 1, "rate": {"form": "proportional", "stock": "c", "k": 0.4}},
            {"from": None, "to": "d", "ratio": 1, "rate": {"form": "linear", "c": 0.0, "terms": [{"stock": "a", "k": 0.15}]}},
            {"from": "d", "to": None, "ratio": 1, "rate": {"form": "proportional", "stock": "d", "k": 0.5}}]


def test_a_crossed_block_is_reread_to_the_truth():
    stocks, run, opts = _case()
    pick = {"flows": _truth()[:3] + [
        {"from": None, "to": "c", "ratio": 1, "rate": {"form": "linear", "c": 0.0, "terms": [{"stock": "b", "k": 0.2}]}},
        {"from": "c", "to": "d", "ratio": 1, "rate": {"form": "proportional", "stock": "c", "k": 0.2}},
        {"from": "d", "to": None, "ratio": 1, "rate": {"form": "proportional", "stock": "d", "k": 0.3}}]}
    out = sparseblock.apply(pick, stocks, run, opts)
    got = {(f["from"], f["to"]): f["rate"] for f in out["flows"]}
    assert set(got) == {(f["from"], f["to"]) for f in _truth()}
    assert abs(got[(None, "c")]["terms"][0]["k"] - 0.3) < 1e-4 and got[(None, "c")]["terms"][0]["stock"] == "a"
    assert abs(got[(None, "d")]["terms"][0]["k"] - 0.15) < 1e-4
    assert got[(None, "a")]["k"] == 1.0                   # the input side is held


def test_an_exact_pick_is_kept():
    stocks, run, opts = _case()
    pick = {"flows": _truth()}
    assert sparseblock.apply(pick, stocks, run, opts) is pick


def test_noisy_counts_leave_it_idle():
    stocks, run, opts = _case()
    run["levels"] = {k: list(np.round(v)) for k, v in run["levels"].items()}
    pick = {"flows": _truth()[:3]}
    assert sparseblock.apply(pick, stocks, run, opts) is pick


def test_a_switch_on_the_block_leaves_it_alone():
    stocks, run, opts = _case()
    pick = {"flows": _truth()[:6] + [{"from": "d", "to": None, "ratio": 1, "rate": {"form": "expr", "expr": "max(0, d - 1)"}}]}
    assert sparseblock.apply(pick, stocks, run, opts) is pick
