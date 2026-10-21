"""Mechanism tests for the sindy strategy (experiment exp/pysindy, docs/DISCOVERY-EXPERIMENTS.md).

On the smallest synthetic models where the answer is exact: (a) a plain chain is recovered as the
matrix method recovers it; (b) a flow sped up by a third stock (cut = k x logs x sharpness / 100) is
found as a product term and read as a linear effect, where the matrix method finds no effect; (c) a
move into a noisy receiver: conservation as an equality constraint across rows, solved jointly,
takes the number from the row that measures it best, where the matrix method takes the receiver's.
(b) and (c) price a change in an outside inflow at 2 x log n (pelt_mult 2): at 1 x log n sharp's
changing inflow is over-cut and a product stands in for the rest.
"""

from __future__ import annotations

import pytest
from synth import generate, skill

pytest.importorskip("pysindy", reason="optional: uv sync --extra research")
pytest.importorskip("cvxpy", reason="optional: uv sync --extra research")

from sdlab.discovery import identify as matrix  # noqa: E402
from sdlab.discovery.strategies.sindy import _identify, identify  # noqa: E402


def find(r, a, b):
    return [f for f in r["flows"] if f["from"] == a and f["to"] == b and not f.get("inflow")]


def k(f):
    return f["rate"]["k"] if f["rate"]["form"] == "proportional" else f["rate"]["terms"][0]["k"]


def test_a_plain_chain_is_recovered_as_the_matrix_method_recovers_it():
    d = generate(stocks=[{"id": "a", "initial": 20}, {"id": "b", "initial": 10}],
                 flows=[{"id": "in", "from": None, "to": "a", "rate": {"form": "constant", "value": 6}},
                        {"id": "ab", "from": "a", "to": "b", "rate": {"form": "proportional", "stock": "a", "k": 0.3}},
                        {"id": "out", "from": "b", "to": None, "rate": {"form": "proportional", "stock": "b", "k": 0.2}}], steps=2000)
    r = identify(d["stocks"], d["run"])
    m = matrix(d["stocks"], d["run"])
    # matrix: a -> b 0.2835, b -> out 0.1927 (and a spurious 0.0067 x b out of a), skill@20 0.996
    # sindy:  a -> b 0.2827, b -> out 0.1927, nothing else, skill@20 0.955
    for res in (r, m):
        assert abs(k(find(res, "a", "b")[0]) - 0.3) <= 0.02 and abs(k(find(res, "b", None)[0]) - 0.2) <= 0.02
    assert not any(f.get("effects") for f in r["flows"]), "no product survives in a linear model"
    assert len([f for f in r["flows"] if not f.get("inflow")]) == 2
    assert skill(r, d) > 0.94


EFFECT = dict(stocks=[{"id": "logs", "initial": 40}, {"id": "planks", "initial": 10}, {"id": "sharp", "initial": 60, "unit": "points"}],
              flows=[{"id": "deliver", "from": None, "to": "logs", "rate": {"form": "constant", "value": 8}},
                     {"id": "cut", "from": "logs", "to": "planks", "rate": {"form": "proportional", "stock": "logs", "k": 0.3},
                      "effects": [{"stock": "sharp", "shape": "linear", "normal": 100, "max": 1}]},
                     {"id": "ship", "from": "planks", "to": None, "rate": {"form": "proportional", "stock": "planks", "k": 0.2}},
                     {"id": "sharpen", "from": None, "to": "sharp", "rate": {"form": "constant", "value": 3}},
                     {"id": "wear", "from": "sharp", "to": None, "rate": {"form": "proportional", "stock": "sharp", "k": 0.05}}],
              steps=3000, schedule={"every": 400, "changes": [{"t": 1, "set": {"sharpen": {"form": "constant", "value": 3}}},
                                                            {"t": 200, "set": {"sharpen": {"form": "constant", "value": 1}}}]})


