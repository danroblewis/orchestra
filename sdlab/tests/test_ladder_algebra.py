"""algebra.py: proven equivalence of net rates (the user, 2026-10-21)."""

from __future__ import annotations

from sdlab.ladder import algebra


def P(a, b, stock, k, **kw):
    return {"from": a, "to": b, "rate": {"form": "proportional", "stock": stock, "k": k}, **kw}


def C(a, b, v):
    return {"from": a, "to": b, "rate": {"form": "constant", "value": v}}


def E(a, b, expr, **kw):
    return {"from": a, "to": b, "rate": {"form": "expr", "expr": expr}, **kw}


IDS = ["queue", "retries", "ready", "cpu", "desired"]
STATES = [{"queue": 50.0 + i, "retries": 4.0 + i % 3, "ready": 9.0, "cpu": 1500.0 + 10 * i, "desired": 9.0} for i in range(20)]


def run(truth, found, ids=IDS, wins=((1, 10),), **kw):
    return algebra.check(truth, found, ids, list(wins), states=STATES, **kw)


def test_309_move_against_link_and_drain():
    truth = [P("queue", "retries", "queue", 0.08), P("retries", "queue", "retries", 0.6), P("retries", None, "retries", 0.4)]
    found = [P("queue", "retries", "queue", 0.08), P(None, "queue", "retries", 0.6), P("retries", None, "retries", 1.0)]
    r = run(truth, found)
    assert r["equivalent"] and r["proven"], r
    assert r["method"] == "identity"


def test_move_against_outflow_and_inflow_pair_numbers_within_tolerance():
    truth = [P("retries", "queue", "retries", 0.6)]
    found = [P("retries", None, "retries", 0.601), P(None, "queue", "retries", 0.599)]
    assert run(truth, found)["equivalent"]


def test_a_true_difference():
    truth = [P("retries", "queue", "retries", 0.6)]
    found = [P("retries", None, "retries", 0.6), P(None, "queue", "retries", 0.5)]
    r = run(truth, found)
    assert r["proven"] and not r["equivalent"]
    d = r["differences"][0]
    assert d["stock"] == "queue" and d["term"] == "retries" and abs(d["found"] - 0.5) < 1e-12


def test_births_and_deaths_seen_as_their_difference():
    truth = [P(None, "queue", "queue", 0.3), P("queue", None, "queue", 0.1)]
    found = [P(None, "queue", "queue", 0.2)]
    assert run(truth, found)["equivalent"]


def test_floored_gap_against_inflow_and_drain_is_not_equivalent():
    # max(0, (100 - q) / 4) against 25 - 0.25 q unfloored: they differ where q > 100, which the run never reached
    truth = [{"from": None, "to": "queue", "rate": {"form": "gap", "goal": 100, "time": 4, "stock": "queue"}}]
    found = [C(None, "queue", 25.0), P("queue", None, "queue", 0.25)]
    r = run(truth, found)
    assert r["proven"] and not r["equivalent"]
    assert r["differences"][0]["at"]["queue"] > 100
    assert r["method"] == "regions"


def test_min_the_same_and_within_tolerance():
    truth = [E("queue", "retries", "min(0.6 * queue, 40 * ready)")]
    assert run(truth, [E("queue", "retries", "min(40 * ready, 0.6 * queue)")])["equivalent"]
    assert run(truth, [E("queue", "retries", "min(0.601 * queue, 40.03 * ready)")])["equivalent"]


def test_min_with_another_cap_or_only_one_arm():
    truth = [E("queue", "retries", "min(0.6 * queue, 40 * ready)")]
    r = run(truth, [E("queue", "retries", "min(0.6 * queue, 30 * ready)")])
    assert r["proven"] and not r["equivalent"] and r["method"] == "regions"
    r = run(truth, [P("queue", "retries", "queue", 0.6)])            # the cap never bound on the run
    assert r["proven"] and not r["equivalent"]


