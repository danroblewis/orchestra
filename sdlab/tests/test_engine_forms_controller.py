"""engine_forms's controller.py (k8s-308): a count stock driven to a quantized target is read as the gap
to ceil(X / a) up and ceil(X / b) down, and only where that explains every change exactly."""

import math

import numpy as np

from sdlab.discovery.strategies.engine_forms import controller


def _run(n=400):
    t = np.arange(n)
    x = 1500 + 1400 * np.sin(2 * math.pi * t / 120) + 300 * np.sin(2 * math.pi * t / 37)
    s = [9.0]
    for i in range(n - 1):
        up = max(0.0, min(16.0, math.ceil(x[i] / 192.5)) - s[i])
        down = 1.0 * (s[i] > max(3.0, math.ceil(x[i] / 157.5)))
        s.append(s[i] + up - down)
    return {"t": list(t), "levels": {"load": list(x), "pods": s},
            "boundary": {"pods": {"in": ["estimate"], "out": ["estimate"]}}, "boundary_declared": True}


def _flows():
    return [{"from": None, "to": "pods", "rate": {"form": "constant", "c": 0.1}},
            {"from": "pods", "to": None, "rate": {"form": "proportional", "stock": "pods", "k": 0.01}}]


def _amounts(expr, levels):
    env = {"min": min, "max": max, "ceil": math.ceil}
    return np.array([eval(expr, env, {k: v[i] for k, v in levels.items()}) for i in range(len(levels["pods"]) - 1)])


def test_a_count_stock_is_read_as_its_controller():
    run = _run()
    stocks = [{"id": "load"}, {"id": "pods"}]
    r = controller.apply({"flows": _flows()}, stocks, run, {})
    assert r.get("controller"), r
    ups = [f for f in r["flows"] if f.get("to") == "pods"]
    downs = [f for f in r["flows"] if f.get("from") == "pods"]
    assert len(ups) == 1 and len(downs) == 1
    s = np.asarray(run["levels"]["pods"])
    net = _amounts(ups[0]["rate"]["expr"], run["levels"]) - _amounts(downs[0]["rate"]["expr"], run["levels"])
    assert np.allclose(net, np.diff(s))


def test_a_stock_that_is_not_counted_is_left_alone():
    run = _run()
    rng = np.random.default_rng(1)
    run["levels"]["pods"] = list(np.round(np.asarray(run["levels"]["pods"]) + rng.integers(-1, 2, len(run["t"]))))
    r = controller.apply({"flows": _flows()}, [{"id": "load"}, {"id": "pods"}], run, {})
    assert r["flows"] == _flows() and not r.get("controller")


def test_an_undeclared_side_is_not_used():
    run = _run()
    run["boundary"] = {"pods": {"in": ["estimate"], "out": []}}
    r = controller.apply({"flows": _flows()}, [{"id": "load"}, {"id": "pods"}], run, {})
    assert not r.get("controller")
