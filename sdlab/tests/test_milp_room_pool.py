"""milp (k8s-316): a pool with a constant ceiling, MIN(a x S, b - e x D), between stocks of two units the declared
boundary closes (queries waiting acquire connections): the move is offered across units, recovered from an answer
whose inflow into the waiting stock took the room's misfit, and the inflow re-read from its true readers."""

import re

import numpy as np

from sdlab.discovery.strategies.milp import room
from sdlab.discovery.strategies.milp.steps import Steps


def _model(n=300):
    k = np.arange(n)
    calls = 400.0 + 350.0 * np.sin(k / 15.0) ** 2                # the callers' requests in flight (measured)
    other = 200.0 + 100.0 * np.cos(k / 7.0)
    waiting, active = np.zeros(n), np.zeros(n)
    waiting[0], active[0] = 10.0, 60.0
    for i in range(n - 1):
        acq = min(0.8 * waiting[i], 80 - 0.2 * active[i])
        waiting[i + 1] = waiting[i] + 0.1 * calls[i] + 0.05 * other[i] - acq
        active[i + 1] = active[i] + acq - 0.8 * active[i]
    stocks = [{"id": "waiting", "unit": "queries"}, {"id": "active", "unit": "connections"},
              {"id": "calls", "unit": "requests"}, {"id": "other", "unit": "requests"}]
    run = {"t": list(range(n)), "levels": {"waiting": list(waiting), "active": list(active), "calls": list(calls), "other": list(other)},
           "boundary": {"waiting": {"in": ["estimate"]}, "active": {"out": ["estimate"]}}, "boundary_declared": True}
    return stocks, run, {}


def test_boundary_forces_a_move_across_units():
    stocks, run, opts = _model()
    st = Steps(stocks, run, opts)
    assert st.same_unit("waiting", "active")                       # each alone in its unit, the sides closed
    assert not st.same_unit("active", "waiting")                   # active has a declared outside outflow
    assert not st.same_unit("calls", "waiting")                    # waiting has a declared outside inflow
    undeclared = Steps(stocks, {k: v for k, v in run.items() if not k.startswith("boundary")}, opts)
    assert not undeclared.same_unit("waiting", "active")


def test_pool_with_constant_ceiling_recovered():
    stocks, run, opts = _model()
    answer = [{"from": "waiting", "to": "active", "ratio": 1, "rate": {"form": "proportional", "stock": "waiting", "k": 0.3}},
              {"from": None, "to": "waiting", "ratio": 1,
               "rate": {"form": "linear", "c": 5.0, "terms": [{"stock": "calls", "k": 0.08}, {"stock": "active", "k": 0.1}]}},
              {"from": "active", "to": None, "ratio": 1, "rate": {"form": "proportional", "stock": "active", "k": 0.5}}]
    flows, note = room.refine(answer, stocks, run, opts)
    rm = [f for f in flows if f.get("room_fit")]
    assert len(rm) == 1 and (rm[0]["from"], rm[0]["to"]) == ("waiting", "active"), note
    m = re.fullmatch(r"min\(([\d.e+-]+) \* waiting, ([\d.e+-]+) - ([\d.e+-]+) \* active\)", rm[0]["rate"]["expr"])
    assert m, rm[0]["rate"]["expr"]                                # the room never reaches 0 on the run: no floor written
    a, b, e = (float(x) for x in m.groups())
    assert abs(a - 0.8) < 0.01 and abs(b - 80) < 0.5 and abs(e - 0.2) < 0.01
    inflow = next(f for f in flows if f["from"] is None and f["to"] == "waiting")
    assert {t["stock"] for t in inflow["rate"]["terms"]} == {"calls", "other"}, inflow


def test_tidy_rereads_inflows_and_drops_a_needless_move():
    from sdlab.discovery.strategies.milp import tidy
    stocks, run, opts = _model()
    answer = [{"from": "waiting", "to": "active", "ratio": 1, "id": "r", "room_fit": {"ceiling": None, "a": 0.8, "b": 80.0, "e": 0.2},
               "rate": {"form": "expr", "expr": "min(0.8 * waiting, 80 - 0.2 * active)"}},
              {"from": None, "to": "waiting", "ratio": 1, "id": "i",
               "rate": {"form": "linear", "c": 3.0, "terms": [{"stock": "calls", "k": 0.09}, {"stock": "active", "k": 0.05}]}},
              {"from": "active", "to": None, "ratio": 1, "id": "o", "rate": {"form": "proportional", "stock": "active", "k": 0.8}},
              {"from": "calls", "to": "other", "ratio": 1, "id": "m", "rate": {"form": "proportional", "stock": "calls", "k": 0.001}}]
    flows, note = tidy.refine(answer, stocks, run, opts)
    inflow = next(f for f in flows if f["from"] is None and f["to"] == "waiting")
    assert {t["stock"] for t in inflow["rate"]["terms"]} == {"calls", "other"}, note
    assert not any((f["from"], f["to"]) == ("calls", "other") for f in flows), note
    assert any(f.get("room_fit") for f in flows)
