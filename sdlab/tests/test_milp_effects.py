"""milp's table-effect flows (effects.py, k8s-310): a counted move switched on by a level past a threshold
recovered from an answer that has a small constant in its place; a plain model left alone."""

import numpy as np

from sdlab.discovery.strategies.milp import effects


def _model(n=300, kill=True):
    k = np.arange(n)
    level = 400 + 90 * np.sin(k / 15.0)                    # the driver (MiB), measured
    ready, pending, kills = np.zeros(n), np.zeros(n), np.zeros(n)
    ready[0], pending[0] = 10.0, 2.0
    for i in range(n - 1):
        killed = ready[i] * 0.01 * max(0.0, level[i] - 470) if kill else 0.0
        started = 0.5 * pending[i]
        ready[i + 1] = ready[i] + started - killed
        pending[i + 1] = pending[i] + 1.0 + killed - started
        kills[i + 1] = kills[i] + killed
    stocks = [{"id": "ready", "unit": "pods"}, {"id": "pending", "unit": "pods"}, {"id": "kills", "unit": "pods", "final": True},
              {"id": "mem", "unit": "MiB"}]
    run = {"t": list(range(n)), "levels": {"ready": list(ready), "pending": list(pending), "kills": list(kills), "mem": list(level)},
           "boundary": {"pending": {"in": ["estimate"]}, "kills": {"in": ["estimate"]}, "mem": {"in": ["estimate"], "out": ["estimate"]}},
           "boundary_declared": True}
    return stocks, run


def _answer():
    return [{"from": "pending", "to": "ready", "ratio": 1, "rate": {"form": "proportional", "stock": "pending", "k": 0.5}},
            {"from": None, "to": "pending", "ratio": 1, "rate": {"form": "constant", "value": 1.0}},
            {"from": None, "to": "kills", "ratio": 1, "rate": {"form": "constant", "value": 0.05}}]


def test_counted_move_recovered():
    stocks, run = _model()
    flows, note = effects.refine(_answer(), stocks, run, {})
    eff = [f for f in flows if f.get("effects")]
    assert {(f["from"], f["to"]) for f in eff} == {("ready", "pending"), (None, "kills")}, note
    pts = eff[0]["effects"][0]["points"]
    hinge = next(x for (x, y), (x2, y2) in zip(pts, pts[1:]) if y == 0 and y2 > 0)
    assert abs(hinge - 470) < 2.0
    assert not any(f["to"] == "kills" and not f.get("effects") for f in flows)   # the constant it replaces is gone


def test_no_effect_left_alone():
    stocks, run = _model(kill=False)
    ans = _answer()[:2]
    flows, note = effects.refine(ans, stocks, run, {})
    assert not any(f.get("effects") for f in flows), note