def test_a_flow_sped_up_by_a_third_stock_is_found_as_a_product_and_read_as_a_linear_effect():
    d = generate(**EFFECT)
    r = identify(d["stocks"], d["run"], {"sindy": "constrained", "pelt_mult": 2})
    cut = find(r, "logs", "planks")
    assert len(cut) == 1 and cut[0]["rate"]["form"] == "proportional"
    eff = cut[0].get("effects") or []
    assert len(eff) == 1 and eff[0]["stock"] == "sharp" and eff[0]["shape"] == "linear"
    per_unit = cut[0]["rate"]["k"] / eff[0]["normal"]                 # truth: 0.3 / 100 per log per point
    assert abs(per_unit - 0.003) <= 0.0004
    assert abs(k(find(r, "planks", None)[0]) - 0.2) <= 0.02 and abs(k(find(r, "sharp", None)[0]) - 0.05) <= 0.01
    assert not [f for f in r["flows"] if f.get("driver")], "conservation leaves no link beside the move"
    # sindy: skill@20 0.86, @100 0.95. matrix: no effect anywhere, logs -> planks 0.08 x logs plus
    # links from sharp (logs -> out 0.14 x sharp, into planks 0.18 x sharp); skill@20 -2.6, @100 0.57
    m = matrix(d["stocks"], d["run"], {"eras": d["eras"]})
    assert not any(f.get("effects") for f in m["flows"])
    assert skill(r, d) > 0.8 and skill(m, d) < 0
    assert skill(r, d, 100) > 0.9 > skill(m, d, 100)


NOISY_RECEIVER = dict(
    stocks=[{"id": "a", "initial": 20}, {"id": "b", "initial": 100}],
    flows=[{"id": "in_a", "from": None, "to": "a", "rate": {"form": "constant", "value": 4}},
           {"id": "ab", "from": "a", "to": "b", "rate": {"form": "proportional", "stock": "a", "k": 0.3}},
           {"id": "in_b", "from": None, "to": "b", "rate": {"form": "constant", "value": 60}},
           {"id": "out", "from": "b", "to": None, "rate": {"form": "proportional", "stock": "b", "k": 0.5}}],
    steps=1500, schedule={"every": 600, "changes": [{"t": 1, "set": {"in_a": {"form": "constant", "value": 4}}},
                                                    {"t": 150, "set": {"in_a": {"form": "constant", "value": 12}}},
                                                    {"t": 300, "set": {"in_a": {"form": "constant", "value": 2}}},
                                                    {"t": 450, "set": {"in_a": {"form": "constant", "value": 8}}}]})


def test_conservation_across_rows_takes_a_move_from_the_row_that_measures_it_best():
    # a's row is quiet (small flows), b's row noisy (60 a step in and out besides a's 0.3 x a): the
    # move a -> b is measured well in a's row and poorly in b's. a's inflow changes, so the matrix
    # method trusts the receiver and sets a's drain to b's reading.
    d = generate(**NOISY_RECEIVER)
    r = identify(d["stocks"], d["run"], {"sindy": "constrained", "pelt_mult": 2})
    # the ablation as its search leaves it (identify's boundary step prices that link as a boundary
    # claim not earned, and drops it)
    free = _identify(d["stocks"], d["run"], {"sindy": "products", "pelt_mult": 2})
    m = matrix(d["stocks"], d["run"])
    assert r["conservation"]["kept"] == ["a"]
    assert abs(k(find(r, "a", "b")[0]) - 0.3) <= 0.005                # joint: 0.2997
    assert not find(r, None, "b") and not find(r, "a", None)
    assert find(free, None, "b"), "without the constraint, b's own reading leaves a link beside the move"
    assert abs(k(find(m, "a", "b")[0]) - 0.3) > 0.02                  # matrix: 0.3294
    assert skill(r, d) > 0.85 > skill(m, d)                            # sindy 0.87, matrix 0.39
