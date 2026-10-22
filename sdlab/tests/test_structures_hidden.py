"""structures' hidden-integrator rows (hidden.py, docs/research/fixes/310-structures.md)."""

import numpy as np

from sdlab.discovery.strategies.structures import hidden

STOCKS = [{"id": "w", "unit": "jobs"}, {"id": "p", "unit": "workers"}, {"id": "m", "unit": "GB"}]


TABLE = [[0.0, 0.0], [38.0, 0.0], [45.0, 0.6]]


def _run(n=400, drain=None):
    # m gains 20 + 0.3 h + 2 w / max(1, p) and loses 0.4 m; h (never measured) gains 1 and loses
    # h x table(w) (a share of it freed when w is high), or drain x h
    i = np.arange(n)
    w = 30 + 10 * np.sin(i / 9.0) + 5 * np.cos(i / 23.0)
    p = np.round(3 + 2 * np.sin(i / 31.0) + (i % 17 == 0))
    m, h = [60.0], 5.0
    for k in range(n - 1):
        m.append(m[-1] + 20 + 0.3 * h + 2 * w[k] / max(1.0, p[k]) - 0.4 * m[-1])
        d = drain if drain is not None else float(np.interp(w[k], *zip(*TABLE)))
        h = h + 1 - d * h
    lv = {"w": list(np.round(w, 4)), "p": list(p), "m": list(np.round(m, 4))}
    return {"t": list(range(n)), "levels": lv, "boundary_declared": True,
            "boundary": {"w": {"in": "input"}, "p": {"in": "input"}, "m": {"in": ["estimate"], "out": ["estimate"]}}}


def test_row_reads_a_hidden_integrator_and_a_per_unit_column():
    run = _run()
    # the answer already carries the table on another flow (as counted.py writes a threshold move)
    flows = [{"from": None, "to": "m", "rate": {"form": "linear", "c": 40.0, "terms": [{"stock": "w", "k": 0.5}]}},
             {"from": "m", "to": None, "rate": {"form": "proportional", "stock": "m", "k": 0.3}},
             {"from": "p", "to": None, "rate": {"form": "proportional", "stock": "p", "k": 0.0},
              "effects": [{"stock": "w", "shape": "table", "points": TABLE}]}]
    r = hidden.apply({"flows": flows}, STOCKS, run, {})
    note = r["hidden_rows"][0]
    assert note["kept"] and note["stock"] == "m"
    assert note["hidden"]["drain_table"] == "w"
    assert "w / max(1, p)" in note["columns"]
    out = next(f for f in r["flows"] if f.get("from") == "m" and f.get("to") is None)
    assert abs(out["rate"]["k"] - 0.4) < 1e-3
    assert {f.get("to") for f in r["flows"] if f.get("from") is None} >= {"m", "h_m"}
    assert len(r["inferred_levels"]["h_m"]) == len(run["t"])


def test_constant_drain_is_a_start_transient_not_a_hidden_stock():
    # with a constant drain the integrator is a constant plus its start's decay: nothing a row needs a stock for
    run = _run(drain=0.05)
    flows = [{"from": None, "to": "m", "rate": {"form": "linear", "c": 40.0, "terms": [{"stock": "w", "k": 0.5}]}},
             {"from": "m", "to": None, "rate": {"form": "proportional", "stock": "m", "k": 0.3}}]
    r = hidden.apply({"flows": flows}, STOCKS, run, {})
    assert not any(n.get("kept") for n in r.get("hidden_rows") or [])


def test_exact_row_is_left_alone():
    run = _run()
    n = len(run["t"])
    m = np.asarray(run["levels"]["m"])
    run["levels"]["m"] = list(np.round(np.concatenate([[m[0]], m[0] * 0.9 ** np.arange(1, n)]), 4))
    flows = [{"from": "m", "to": None, "rate": {"form": "proportional", "stock": "m", "k": 0.1}}]
    r = hidden.apply({"flows": flows}, STOCKS, run, {})
    assert r["flows"] == flows
