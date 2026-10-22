"""combined2's hidden integrator rows (hiddenrow.py), docs/research/fixes/310-combined2.md (round 2)."""

import numpy as np

from sdlab.discovery.strategies.combined2 import hiddenrow


def _record(n=500, leak=True):
    """`cache` (MB) is fed by 20 + 0.4 x junk + 3 x load / max(1, workers) and drained at 0.3; `junk` (hidden)
    grows 2 a step and is cleared at the same per-unit fraction as `workers` fall back to `idle` (0.02 per
    unit of heat over 80). heat cycles; load is an input."""
    t = np.arange(n + 1, dtype=float)
    heat = 70 + 15 * np.sin(2 * np.pi * t / 90)
    load = 200 + 80 * np.sin(2 * np.pi * t / 37)
    workers, idle, cache, junk = (np.zeros(n + 1) for _ in range(4))
    workers[0], idle[0], cache[0] = 10.0, 2.0, 100.0
    for i in range(n):
        frac = 0.02 * max(0.0, heat[i] - 80)
        fall, start = workers[i] * frac, 0.5 * idle[i]
        workers[i + 1] = workers[i] + start - fall
        idle[i + 1] = idle[i] - start + fall
        inflow = 20 + (0.4 * junk[i] if leak else 0.0) + 3 * load[i + 1] / max(1.0, workers[i])   # an input during the step (the engine reads its next value)
        cache[i + 1] = cache[i] + inflow - 0.3 * cache[i]
        junk[i + 1] = junk[i] + 2 - junk[i] * frac
    return t, heat, load, workers, idle, cache


def _setup(leak=True):
    t, heat, load, workers, idle, cache = _record(leak=leak)
    run = {"t": list(t), "levels": {"workers": list(workers), "idle": list(idle), "cache": list(cache), "heat": list(heat)},
           "boundary": {"cache": {"in": ["estimate"], "out": ["estimate"]}, "heat": {"in": ["estimate"], "out": ["estimate"]}},
           "boundary_declared": True}
    stocks = [{"id": "workers", "unit": "pods"}, {"id": "idle", "unit": "pods"}, {"id": "cache", "unit": "MB"}, {"id": "heat", "unit": "C"}]
    opts = {"inputs": {"load": list(load)}}
    pts = [[80.0, 0.0], [100.0, 1.0]]
    flows = [{"from": "idle", "to": "workers", "rate": {"form": "proportional", "stock": "idle", "k": 0.5}},
             {"from": "workers", "to": "idle", "rate": {"form": "proportional", "stock": "workers", "k": 0.4},
              "effects": [{"stock": "heat", "shape": "table", "points": pts}]},
             {"from": None, "to": "cache", "rate": {"form": "linear", "c": 40.0, "terms": [{"stock": "load", "k": 0.1}]}},
             {"from": "cache", "to": None, "rate": {"form": "proportional", "stock": "cache", "k": 0.3}}]
    return stocks, run, opts, flows


def test_a_hidden_integrator_drained_by_the_counted_fraction():
    stocks, run, opts, flows = _setup()
    out = hiddenrow.apply({"flows": flows}, stocks, run, opts)
    note = out["hidden_rows"][0]
    assert note["stock"] == "cache" and note["drain"] == "effect" and note["reads"] == ["load / max(1, workers)"]
    h = note["hidden"]
    assert h in out["inferred_levels"]
    drain = next(f for f in out["flows"] if f["from"] == h)
    assert abs(drain["rate"]["k"] - 0.4) < 1e-3 and drain["effects"][0]["stock"] == "heat"
    gone = next(f for f in out["flows"] if f["from"] == "cache")
    assert abs(gone["rate"]["k"] - 0.3) < 1e-6
    inflow = next(f for f in out["flows"] if f["to"] == "cache")
    assert f"* {h}" in inflow["rate"]["expr"] and "load / max(1, workers)" in inflow["rate"]["expr"]
    # H runs from 1 a step: the read coefficient is 0.4 x 2
    assert abs(float(inflow["rate"]["expr"].split(" + ")[1].split(" * ")[0]) - 0.8) < 1e-3
    assert note["sse"] < 1e-8 * note["sse_before"]


def test_no_hidden_stock_where_the_row_needs_none():
    stocks, run, opts, flows = _setup(leak=False)
    out = hiddenrow.apply({"flows": flows}, stocks, run, opts)
    assert "hidden_rows" not in out and "inferred_levels" not in out
