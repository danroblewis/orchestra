"""milp's hidden delay on an inflow (delay.py, k8s-312): a stock fed through a hidden first-order stage (DELAY1) by a
room-limited move's unmet demand, and drained by its surplus over a floored target read from another unit, gets the
stage, its time and both forms; a stock whose inflow arrives at once gets no hidden stock. Also room.py (k8s-312):
the room-limited move replaces a MIN the program wrote on the pair."""

import re

import numpy as np

from sdlab.discovery.strategies.milp import delay, room


def _model(n=600, lag=True):
    k = np.arange(n)
    want = 10 + 6 * np.sin(k / 30.0) + 4 * (k % 150 > 100)        # pods asked for (a measured level, pods)
    pods = np.zeros(n)
    nodes = np.zeros(n)
    pods[0], nodes[0], h = 8.0, 3.0, 0.0
    for i in range(n - 1):
        room_left = max(0.0, 4 * nodes[i] - pods[i])
        started = min(0.5 * max(0.0, want[i] - pods[i]), room_left)
        unmet = max(0.0, max(0.0, want[i] - pods[i]) - room_left)
        arrive = 0.5 * h if lag else 0.075 * unmet
        removed = 0.05 * max(0.0, nodes[i] - max(3.0, (pods[i] + want[i]) / 4))
        h = h + 0.075 * unmet - 0.5 * h
        pods[i + 1] = pods[i] + started - 0.02 * pods[i]
        nodes[i + 1] = nodes[i] + arrive - removed
    gap = np.maximum(0.0, want - pods)
    stocks = [{"id": "gap", "unit": "pods"}, {"id": "pods", "unit": "pods"}, {"id": "want", "unit": "pods"}, {"id": "nodes", "unit": "nodes"}]
    run = {"t": list(range(n)), "levels": {"gap": list(gap), "pods": list(pods), "want": list(want), "nodes": list(nodes)},
           "boundary": {"nodes": {"in": ["estimate"], "out": ["estimate"]}}, "boundary_declared": True}
    answer = [{"from": "gap", "to": "pods", "ratio": 1, "id": "r",
               "rate": {"form": "expr", "expr": "min(0.5 * gap, max(0, 4 * nodes - pods))"}},
              {"from": None, "to": "nodes", "ratio": 1, "rate": {"form": "linear", "c": 0.01, "terms": [{"stock": "gap", "k": 0.01}]}},
              {"from": "nodes", "to": None, "ratio": 1, "rate": {"form": "proportional", "stock": "nodes", "k": 0.01}}]
    return stocks, run, answer


def test_delayed_inflow_recovered():
    stocks, run, answer = _model()
    flows, note = delay.refine(answer, stocks, run, {})
    stage = [f for f in flows if f["from"] == "nodes_delay"]
    assert len(stage) == 1 and stage[0]["to"] == "nodes", note
    assert abs(stage[0]["rate"]["k"] - 0.5) < 0.01
    fill = next(f for f in flows if f["to"] == "nodes_delay")
    assert re.search(r"max\(0, gap - max\(0, 4(\.0)? \* nodes - pods\)\)", fill["rate"]["expr"]), fill["rate"]
    assert abs(float(fill["rate"]["expr"].split(" * ")[0]) - 0.075) < 0.002
    out = next(f for f in flows if f["from"] == "nodes" and f["to"] is None)
    assert re.match(r"^[\d.e+-]+ \* max\(0, nodes - max\(", out["rate"]["expr"]), out["rate"]


def test_no_stage_where_the_inflow_arrives_at_once():
    stocks, run, answer = _model(lag=False)
    flows, note = delay.refine(answer, stocks, run, {})
    assert not any("nodes_delay" in (f["from"], f["to"]) for f in flows), note


def test_room_replaces_a_program_min_on_the_pair():
    from tests.test_milp_room import _answer, _model as room_model
    stocks, run, opts = room_model()
    ans = [dict(f) for f in _answer()]
    ans[0] = {"from": "pending", "to": "ready", "ratio": 1, "rate": {"form": "expr", "expr": "min(0.3 * pending, 0.9 * nodes)"}}
    flows, note = room.refine(ans, stocks, run, opts)
    rm = [f for f in flows if f.get("room_fit")]
    assert len(rm) == 1 and rm[0]["room_fit"]["ceiling"] == "nodes", note
    assert not any((f["from"], f["to"]) == ("pending", "ready") and not f.get("room_fit") for f in flows)
