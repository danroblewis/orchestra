"""combined2's capacity-limit offer is a move (capmin._judge), docs/research/fixes/regress-combined2.md.

309/310 none-long regressed when capmin offered a pod controller's floored gaps (max(0, desired - pending - ready),
max(0, ready - desired)) as limits into outside or into a counter the declared boundary feeds from outside."""

import numpy as np

from sdlab.discovery.strategies.combined2 import capmin


def _gap(n=400, counter=False):
    """`want` (an input) sets `have`'s goal: have gains max(0, want - have) from outside a step and loses 0.2 x
    have to outside; `other` drifts. With counter: `made_total` (final, declared outside inflow) counts the gains."""
    t = np.arange(n + 1, dtype=float)
    want = 10 + 6 * np.sin(2 * np.pi * t / 60) + 3 * np.sin(2 * np.pi * t / 23)
    h, o, c = np.zeros(n + 1), np.zeros(n + 1), np.zeros(n + 1)
    h[0], o[0] = 8.0, 5.0
    for i in range(n):
        made = max(0.0, want[i] - h[i])
        h[i + 1] = h[i] + made - 0.2 * h[i]
        o[i + 1] = o[i] + 1.0 + 0.5 * np.sin(i / 7.0) - 0.2 * o[i]
        c[i + 1] = c[i] + made
    lv = {"have": list(h), "other": list(o)}
    stocks = [{"id": "have", "unit": "pods"}, {"id": "other", "unit": "pods"}]
    boundary = {"have": {"in": ["estimate"], "out": ["estimate"]}, "other": {"in": ["estimate"], "out": ["estimate"]}}
    if counter:
        lv["made_total"] = list(c)
        stocks.append({"id": "made_total", "unit": "pods", "final": True})
        boundary["made_total"] = {"in": ["estimate"]}
    run = {"t": list(t), "levels": lv, "boundary_declared": True, "boundary": boundary}
    return stocks, run, {"inputs": {"want": list(want)}}


def test_a_floored_outside_side_is_not_offered_as_a_limit():
    stocks, run, opts = _gap()
    o, cap = capmin.offer(stocks, run, opts)
    assert cap is None, cap
    assert not any(str(k).startswith(capmin.NAME) for k in o.get("inputs") or {})


def test_a_counter_fed_from_outside_receives_no_limit():
    stocks, run, opts = _gap(counter=True)
    assert capmin.counters_fed_from_outside(stocks, run) == {"made_total"}
    _, cap = capmin.offer(stocks, run, opts)
    caps = [] if cap is None else [cap] + list(cap.get("more") or [])
    assert not any(c.get("to") == "made_total" or c.get("to") is None for c in caps), caps


def test_undeclared_boundary_closes_nothing():
    stocks, run, _ = _gap(counter=True)
    assert capmin.counters_fed_from_outside(stocks, {**run, "boundary_declared": False}) == frozenset()
