"""milp's hidden integrators (hidden.py, k8s-310): a stock whose inflow reads a hidden stock (filled at a
constant, drained in proportion to itself) gets that stock; a row explained by measured columns gets none."""

import numpy as np

from sdlab.discovery.strategies.milp import hidden


def _model(n=600, leak=True):
    k = np.arange(n)
    x = 200 + 80 * np.sin(k / 23.0)                         # requests, measured
    y = 8 + 3 * np.sin(k / 41.0 + 1.0)                      # pods, measured
    h, m = 0.0, np.zeros(n)
    m[0] = 300.0
    for i in range(n - 1):
        m[i + 1] = m[i] + 50 + (0.5 * h if leak else 0.0) + 1.0 * x[i] / max(1.0, y[i]) - 0.5 * m[i]
        h = h + 1.0 - 0.02 * h
    stocks = [{"id": "x", "unit": "requests"}, {"id": "y", "unit": "pods"}, {"id": "m", "unit": "MiB"}]
    run = {"t": list(range(n)), "levels": {"x": list(x), "y": list(y), "m": list(m)},
           "boundary": {"m": {"in": ["estimate"], "out": ["estimate"]}}, "boundary_declared": True}
    answer = [{"from": None, "to": "m", "ratio": 1, "rate": {"form": "linear", "c": 60.0, "terms": [{"stock": "x", "k": 0.1}]}},
              {"from": "m", "to": None, "ratio": 1, "rate": {"form": "proportional", "stock": "m", "k": 0.45}}]
    return stocks, run, answer


def test_hidden_integrator_recovered():
    stocks, run, answer = _model()
    flows, note = hidden.refine(answer, stocks, run, {})
    hid = [f for f in flows if f["to"] == "m_hidden" or f["from"] == "m_hidden"]
    assert len(hid) == 2, note
    drain = next(f for f in hid if f["from"] == "m_hidden")
    assert abs(drain["rate"]["k"] - 0.02) < 1e-3
    inflow = next(f for f in flows if f["from"] is None and f["to"] == "m")
    assert "m_hidden" in inflow["rate"]["expr"] and "x / max(1, y)" in inflow["rate"]["expr"]
    out = next(f for f in flows if f["from"] == "m" and f["to"] is None)
    assert abs(out["rate"]["k"] - 0.5) < 1e-3


def test_no_hidden_stock_where_measured_columns_explain():
    stocks, run, answer = _model(leak=False)
    flows, note = hidden.refine(answer, stocks, run, {})
    assert not any("m_hidden" in (f["from"], f["to"]) for f in flows)
