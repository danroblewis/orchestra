"""Experiment "shared noise": moves, links and co-flows told apart by which stocks' unexplained
changes share draws (sdlab/discovery/shared_noise.py, strategy `shared_noise`).

A move's one draw leaves its source and arrives in its destination in the same step, so their rows'
residuals mirror each other; a link's draw is its own; a co-flow's draw also takes `per` x itself
from the stock it uses. Where the average rates fit a move and a link equally well, the matrix
method reads a gain as a move whenever the source's drain can pay for it.
"""

from __future__ import annotations

import numpy as np
from synth import generate, skill

from sdlab.discovery.strategies import load

matrix, shared_noise = load("matrix"), load("shared_noise")


def prop(s, k):
    return {"form": "proportional", "stock": s, "k": k}


def lin(s, k):
    return {"form": "linear", "c": 0, "terms": [{"stock": s, "k": k}]}


def const(v):
    return {"form": "constant", "value": v}


def kind(r, a, b):
    """How a result reads the pair a, b: "move", "link" or None."""
    for f in r["flows"]:
        if f.get("driver") == a and f.get("to") == b:
            return "link"
        if f.get("from") == a and f.get("to") == b and not f.get("driver"):
            return "move"
    return None


def test_a_move_and_a_link_out_of_the_same_stock_at_the_same_rate():
    # a -> b (move, 0.1 x a), a => c (link, 0.1 x a: nothing leaves a), and a also loses 0.1 x a to
    # outside: a's drain (0.2) pays for both gains, so the averages fit "two moves" as well
    d = generate(stocks=[{"id": "a", "initial": 200}, {"id": "b", "initial": 100}, {"id": "c", "initial": 100}],
                 flows=[{"id": "in", "from": None, "to": "a", "rate": const(40)},
                        {"id": "ab", "from": "a", "to": "b", "rate": prop("a", 0.1)},
                        {"id": "ac", "from": None, "to": "c", "rate": lin("a", 0.1)},
                        {"id": "aout", "from": "a", "to": None, "rate": prop("a", 0.1)},
                        {"id": "bout", "from": "b", "to": None, "rate": prop("b", 0.2)},
                        {"id": "cout", "from": "c", "to": None, "rate": prop("c", 0.2)}],
                 schedule={"every": 400, "changes": [{"t": 1, "set": {"in": const(40)}}, {"t": 101, "set": {"in": const(120)}},
                                                     {"t": 201, "set": {"in": const(10)}}, {"t": 301, "set": {"in": const(70)}}]},
                 steps=2000)
    base = matrix(d["stocks"], d["run"], {})
    assert kind(base, "a", "c") == "move", "the matrix method reads the link as a move (a's drain can pay for it)"
    r = shared_noise(d["stocks"], d["run"], {})
    assert kind(r, "a", "b") == "move"
    assert kind(r, "a", "c") == "link"
    out = next(f for f in r["flows"] if f["from"] == "a" and f["to"] is None)
    assert abs(out["rate"]["k"] - 0.1) < 0.02, "the rest of a's drain goes outside"
    assert skill(r, d) > 0.97


def test_births_are_a_link_from_adults_not_a_move():
    # the population: children are born at 0.03 x adults (nothing leaves the adults), grow up at
    # 0.06 x children; adults retire at 0.025 and die at 0.01: their drain (0.035) could pay for the
    # births, and the matrix method reads them as a move adults -> children
    d = generate(stocks=[{"id": "children", "initial": 2000}, {"id": "adults", "initial": 5000}, {"id": "elderly", "initial": 1500}],
                 flows=[{"id": "births", "from": None, "to": "children", "rate": lin("adults", 0.03)},
                        {"id": "grow", "from": "children", "to": "adults", "rate": prop("children", 0.06)},
                        {"id": "retire", "from": "adults", "to": "elderly", "rate": prop("adults", 0.025)},
                        {"id": "adeath", "from": "adults", "to": None, "rate": prop("adults", 0.01)},
                        {"id": "death", "from": "elderly", "to": None, "rate": prop("elderly", 0.1)},
                        {"id": "migr", "from": None, "to": "adults", "rate": const(50)}],
                 schedule={"every": 300, "changes": [{"t": 1, "set": {"migr": const(50)}}, {"t": 101, "set": {"migr": const(400)}},
                                                     {"t": 201, "set": {"migr": const(0)}}]},
                 steps=2000)
    base = matrix(d["stocks"], d["run"], {})
    assert kind(base, "adults", "children") == "move"
    r = shared_noise(d["stocks"], d["run"], {})
    assert kind(r, "adults", "children") == "link"
    assert kind(r, "children", "adults") == "move"
    assert kind(r, "adults", "elderly") == "move"
    assert skill(r, d) > 0.95