def test_max_floor_against_two_flows():
    # max(0, ready - desired) as one flow against the same written as an expression with a floor of its own
    truth = [E("ready", None, "max(0, ready - desired)")]
    assert run(truth, [E("ready", None, "ready - desired")])["equivalent"]      # every rate is floored at 0 anyway
    assert not run(truth, [{"from": "ready", "to": None, "two_way": True,
                            "rate": {"form": "linear", "c": 0, "terms": [{"stock": "ready", "k": 1}, {"stock": "desired", "k": -1}]}}])["equivalent"]


def test_step_functions_are_atoms():
    truth = [E(None, "desired", "max(0, min(16, ceil(cpu / 192.5)) - desired)")]
    assert run(truth, [E(None, "desired", "max(0, min(16, ceil(cpu / 192.5)) - desired)")])["equivalent"]
    r = run(truth, [E(None, "desired", "max(0, min(16, ceil(cpu / 150)) - desired)")])
    assert not r["equivalent"]


def test_table_effect_written_two_ways():
    tab = {"stock": "cpu", "shape": "table", "points": [[0, 0], [1000, 1], [3000, 1]]}
    truth = [{**P("queue", "retries", "queue", 0.5), "effects": [tab]}]
    same = E("queue", "retries", "0.5 * queue * lookup(cpu, [[0, 0], [1000, 1], [3000, 1]])")
    assert run(truth, [same])["equivalent"]
    other = E("queue", "retries", "0.5 * queue * lookup(cpu, [[0, 0], [2000, 1], [3000, 1]])")
    assert not run(truth, [other])["equivalent"]


def test_eras_per_window():
    truth = [{**C(None, "queue", 5.0), "byTime": [{"from": 1, "to": 5, "rate": {"form": "constant", "value": 5.0}},
                                                   {"from": 6, "to": 10, "rate": {"form": "constant", "value": 8.0}}]}]
    found = [{"from": None, "to": "queue", "inflow": [{"from": 1, "to": 5, "value": 5.0}, {"from": 6, "to": 10, "value": 8.0}]}]
    assert run(truth, found, wins=((1, 5), (6, 10)))["equivalent"]
    flat = [C(None, "queue", 6.5)]
    assert not run(truth, flat, wins=((1, 5), (6, 10)))["equivalent"]


def test_hidden_stock_not_covered():
    truth = [P("queue", "retries", "queue", 0.1)]
    found = [{"from": "queue", "to": "retries", "via": {"delay": 3}, "rate": {"form": "proportional", "stock": "queue", "k": 0.1}}]
    r = run(truth, found)
    assert not r["proven"] and not r["equivalent"] and r["method"] == "not covered"


def test_tolerance_from_close():
    truth = [P("retries", "queue", "retries", 0.6)]
    found = [P("retries", "queue", "retries", 0.65)]
    assert not run(truth, found)["equivalent"]
    assert run(truth, found, close=lambda s, m, a, b, w: abs(a - b) <= 0.1 * abs(a) + 1e-12)["equivalent"]


def test_bookkeeping_names_the_drawing_and_prefers_the_move():
    move, link, drain = ("flow", "retries", "queue", "retries"), ("flow", None, "queue", "retries"), ("flow", "retries", None, "retries")
    units = {"retries": "requests", "queue": "requests", "ready": "pods"}
    b = algebra.bookkeeping([{move: 0.6}], [{link: 0.6, drain: 0.6}], units)
    assert not b["conserving"] and "not conserving" in b["note"]
    b = algebra.bookkeeping([{link: 0.6, drain: 1.0}], [{move: 0.6, drain: 0.4}], units)
    assert b["conserving"] and "conserving" in b["note"]
    # across units, a move is never the drawing of the truth's link and outflow
    pod_move, pod_link, pod_drain = ("flow", "ready", "queue", "ready"), ("flow", None, "queue", "ready"), ("flow", "ready", None, "ready")
    b = algebra.bookkeeping([{pod_link: 2.0, pod_drain: 2.0}], [{pod_move: 2.0}], units)
    assert not b["conserving"] and b["unit_moves"]
