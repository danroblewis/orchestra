"""combined2's counted flows (counted.py), docs/research/fixes/310-combined2.md."""

import numpy as np

from sdlab.discovery.strategies.combined2 import counted, hinge


def _record(n=400):
    """`up` pods fed from `wait` at 0.5 a step; a heat level `heat` (another unit) that cycles; above 80 a
    share of `up` falls back to `wait` (0.02 per unit of heat over 80), each fall counted in `falls`."""
    t = np.arange(n + 1, dtype=float)
    heat = 70 + 15 * np.sin(2 * np.pi * t / 90)
    up, wait, falls = (np.zeros(n + 1) for _ in range(3))
    up[0], wait[0] = 10.0, 2.0
    for i in range(n):
        fall = up[i] * max(0.0, 0.02 * (heat[i] - 80))
        start = 0.5 * wait[i]
        up[i + 1] = up[i] + start - fall
        wait[i + 1] = wait[i] - start + fall + 0.1
        falls[i + 1] = falls[i] + fall
    return t, heat, up, wait, falls


def _setup():
    t, heat, up, wait, falls = _record()
    run = {"t": list(t), "levels": {"up": list(up), "wait": list(wait), "falls": list(falls), "heat": list(heat)},
           "boundary": {"wait": {"in": "estimate"}, "falls": {"in": "estimate"}, "heat": {"in": "estimate", "out": "estimate"}},
           "boundary_declared": True}
    stocks = [{"id": "up", "unit": "pods"}, {"id": "wait", "unit": "pods"}, {"id": "falls", "unit": "pods", "final": True},
              {"id": "heat", "unit": "C"}]
    flows = [{"from": "wait", "to": "up", "rate": {"form": "proportional", "stock": "wait", "k": 0.45}},
             {"from": None, "to": "wait", "rate": {"form": "constant", "value": 0.15}},
             {"from": None, "to": "falls", "rate": {"form": "constant", "value": 0.05}}]
    return stocks, run, flows, (t, heat, up, wait, falls)


def test_a_counter_gives_the_move_it_counts():
    stocks, run, flows, (t, heat, up, wait, falls) = _setup()
    out = counted.apply({"flows": flows}, stocks, run, {})
    note = out["counted"][0]
    assert note["counter"] == "falls" and note["base"] == "up" and note["reader"] == "heat" and note["move"] == "wait"
    move = [f for f in out["flows"] if f["from"] == "up" and f["to"] == "wait"]
    assert len(move) == 1 and move[0]["effects"][0]["stock"] == "heat"
    levels, cols, n = hinge.columns(run, {})
    want = up[:n] * np.maximum(0.0, 0.02 * (heat[:n] - 80))
    got = hinge.amount(move[0], cols, n)
    assert np.sqrt(np.mean((got - want) ** 2)) < 1e-3 * np.sqrt(np.mean(want ** 2))
    back = [f for f in out["flows"] if f["from"] == "wait" and f["to"] == "up"][0]   # the start rate repaired
    assert abs(back["rate"]["k"] - 0.5) < 1e-3


def test_a_counter_fed_by_a_move_is_left_alone():
    stocks, run, flows, _ = _setup()
    flows = flows[:2] + [{"from": "up", "to": "falls", "rate": {"form": "proportional", "stock": "up", "k": 0.01}}]
    out = counted.apply({"flows": flows}, stocks, run, {})
    assert "counted" not in out