def coflow_series(seed: int, steps: int = 2000) -> dict:
    """Made by hand with numpy: a -> b moves Poisson(0.2 x a) a step, and each unit moved uses up
    0.5 of c (the same draw leaves a, arrives in b and takes half of itself from c)."""
    rng = np.random.default_rng(seed)
    a, b, c = 100.0, 100.0, 400.0
    L = {"a": [], "b": [], "c": []}
    for t in range(steps):
        inflow = rng.poisson(30 if (t // 200) % 2 == 0 else 10)
        d = min(rng.poisson(0.2 * a), a, c / 0.5)
        out_b = rng.poisson(0.1 * b)
        a, b, c = a + inflow - d, b + d - out_b, c + rng.poisson(20) - 0.5 * d
        for k, v in (("a", a), ("b", b), ("c", c)):
            L[k].append(v)
    stocks = [{"id": s, "name": s, "unit": "things"} for s in ("a", "b")] + [{"id": "c", "name": "c", "unit": "litres"}]
    return {"stocks": stocks, "run": {"t": list(range(1, steps + 1)), "levels": L}}


def test_a_stock_that_mirrors_a_flow_draws_is_a_co_flow():
    for seed in (1, 2, 3):
        d = coflow_series(seed)
        base = matrix(d["stocks"], d["run"], {})
        assert any(f["from"] == "c" and f.get("driver") == "a" for f in base["flows"]), "the matrix method: c drains faster when a is high"
        r = shared_noise(d["stocks"], d["run"], {})
        ab = next(f for f in r["flows"] if f["from"] == "a" and f["to"] == "b")
        assert [u["stock"] for u in ab.get("uses") or []] == ["c"]
        assert abs(ab["uses"][0]["per"] - 0.5) < 0.08
        assert not any(f["from"] == "c" and f.get("driver") for f in r["flows"]), "the separate drain is gone"


def test_a_drain_that_only_follows_a_level_is_not_a_co_flow():
    # c loses 0.1 x a a step, drawn on its own: no shared draw with a -> b, so no `uses`
    d = generate(stocks=[{"id": "a", "initial": 100}, {"id": "b", "initial": 100}, {"id": "c", "initial": 400, "unit": "litres"}],
                 flows=[{"id": "in", "from": None, "to": "a", "rate": const(30)},
                        {"id": "ab", "from": "a", "to": "b", "rate": prop("a", 0.2)},
                        {"id": "bout", "from": "b", "to": None, "rate": prop("b", 0.1)},
                        {"id": "cin", "from": None, "to": "c", "rate": const(20)},
                        {"id": "cout", "from": "c", "to": None, "rate": lin("a", 0.1)}],
                 schedule={"every": 400, "changes": [{"t": 1, "set": {"in": const(30)}}, {"t": 201, "set": {"in": const(10)}}]},
                 steps=2000)
    r = shared_noise(d["stocks"], d["run"], {})
    assert not any(f.get("uses") for f in r["flows"])
    assert any(f["from"] == "c" and f.get("driver") == "a" for f in r["flows"])


def test_a_true_co_flow_from_the_ground_truth_engine():
    d = generate(stocks=[{"id": "a", "initial": 100}, {"id": "b", "initial": 100}, {"id": "c", "initial": 300}],
                 flows=[{"id": "in", "from": None, "to": "a", "rate": const(30)},
                        {"id": "ab", "from": "a", "to": "b", "rate": prop("a", 0.2), "uses": [{"stock": "c", "per": 0.5}]},
                        {"id": "bout", "from": "b", "to": None, "rate": prop("b", 0.1)},
                        {"id": "cin", "from": None, "to": "c", "rate": const(20)}],
                 schedule={"every": 400, "changes": [{"t": 1, "set": {"in": const(30)}}, {"t": 201, "set": {"in": const(10)}}]},
                 steps=2000)
    r = shared_noise(d["stocks"], d["run"], {})
    ab = next(f for f in r["flows"] if f["from"] == "a" and f["to"] == "b")
    assert abs(ab["uses"][0]["per"] - 0.5) < 0.08
    assert skill(r, d) > 0.97


def test_noise_free_data_decides_nothing_and_keeps_the_move():
    # a chain outside -> a -> b -> outside with no counting noise: the residuals are rounding only,
    # far below counting noise of the flows' sizes, so they say nothing about moves and links; the
    # averages' move a -> b stays (before, the empty covariances read as "link": a -> outside plus
    # outside -> b at 0.6 x a, kubernetes 301 none-*)
    d = generate(stocks=[{"id": "a", "initial": 300}, {"id": "b", "initial": 100}],
                 flows=[{"id": "in", "from": None, "to": "a", "rate": const(200)},
                        {"id": "ab", "from": "a", "to": "b", "rate": prop("a", 0.6)},
                        {"id": "bout", "from": "b", "to": None, "rate": prop("b", 0.5)}],
                 schedule={"every": 400, "changes": [{"t": 1, "set": {"in": const(200)}}, {"t": 101, "set": {"in": const(350)}},
                                                     {"t": 201, "set": {"in": const(120)}}, {"t": 301, "set": {"in": const(260)}}]},
                 steps=400, noise={})
    r = shared_noise(d["stocks"], d["run"], {})
    assert kind(r, "a", "b") == "move"
