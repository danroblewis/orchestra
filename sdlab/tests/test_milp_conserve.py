"""milp's conserving rewrites (conserve.py, k8s-317): a same-unit link beside a drain becomes the move, an
own-level gap on an inflow becomes the drain; nothing changes where the floor would differ."""

import numpy as np

from sdlab.discovery.strategies.milp import conserve


def _run(n=50):
    t = np.arange(n, dtype=float)
    q = 50 + 10 * np.sin(t / 5)
    r = 20 + 5 * np.cos(t / 7)
    c = 300 + 50 * np.sin(t / 4)
    stocks = [{"id": "q", "unit": "req"}, {"id": "r", "unit": "req"}, {"id": "c", "unit": "mc"}]
    run = {"t": list(t), "levels": {"q": list(q), "r": list(r), "c": list(c)},
           "boundary": {"q": {"in": ["estimate"]}, "r": {"out": ["estimate"]}, "c": {"in": ["estimate"], "out": ["estimate"]}},
           "boundary_declared": True}
    return stocks, run


def _lin(c0, **k):
    return {"form": "linear", "c": c0, "terms": [{"stock": s, "k": v} for s, v in k.items()]}


def test_link_becomes_move_and_gap_becomes_drain():
    stocks, run = _run()
    flows = [{"from": None, "to": "q", "rate": _lin(5.0, r=0.6)},
             {"from": "r", "to": None, "rate": {"form": "proportional", "stock": "r", "k": 1.0}},
             {"from": None, "to": "c", "rate": _lin(0.0, q=10.0, c=-0.25)},
             {"from": "c", "to": None, "rate": {"form": "proportional", "stock": "c", "k": 0.25}}]
    out, notes = conserve.refine(flows, stocks, run, {})
    by = {(f["from"], f["to"]): f["rate"] for f in out}
    assert by[("r", "q")] == {"form": "proportional", "stock": "r", "k": 0.6}
    assert abs(by[("r", None)]["k"] - 0.4) < 1e-9
    assert by[(None, "q")] == {"form": "constant", "value": 5.0}
    assert by[(None, "c")] == {"form": "proportional", "stock": "q", "k": 10.0}
    assert abs(by[("c", None)]["k"] - 0.5) < 1e-9
    assert len(notes["rewrites"]) == 2


def test_no_rewrite_where_the_floor_binds():
    stocks, run = _run()
    flows = [{"from": None, "to": "c", "rate": _lin(-100.0, q=1.0, c=-0.25)},   # without the gap: negative on some steps
             {"from": "c", "to": None, "rate": {"form": "proportional", "stock": "c", "k": 0.25}}]
    out, notes = conserve.refine(flows, stocks, run, {})
    assert notes == {}
