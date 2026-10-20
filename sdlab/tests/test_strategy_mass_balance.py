"""Experiment mass_balance (docs/research/mass-balance-hidden.md): an unmeasured stock between two
measured ones, reconstructed from the unit's balance, on the smallest model that has one.

    a (measured) --0.2 x a--> h (NOT measured) --0.1 x h--> b (measured) --0.25 x b--> out

a is fed from outside at a rate that changes three times. The matrix method has no stock for h, so
it reads a's loss as a drain to outside (0.25, biased by a's 33 inflow pieces) and h's arrivals as
b's outside inflow in 12 pieces fitted to this run; fed the true inflow from other states, b is
wrong (skill@20 -25%). mass_balance pairs a's loss with b's arrivals, follows h's level through the
balance with a filter (sdlab/discovery/balance_filter.py), and finds a -> H -> b.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pytest
from synth import generate, skill

from sdlab.discovery.balance import reconstruct, scale_rate
from sdlab.discovery.observer import observe
from sdlab.discovery.identify import identify as main_line
from sdlab.discovery.strategies import load

_GRADE = Path(__file__).resolve().parent / "bench" / "grade.py"


def _grade():
    spec = importlib.util.spec_from_file_location("bench_grade_mb", _GRADE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def P(stock, k):
    return {"form": "proportional", "stock": stock, "k": k}


def C(v):
    return {"form": "constant", "value": v}


def one_hidden(steps=2000, stages=1, seed=1, changes=((400, 35), (900, 10), (1400, 25))):
    """a -> h -> b; with stages=2, h is two stages in a row (an Erlang-2 delay of the same mean)."""
    hs = [f"h{i}" for i in range(stages)]
    chain = ["a", *hs, "b"]
    k = [0.2] + [0.1 * stages] * stages
    flows = [{"id": "in", "from": None, "to": "a", "rate": C(20)}]
    flows += [{"id": f"f{i}", "from": x, "to": y, "rate": P(x, k[i])} for i, (x, y) in enumerate(zip(chain, chain[1:]))]
    flows.append({"id": "out", "from": "b", "to": None, "rate": P("b", 0.25)})
    return generate(
        stocks=[{"id": "a", "initial": 100}, *({"id": h, "initial": 200 / stages, "measured": False} for h in hs), {"id": "b", "initial": 80}],
        flows=flows, steps=steps, seed=seed,
        schedule={"every": 0, "changes": [{"t": t, "set": {"in": C(v)}} for t, v in changes]},
    )


@pytest.fixture(scope="module")
def data():
    return one_hidden()


@pytest.fixture(scope="module")
def found(data):
    return load("mass_balance")(data["stocks"], data["run"], {"eras": data["eras"]})


def test_the_plain_balance_recovers_a_noise_free_delay():
    # H(t) = H0 + alpha x cumsum(F) - cumsum(u), u = d x H: exact without counting noise
    rng = np.random.default_rng(0)
    F = np.repeat(rng.uniform(5, 30, 20), 100)
    H = np.zeros(len(F) + 1)
    H[0] = 50.0
    u = np.zeros(len(F))
    for t in range(len(F)):
        u[t] = 0.1 * H[t]
        H[t + 1] = H[t] + 0.6 * F[t] - u[t]
    rec = reconstruct(F, u)
    assert rec["alpha"] == pytest.approx(0.6, abs=1e-6)
    assert rec["d"] == pytest.approx(0.1, abs=1e-6)
    assert np.allclose(rec["H"], H, atol=1e-4)


def test_a_rate_scales_in_its_own_form():
    assert scale_rate(P("a", 0.2), 0.5)["k"] == pytest.approx(0.1)
    assert scale_rate({"form": "linear", "c": 2, "terms": [{"stock": "a", "k": 0.4}]}, 0.5) == {"form": "linear", "c": 1.0, "terms": [{"stock": "a", "k": 0.2}]}
    assert scale_rate({"form": "gap", "stock": "a", "goal": 10, "time": 4}, 0.5)["time"] == pytest.approx(8)


@pytest.mark.xfail(strict=True, reason="since the main line earns its pieces (docs/research/k8s-302.md) a's 33 pieces are 4 "
                   "and its drain 0.19 (was 0.25), b's arrivals 4 pieces; the balance's alpha comes out 1.135, over "
                   "plausible()'s 1.05, so no hidden stock (the ladder's 015, 026, 085 hidden cells still pass)")
def test_mass_balance_recovers_the_unmeasured_stock(data, found):
    r = found
    hidden = list(r.get("inferred_levels") or {})
    assert len(hidden) == 1, r["chosen"]
    h = hidden[0]
    into = [f for f in r["flows"] if f["to"] == h]
    out = [f for f in r["flows"] if f["from"] == h]
    assert [(f["from"], f["rate"]["form"]) for f in into] == [("a", "proportional")]
    assert [(f["to"], f["rate"]["form"]) for f in out] == [("b", "proportional")]
    assert into[0]["rate"]["k"] == pytest.approx(0.2, abs=0.02)            # found 0.215
    assert out[0]["rate"]["k"] == pytest.approx(0.1, abs=0.02)             # found 0.082
    drain = next(f for f in r["flows"] if f["from"] == "b" and f["to"] is None)
    assert drain["rate"]["k"] == pytest.approx(0.25, abs=0.02)             # found 0.268
    assert not [f for f in r["flows"] if f["to"] == "b" and f["from"] is None]   # no outside inflow into b
    assert not [f for f in r["flows"] if f["from"] == "a" and f["to"] is None]   # a loses only what H takes
    level = np.array(r["inferred_levels"][h])
    assert len(level) == len(data["run"]["t"])
    assert np.corrcoef(level, data["data"]["all_levels"]["h0"])[0, 1] > 0.95  # found 0.99
    assert skill(r, data, 20) > 0.8                                         # found 82% (seeds 2, 3: 98%, 88%)
    assert skill(r, data, 100) > 0.9                                        # found 95%


@pytest.mark.xfail(strict=True, reason="since the main line earns its pieces (docs/research/k8s-302.md) a's 33 pieces are 4 "
                   "and its drain 0.19 (was 0.25), b's arrivals 4 pieces; the balance's alpha comes out 1.135, over "
                   "plausible()'s 1.05, so no hidden stock (the ladder's 015, 026, 085 hidden cells still pass)")
def test_the_grader_counts_it_as_a_hidden_stock_and_reestimates_it_on_another_run(data, found):
    g = _grade()
    truth = {"rel": {"a>b": "hidden"}, "outside": {"in>a", "b>out"}}
    assert g.grade(found, truth)["right"] == 3
    other = one_hidden(seed=2)
    on_other = g.same_behaviour(found, other["model"], other["data"], horizon=20, own_run=False)["skill"]
    assert on_other > 0.8                                                   # found 84%
    # on another run the stored estimate (this run's) would be wrong: the grader asks the model
    h = list(found["inferred_levels"])[0]
    est = observe(found["flows"], ["a", "b"], other["run"]["t"], other["run"]["levels"], [h], {h: found["inferred_levels"][h][0]})
    assert np.corrcoef(est[h], other["data"]["all_levels"]["h0"])[0, 1] > 0.95


def test_the_matrix_reads_the_arrivals_as_pieces_and_misses(data):
    # the pinned main line (the matrix strategy's own now earns its pieces, docs/research/k8s-302.md:
    # b's arrivals in 4 pieces, skill@20 0.88)
    r = main_line(data["stocks"], data["run"], {"eras": data["eras"]})
    assert any(f["to"] == "b" and f["from"] is None and f.get("inflow") for f in r["flows"])
    assert skill(r, data, 20) < 0.5                                         # found -25%


@pytest.mark.xfail(strict=True, reason="since the main line earns its pieces (docs/research/k8s-302.md) a's 33 pieces are 4 "
                   "and its drain 0.19 (was 0.25), b's arrivals 4 pieces; the balance's alpha comes out 1.135, over "
                   "plausible()'s 1.05, so no hidden stock (the ladder's 015, 026, 085 hidden cells still pass)")
def test_two_stages_come_out_as_one_stock_with_the_mean_delay():
    d = one_hidden(stages=2)
    r = load("mass_balance")(d["stocks"], d["run"], {"eras": d["eras"]})
    assert len(r.get("inferred_levels") or {}) == 1, r["chosen"]
    m = load("matrix")(d["stocks"], d["run"], {"eras": d["eras"]})
    assert skill(r, d, 20) > skill(m, d, 20) + 0.3


def test_an_unrelated_loss_and_inflow_make_no_hidden_stock():
    # a really loses to outside; b is fed from outside on its own schedule
    d = generate(
        stocks=[{"id": "a", "initial": 100}, {"id": "b", "initial": 80}],
        flows=[{"id": "in", "from": None, "to": "a", "rate": C(20)}, {"id": "lost", "from": "a", "to": None, "rate": P("a", 0.2)},
               {"id": "feed", "from": None, "to": "b", "rate": C(20)}, {"id": "out", "from": "b", "to": None, "rate": P("b", 0.25)}],
        steps=2000,
        schedule={"every": 0, "changes": [{"t": 400, "set": {"in": C(35)}}, {"t": 700, "set": {"feed": C(8)}}, {"t": 900, "set": {"in": C(10)}},
                                          {"t": 1200, "set": {"feed": C(30)}}, {"t": 1400, "set": {"in": C(25)}}, {"t": 1700, "set": {"feed": C(15)}}]},
    )
    r = load("mass_balance")(d["stocks"], d["run"], {"eras": d["eras"]})
    assert not r.get("inferred_levels"), r["balance"]


def test_a_population_gets_no_hidden_stock():
    # births follow adults (a link), children grow up into adults, adults die: no delay to find
    d = generate(
        stocks=[{"id": "children", "initial": 300, "unit": "people"}, {"id": "adults", "initial": 1000, "unit": "people"}],
        flows=[{"id": "births", "from": None, "to": "children", "rate": {"form": "linear", "c": 0, "terms": [{"stock": "adults", "k": 0.02}]}},
               {"id": "grow", "from": "children", "to": "adults", "rate": P("children", 0.06)},
               {"id": "deaths", "from": "adults", "to": None, "rate": P("adults", 0.018)},
               {"id": "arrive", "from": None, "to": "adults", "rate": C(5)}],
        steps=1500,
        schedule={"every": 0, "changes": [{"t": 500, "set": {"arrive": C(25)}}, {"t": 1000, "set": {"arrive": C(0)}}]},
    )
    r = load("mass_balance")(d["stocks"], d["run"], {"eras": d["eras"]})
    assert not r.get("inferred_levels"), r["balance"]
