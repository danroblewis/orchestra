"""Strategies built when past ideas were revisited on the ladder (docs/research/revisit.md):
gap_prior (a drain read by another stock written as the goal gap or co-flow it equals, where the
data cannot tell), lna_loops (loop-closing links kept when the likelihood does not rule them out), lna_pulses
(pulses found first, lna on what they leave), lna_levels (inflow pieces as a few recurring
levels), lna_products and lna_stack (all of them in one model) (moves scaled by a third stock in
lna's likelihood)."""

from __future__ import annotations

import numpy as np
import pytest

from sdlab.discovery.strategies.gap_prior import as_coflows, as_gaps, one_number
from sdlab.discovery.strategies.lna_levels.levels import kmeans_1d, viterbi
from sdlab.discovery.strategies.lna_pulses import pooled
from sdlab.ladder import cases as casemod
from sdlab.ladder import data
from sdlab.ladder.runner import discover


def _run(strategy: str, case: str, variant: str) -> dict:
    c = casemod.load(case)
    return discover(strategy, casemod.truth_model(c, variant), data.load(c, variant))


def _ends(r: dict) -> set[tuple]:
    out = set()
    for f in r["flows"]:
        rate = f["rate"]
        reads = rate.get("stock") or ",".join(t["stock"] for t in rate.get("terms") or [])
        out.add((f["from"], f["to"], reads))
    return out


def test_drain_read_by_another_stock_becomes_a_gap():
    flows = [{"from": None, "to": "P", "rate": {"form": "constant", "value": 60.0}, "perStep": 60.0,
              "inflow": [{"from": 2, "to": 100, "value": 60.0}, {"from": 101, "to": 300, "value": 60.0000001}]},
             {"from": "P", "to": None, "rate": {"form": "linear", "c": 0, "terms": [{"stock": "I", "k": 0.2}]}, "perStep": 40.0},
             {"from": "I", "to": None, "rate": {"form": "proportional", "stock": "I", "k": 0.1}, "perStep": 20.0}]
    out = as_gaps(flows)
    assert len(out) == 2
    gap = next(f for f in out if f["from"] is None)
    assert gap["rate"] == {"form": "linear", "c": pytest.approx(60.0), "terms": [{"stock": "I", "k": -0.2}]}
    assert "inflow" not in gap


def test_own_drains_and_real_pieces_are_left_alone():
    flows = [{"from": None, "to": "A", "rate": {"form": "constant", "value": 10.0}, "inflow": [{"from": 2, "to": 100, "value": 5.0}, {"from": 101, "to": 300, "value": 15.0}]},
             {"from": "A", "to": None, "rate": {"form": "linear", "c": 0, "terms": [{"stock": "B", "k": 0.2}]}}]
    assert as_gaps(flows) == flows                      # the inflow is two numbers: no single c
    own = [{"from": None, "to": "A", "rate": {"form": "constant", "value": 10.0}},
           {"from": "A", "to": None, "rate": {"form": "proportional", "stock": "A", "k": 0.2}}]
    assert as_gaps(own) == own
    assert one_number([{"value": 1.0}, {"value": 1.00000001}]) and not one_number([{"value": 1.0}, {"value": 1.1}])


def test_drain_read_by_a_moving_stock_becomes_a_coflow():
    flows = [{"from": "A", "to": "B", "rate": {"form": "proportional", "stock": "A", "k": 0.3}},
             {"from": "R", "to": None, "rate": {"form": "linear", "c": 0, "terms": [{"stock": "A", "k": 0.15}]}},
             {"from": None, "to": "R", "rate": {"form": "constant", "value": 8.0}}]
    out = as_coflows(flows)
    assert len(out) == 2 and out[0]["uses"] == [{"stock": "R", "per": pytest.approx(0.5)}]
    assert as_gaps(out) == out                          # the drain went into the co-flow, not a gap


