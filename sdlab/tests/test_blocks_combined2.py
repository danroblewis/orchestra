"""combined2's blocks.compose: a unit's rows another candidate explains to the rounding replace the pick's
(docs/research/fixes/312-combined2-r2.md)."""

import numpy as np

from sdlab.discovery.strategies.combined2 import blocks


def _case(n=300):
    t = np.arange(n + 1, dtype=float)
    u = 1.0 + 0.5 * np.sin(2 * np.pi * t / 50)
    a, b, h = np.zeros(n + 1), np.zeros(n + 1), np.zeros(n + 1)
    a[0], b[0], h[0] = 3.0, 1.0, 5.0
    for i in range(n):
        a[i + 1] = a[i] + u[i + 1] - 0.2 * a[i]
        b[i + 1] = b[i] + 0.2 * a[i] - 0.1 * b[i]
        h[i + 1] = h[i] + 0.05 * a[i] - 0.02 * h[i]
    lv = {"a": list(np.round(a, 4)), "b": list(np.round(b, 4)), "h": list(np.round(h, 4))}
    stocks = [{"id": "a", "unit": "jobs"}, {"id": "b", "unit": "jobs"}, {"id": "h", "unit": "hosts"}]
    return stocks, {"t": list(t), "levels": lv}, {"inputs": {"u": list(u)}}


def _flows(k_move, k_h=0.05):
    return [{"from": None, "to": "a", "ratio": 1, "rate": {"form": "proportional", "stock": "u", "k": 1.0}},
            {"from": "a", "to": "b", "ratio": 1, "rate": {"form": "proportional", "stock": "a", "k": k_move}},
            {"from": "b", "to": None, "ratio": 1, "rate": {"form": "proportional", "stock": "b", "k": 0.1}},
            {"from": None, "to": "h", "ratio": 1, "rate": {"form": "proportional", "stock": "a", "k": k_h}},
            {"from": "h", "to": None, "ratio": 1, "rate": {"form": "proportional", "stock": "h", "k": 0.02}}]


def test_an_exact_block_replaces_a_wrong_one():
    stocks, run, opts = _case()
    pick = {"flows": _flows(0.15, k_h=0.04)}          # both blocks off; the other candidate has only jobs right
    other = {"name": "x", "flows": _flows(0.2, k_h=0.07)}
    out = blocks.compose(pick, [other], stocks, run, opts)
    assert [b["unit"] for b in out["blocks_taken"]] == ["jobs"]
    got = {(f["from"], f["to"]): f["rate"].get("k") for f in out["flows"]}
    assert got[("a", "b")] == 0.2 and got[(None, "h")] == 0.04


def test_a_pick_that_is_nearly_exact_is_kept():
    stocks, run, opts = _case()
    pick = {"flows": _flows(0.2 + 1e-7)}
    out = blocks.compose(pick, [{"name": "x", "flows": _flows(0.2)}], stocks, run, opts)
    assert out is pick
