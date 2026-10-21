"""combined2's discrete-actuator switch (switch.py, docs/research/fixes/308-combined2.md)."""

import numpy as np

from sdlab.discovery.strategies.combined2 import switch
from sdlab.ladder import sim


def _record(n=400):
    t = np.arange(n + 1, dtype=float)
    load = 1500 + 900 * np.sin(2 * np.pi * t / 150)
    pods = np.zeros(n + 1)
    pods[0] = 9
    for i in range(n):
        up = 1.0 if (load[i] > 190 * pods[i] and pods[i] < 16) else 0.0
        down = 1.0 if (load[i] <= 160 * (pods[i] - 1) and pods[i] > 3) else 0.0
        pods[i + 1] = pods[i] + up - down
    return t, load, pods


def test_switch_replaces_linear_drift_and_runs_in_the_engine():
    t, load, pods = _record()
    run = {"t": list(t), "levels": {"pods": list(pods), "load": list(load)}}
    stocks = [{"id": "pods"}, {"id": "load"}]
    drift = [{"from": None, "to": "pods", "rate": {"form": "linear", "c": 0.05, "terms": []}},
             {"from": "pods", "to": None, "rate": {"form": "proportional", "stock": "pods", "k": 0.004}},
             {"from": None, "to": "load", "rate": {"form": "linear", "c": 1.0, "terms": []}}]
    out = switch.apply({"flows": drift}, stocks, run, {})
    sw = [f for f in out["flows"] if f.get("switch")]
    assert {(f["from"], f["to"]) for f in sw} == {(None, "pods"), ("pods", None)}
    assert len(out["flows"]) == 3                                  # one flow per side, load's untouched
    states = [{"pods": pods[i], "load": load[i]} for i in range(len(t) - 1)]
    net = sum((1 if f["to"] == "pods" else -1) * np.asarray(sim.amounts(f, {"t": list(t)}, states)) for f in sw)
    assert np.allclose(net, np.diff(pods))


def test_smooth_stock_is_left_alone():
    t, load, _ = _record()
    run = {"t": list(t), "levels": {"load": list(load)}}
    flows = [{"from": None, "to": "load", "rate": {"form": "linear", "c": 1.0, "terms": []}}]
    assert switch.apply({"flows": flows}, [{"id": "load"}], run, {}) == {"flows": flows}