def test_gap_prior_on_the_goal_gap_without_noise():
    r = _run("gap_prior", "011-goal-gap", "none-short")
    assert (None, "P", "I") in _ends(r) and ("P", None, "I") not in _ends(r)


def test_gap_prior_on_the_coflow_without_noise():
    move = next(f for f in _run("gap_prior", "016-coflow", "none-short")["flows"] if f["from"] == "A" and f["to"] == "B")
    assert move["uses"][0]["stock"] == "R" and move["uses"][0]["per"] == pytest.approx(0.5, rel=0.02)


def test_gap_prior_leaves_noisy_runs_to_lna():
    assert _run("gap_prior", "011-goal-gap", "counts-short")["flows"] == _run("lna", "011-goal-gap", "counts-short")["flows"]


def test_loop_closing_link_kept():
    r = _run("lna_loops", "046-random-link-loop#3", "counts-short")
    assert (None, "A", "B") in _ends(r) and ("A", "B", "A") in _ends(r)


def test_pulses_found_and_the_chain_read_around_them():
    for variant in ("none-short", "counts-short"):
        r = _run("lna_pulses", "022-pulse", variant)
        assert ("A", "B", "A") in _ends(r)
        assert r["pulses"] == {"A": 3}


def test_no_pulses_no_change():
    assert _run("lna_pulses", "003-chain-2", "counts-short")["flows"] == _run("lna", "003-chain-2", "counts-short")["flows"]


def test_pulses_of_one_size_pooled():
    r = np.zeros(300)
    hit = np.zeros(300, bool)
    hit[[50, 150, 250]] = True
    r[hit] = [281.0, 300.0, 305.0]
    out = pooled(r, hit, np.full(300, 10.0), 3.0, counts=True)
    assert np.allclose(out[hit], out[50]) and out[50] == pytest.approx(295.0, abs=3)
    r[250] = 900.0                                      # not one size: left as measured
    assert pooled(r, hit, np.full(300, 10.0), 3.0, counts=True)[250] == 900.0


def test_linear_effect_found_with_counting_noise():
    r = _run("lna_products", "017-linear-effect", "counts-short")
    move = next(f for f in r["flows"] if f["from"] == "A" and f["to"] == "B")
    assert [e["stock"] for e in move.get("effects") or []] == ["C"]


def test_no_effect_where_there_is_none():
    r = _run("lna_products", "014-split", "counts-short")
    assert not any(f.get("effects") for f in r["flows"])


def test_kmeans_1d_and_viterbi():
    assert kmeans_1d(np.array([4.0, 19.0, 4.2, 18.5, 3.9]), np.ones(5), 2) in ([0, 1, 0, 1, 0], [1, 0, 1, 0, 1])
    rng = np.random.default_rng(1)
    truth = np.repeat([0, 1, 0, 1], 100)
    u = np.where(truth == 1, 19.0, 4.0) + rng.normal(0, 2.0, 400)
    path = viterbi(u, np.full(400, 0.1), np.array([4.0, 19.0]), np.log(400))
    assert (path != truth).sum() <= 4


def test_square_wave_inflow_as_two_levels():
    r = _run("lna_levels", "048-random-stepping-inflow-drain#1", "counts-short")
    assert r["levels"] == {"C": 2}
    inflow = next(f for f in r["flows"] if f["from"] is None and f["to"] == "C")
    assert len({p["value"] for p in inflow["inflow"]}) == 2


def test_births_not_read_as_a_stepping_inflow():
    fl = _ends(_run("lna_levels", "009-births-and-deaths", "counts-long"))
    assert (None, "P", "P") in fl


def test_stack_effect_and_square_wave_together():
    r = _run("lna_stack", "017-linear-effect", "counts-long")
    move = next(f for f in r["flows"] if f["from"] == "A" and f["to"] == "B")
    assert [e["stock"] for e in move.get("effects") or []] == ["C"]
    assert r["levels"] == {"C": 2}
