"""combined2 (sdlab/discovery/strategies/combined2, docs/research/combined2.md): the held-inflow
forecast judge, the discrete likelihood for small counts, the screens, and the stages on a few
cells they were built for."""

from __future__ import annotations

import json
import math

import numpy as np
import pytest

from sdlab.discovery.simulate import behaviour_error
from sdlab.discovery.strategies.combined2 import judge as J2
from sdlab.discovery.strategies.combined2 import screens
from sdlab.discovery.strategies.combined2._vendored.combined import judge as J
from sdlab.discovery.strategies.combined2.forecast import held_error
from sdlab.ladder import cases as casemod
from sdlab.ladder import data, score
from sdlab.ladder.runner import discover


@pytest.fixture(autouse=True)
def cache(tmp_path, monkeypatch):
    monkeypatch.setenv("SDLAB_LADDER_CACHE", str(tmp_path / "ladder"))


def _run(levels: dict, T: int) -> dict:
    return {"t": list(range(T)), "levels": levels}


def test_held_error_is_behaviour_error_without_pieces():
    rng = np.random.default_rng(0)
    T = 200
    a = [50.0]
    for _ in range(T - 1):
        a.append(a[-1] + 10 - 0.2 * a[-1] + rng.normal(0, 1))
    flows = [{"from": None, "to": "A", "rate": {"form": "constant", "value": 10.0}},
             {"from": "A", "to": None, "rate": {"form": "proportional", "stock": "A", "k": 0.2}}]
    run = _run({"A": a}, T)
    assert math.isclose(held_error(flows, ["A"], run["t"], run["levels"], 20), behaviour_error(flows, ["A"], run["t"], run["levels"], 20))


def test_pieces_that_follow_the_data_do_not_help_when_held():
    """A wrong model (no drain) whose inflow pieces copy the data's every change looks perfect when it
    replays its pieces, and runs off when they are held at the start of each forecast."""
    T = 200
    a = [0.0]
    for _ in range(T - 1):
        a.append(a[-1] + 10 - 0.2 * a[-1])
    d = np.diff(a)
    wrong = [{"from": None, "to": "A", "inflow": [{"from": k + 1, "to": k + 1, "value": float(max(0.0, d[k]))} for k in range(T - 1)]}]
    right = [{"from": None, "to": "A", "rate": {"form": "constant", "value": 10.0}},
             {"from": "A", "to": None, "rate": {"form": "proportional", "stock": "A", "k": 0.2}}]
    run = _run({"A": a}, T)
    own_w = behaviour_error(wrong, ["A"], run["t"], run["levels"], 20)
    held_w = held_error(wrong, ["A"], run["t"], run["levels"], 20)
    held_r = held_error(right, ["A"], run["t"], run["levels"], 20)
    assert own_w < 1e-6
    assert held_w > 100 * max(held_r, 1e-12)


def _small_counts(c: float, k: float, T: int, seed: int) -> list[float]:
    rng = np.random.default_rng(seed)
    x, out = 0, [0.0]
    for _ in range(T - 1):
        i = rng.poisson(c)
        o = min(rng.poisson(k * x), x)
        x = x + i - o
        out.append(float(x))
    return out


def test_discrete_likelihood_prefers_the_true_drain_near_zero():
    a = _small_counts(0.5, 0.5, 400, 3)
    run = _run({"A": a}, 400)
    data_ = J.Data([{"id": "A"}], run)

    def model(c, k):
        return [{"from": None, "to": "A", "rate": {"form": "constant", "value": c}},
                {"from": "A", "to": None, "rate": {"form": "proportional", "stock": "A", "k": k}}]
    assert J2.applies(model(0.5, 0.5), data_)
    nll = {k: J2.nll(model(0.5, k), data_) for k in (0.2, 0.35, 0.5, 0.7, 1.0)}
    assert min(nll, key=nll.get) == 0.5, nll


def test_discrete_likelihood_is_the_gaussian_for_large_rates():
    a = _small_counts(200.0, 0.5, 300, 4)
    run = _run({"A": a}, 300)
    data_ = J.Data([{"id": "A"}], run)
    flows = [{"from": None, "to": "A", "rate": {"form": "constant", "value": 200.0}},
             {"from": "A", "to": None, "rate": {"form": "proportional", "stock": "A", "k": 0.5}}]
    # past the first steps every rate is large: the same likelihood as combined's LNA
    assert abs(J2.nll(flows, data_) - J.nll(flows, data_)) < 0.05 * abs(J.nll(flows, data_))


def test_screens():
    t = np.arange(100.0)
    twins = np.vstack([30 * (1 - 0.9 ** t), 30 * (1 - 0.9 ** t) + 0.0])
    assert screens.alike(twins)
    rng = np.random.default_rng(0)
    apart = np.vstack([np.cumsum(rng.normal(0, 1, 100)), np.cumsum(rng.normal(0, 1, 100))]) + 100
    assert not screens.alike(apart)
    assert screens.counts(np.round(apart)) and not screens.counts(apart)


def run_case(case_prefix: str, variant: str):
    cid = next(c for c in casemod.case_ids() if c.startswith(case_prefix))
    c = casemod.load(cid)
    model = casemod.truth_model(c, variant)
    d = data.load(c, variant)
    r = discover("combined2", model, d)
    flows = json.loads(json.dumps(r["flows"], default=float))
    noise = casemod.variant(c, variant)["noise"]
    if d.get("clean"):
        s = score.equations(c, noise, model, flows, d)
    else:
        s = score.equations(c, noise, model, flows, d)
    return r, s


def test_short_series_go_to_archetypes():
    r, s = run_case("112", "none-short")
    assert r["combined2"]["chosen"] == "archetypes"


def test_measurement_noise_goes_to_the_filter():
    r, s = run_case("082", "meas-short")
    assert r["combined2"]["chosen"] == "kalman"


def test_logistic_crowding_without_noise_passes():
    r, s = run_case("103", "none-short")
    assert s["status"] == "pass", s
