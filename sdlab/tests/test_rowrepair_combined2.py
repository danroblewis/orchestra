"""combined2's row repair (rowrepair.py), docs/research/fixes/310-combined2.md (round 2)."""

import numpy as np

from sdlab.discovery.strategies.combined2 import rowrepair


def _setup(n=300):
    """jobs arrive (an input) into `queue`, move to `busy` at 0.6, 0.08 of the queue to `retry`, which sends
    0.6 back and loses 0.4; `busy` finishes into the counter `done` at 0.5. Levels to four decimals."""
    t = np.arange(n + 1, dtype=float)
    load = 400 + 200 * np.sin(2 * np.pi * t / 60)
    q, b, r, d = (np.zeros(n + 1) for _ in range(4))
    q[0], b[0] = 50.0, 100.0
    for i in range(n):
        q[i + 1] = q[i] + load[i + 1] - 0.68 * q[i] + 0.6 * r[i]
        b[i + 1] = b[i] + 0.6 * q[i] - 0.5 * b[i]
        r[i + 1] = r[i] + 0.08 * q[i] - r[i]
        d[i + 1] = d[i] + 0.5 * b[i]
    lv = {k: list(np.round(v, 4)) for k, v in (("queue", q), ("busy", b), ("retry", r), ("done", d))}
    run = {"t": list(t), "levels": lv, "boundary_declared": True,
           "boundary": {"queue": {"in": ["input"], "out": []}, "retry": {"in": [], "out": ["estimate"]}}}
    stocks = [{"id": "queue", "unit": "jobs"}, {"id": "busy", "unit": "jobs"}, {"id": "retry", "unit": "jobs"},
              {"id": "done", "unit": "jobs", "final": True}]
    return stocks, run, {"inputs": {"load": list(load)}}


def test_the_moves_a_block_lacks_are_found_together():
    stocks, run, opts = _setup()
    flows = [{"from": None, "to": "queue", "ratio": 1, "input": "load", "rate": {"form": "proportional", "stock": "load", "k": 1.0}}]
    out = rowrepair.apply({"flows": flows}, stocks, run, opts)
    got = {(f["from"], f["to"]): f["rate"] for f in out["flows"]}
    want = {("queue", "busy"): 0.6, ("queue", "retry"): 0.08, ("retry", "queue"): 0.6, ("retry", None): 0.4, ("busy", "done"): 0.5}
    assert set(got) == set(want) | {(None, "queue")}
    for key, k in want.items():
        assert abs(got[key]["k"] - k) < 1e-4, (key, got[key])
    assert got[(None, "queue")] == {"form": "proportional", "stock": "load", "k": 1.0}      # the input side untouched


def test_explained_rows_are_left_alone():
    stocks, run, opts = _setup()
    first = rowrepair.apply({"flows": [{"from": None, "to": "queue", "ratio": 1, "input": "load",
                                        "rate": {"form": "proportional", "stock": "load", "k": 1.0}}]}, stocks, run, opts)
    again = rowrepair.apply({"flows": first["flows"]}, stocks, run, opts)
    assert "repaired_rows" not in again
