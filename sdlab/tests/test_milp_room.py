"""milp's room-limited moves (room.py, k8s-311): a move that fills its receiver only up to a ceiling another level
sets, MIN(a x S, MAX(0, b x Y - D)), recovered from an answer with a plain move in its place; a plain move left
alone."""

import re

import numpy as np

from sdlab.discovery.strategies.milp import room


def _model(n=300, ceiling=True):
    k = np.arange(n)
    nodes = np.where((k % 100 > 40) & (k % 100 < 60), 2.0, 3.0)         # the ceiling's reader (nodes), measured
    ready, pending = np.zeros(n), np.zeros(n)
    ready[0], pending[0] = 6.0, 2.0
    for i in range(n - 1):
        demand = 0.5 * pending[i]
        started = min(demand, max(0.0, 4 * nodes[i] - ready[i])) if ceiling else demand
        created = 1.0 + 0.8 * np.sin(i / 9.0)
        deleted = 0.1 * ready[i]
        ready[i + 1] = ready[i] + started - deleted
        pending[i + 1] = pending[i] + created - started
    stocks = [{"id": "ready", "unit": "pods"}, {"id": "pending", "unit": "pods"}, {"id": "nodes", "unit": "nodes"}]
    run = {"t": list(range(n)), "levels": {"ready": list(ready), "pending": list(pending), "nodes": list(nodes)},
           "boundary": {"pending": {"in": ["estimate"]}, "ready": {"out": ["estimate"]}}, "boundary_declared": True}
    created = 1.0 + 0.8 * np.sin(np.arange(n) / 9.0)
    return stocks, run, {"inputs": {"created": list(np.r_[created[0], created[:-1]])}}


def _answer():
    return [{"from": "pending", "to": "ready", "ratio": 1, "rate": {"form": "proportional", "stock": "pending", "k": 0.2}},
            {"from": None, "to": "pending", "ratio": 1, "rate": {"form": "proportional", "stock": "created", "k": 1.0}},
            {"from": "ready", "to": None, "ratio": 1, "rate": {"form": "proportional", "stock": "ready", "k": 0.1}}]


def test_room_limited_move_recovered():
    stocks, run, opts = _model()
    flows, note = room.refine(_answer(), stocks, run, opts)
    rm = [f for f in flows if f.get("room_fit")]
    assert len(rm) == 1 and (rm[0]["from"], rm[0]["to"]) == ("pending", "ready"), note
    assert rm[0]["room_fit"]["ceiling"] == "nodes"
    a, b = (float(x) for x in re.findall(r"min\(([\d.e+-]+) \* pending, max\(0, ([\d.e+-]+) \* nodes - ready\)\)", rm[0]["rate"]["expr"])[0])
    assert abs(a - 0.5) < 0.01 and abs(b - 4) < 0.02
    assert not any((f["from"], f["to"]) == ("pending", "ready") and not f.get("room_fit") for f in flows)


def test_plain_move_left_alone():
    stocks, run, opts = _model(ceiling=False)
    ans = [dict(f) for f in _answer()]
    ans[0]["rate"] = {"form": "proportional", "stock": "pending", "k": 0.5}
    flows, note = room.refine(ans, stocks, run, opts)
    assert not any(f.get("room_fit") for f in flows), note
