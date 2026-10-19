"""The structures strategy (sdlab/discovery/strategies/structures): its Erlang chain matches the
engine's compiled DELAYn, and its search recovers the canonical structures it was built for: a
product of two stocks, a goal gap over several stocks with a floor, and a hidden delay chain."""

import json

import numpy as np
import pytest

from sdlab.discovery.strategies import structures
from sdlab.discovery.strategies.structures.terms import erlang, init_response, stage_contents
from sdlab.ladder import cases as casemod
from sdlab.ladder import data, score
from sdlab.ladder.runner import discover


@pytest.fixture(autouse=True)
def cache(tmp_path, monkeypatch):
    monkeypatch.setenv("SDLAB_LADDER_CACHE", str(tmp_path / "ladder"))
    monkeypatch.setenv("SDLAB_STRUCTURES", json.dumps({"alone": True}))


def run_case(case_prefix, variant):
    cid = next(c for c in casemod.case_ids() if c.startswith(case_prefix))
    c = casemod.load(cid)
    model = casemod.truth_model(c, variant)
    d = data.load(c, variant)
    r = discover("structures", model, d)
    s = score.equations(c, casemod.variant(c, variant)["noise"], model, json.loads(json.dumps(r["flows"], default=float)), d)
    return r, s


def test_erlang_chain_is_the_engines_stages():
    rng = np.random.default_rng(1)
    z = rng.uniform(0, 10, 200)
    n, tau = 3, 6.0
    H = stage_contents(z, np.zeros(n), n, tau)
    assert np.allclose(erlang(z, n, tau), (n / tau) * H[-1, :-1])
    # one unit in stage 0 at the start: what the chain delivers, all of it eventually
    h0 = init_response(400, n, tau, 0)
    assert abs(h0.sum() - 1.0) < 1e-6 and h0[0] == 0.0


def test_logistic_crowding_is_a_drain_times_its_own_level():
    r, s = run_case("103", "counts-short")
    assert s["status"] == "pass", s


def test_bass_word_of_mouth_is_a_product_without_noise():
    r, s = run_case("102", "none-short")
    assert s["status"] == "pass", s


def test_hiring_closes_one_gap_over_two_stocks_and_an_input():
    r, s = run_case("106", "none-short")
    assert s["status"] == "pass", s
    hiring = [f for f in r["flows"] if f["from"] is None and f["to"] == "Rookies"]
    assert len(hiring) == 1 and hiring[0]["rate"]["form"] == "linear"


def test_a_third_order_delay_fed_by_an_input_is_found():
    r, s = run_case("110", "none-short")
    assert s["status"] == "pass", s
    assert len(r["inferred_levels"]) == 3
    assert abs(r["trace"]["chain"]["delay"] - 20) < 0.05 and r["trace"]["chain"]["order"] == 3


def test_identify_returns_the_base_without_its_own_model(monkeypatch):
    monkeypatch.setenv("SDLAB_STRUCTURES", json.dumps({"base": "combined", "seconds": 0.0}))
    t = list(range(1, 41))
    run = {"t": t, "levels": {"A": [float(10 + i % 3) for i in t]}}
    out = structures.identify([{"id": "A"}], run, {"specialists": ["lna"]})
    assert "flows" in out and out["structures"]["chosen"] == "combined"
