"""combined2's hidden first-order stage on an outside inflow (lagrow.py), docs/research/fixes/312-combined2.md."""

import numpy as np

from sdlab.discovery.strategies.combined2 import hinge, lagrow


def _setup(tau=3.0, n=400, staged=True):
    """`demand` fills from an input and drains at 0.2; `hosts` are ordered at 0.1 x max(0, demand - 8) a step,
    which join through a hidden stage emptying at 1 / tau (staged) or at once (not staged), and leave at
    0.05 x max(0, min(hosts - 2, hosts - demand / 2))."""
    t = np.arange(n + 1, dtype=float)
    inp = 1.4 + 1.2 * np.sin(2 * np.pi * t / 90)
    d, h, s = np.zeros(n + 1), np.zeros(n + 1), np.zeros(n + 1)
    d[0], h[0] = 6.0, 3.0
    for i in range(n):
        order = 0.1 * max(0.0, d[i] - 8.0)
        arrive = s[i] / tau if staged else order
        leave = 0.05 * max(0.0, min(h[i] - 2.0, h[i] - d[i] / 2))
        s[i + 1] = s[i] + order - s[i] / tau
        d[i + 1] = d[i] + inp[i + 1] - 0.2 * d[i]
        h[i + 1] = h[i] + arrive - leave
    run = {"t": list(t), "levels": {"demand": list(d), "hosts": list(h)}, "boundary_declared": True,
           "boundary": {"demand": {"in": ["input"], "out": ["estimate"]}, "hosts": {"in": ["estimate"], "out": ["estimate"]}}}
    stocks = [{"id": "demand", "unit": "jobs"}, {"id": "hosts", "unit": "hosts"}]
    flows = [{"from": None, "to": "demand", "ratio": 1, "input": "inp", "rate": {"form": "proportional", "stock": "inp", "k": 1.0}},
             {"from": "demand", "to": None, "ratio": 1, "rate": {"form": "proportional", "stock": "demand", "k": 0.2}},
             {"from": None, "to": "hosts", "ratio": 1, "rate": {"form": "linear", "c": 0.01, "terms": [{"stock": "demand", "k": 0.001}]}},
             {"from": "hosts", "to": None, "ratio": 1, "rate": {"form": "proportional", "stock": "hosts", "k": 0.002}}]
    return stocks, run, {"inputs": {"inp": list(inp)}}, flows


def test_a_staged_inflow_is_written_as_a_hidden_stage():
    stocks, run, opts, flows = _setup()
    r = lagrow.apply({"flows": flows}, stocks, run, opts)
    note = r["staged_rows"][0]
    assert note["stock"] == "hosts" and abs(note["tau"] - 3.0) < 0.03
    arrive = next(f for f in r["flows"] if f.get("to") == "hosts")
    assert arrive["from"] == "hosts_stage" and abs(arrive["rate"]["k"] - 1 / 3) < 0.005
    assert "hosts_stage" in r["inferred_levels"]
    levels, cols, n = hinge.columns(run, opts)
    assert note["sse"] < 1e-8 * float(np.sum(hinge.delta(levels, "hosts", n) ** 2))


def test_an_inflow_without_a_stage_is_not_staged():
    stocks, run, opts, flows = _setup(staged=False)
    r = lagrow.apply({"flows": flows}, stocks, run, opts)
    assert not r.get("staged_rows")
