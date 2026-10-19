"""The archetypes strategy (sdlab/discovery/strategies/archetypes): its simulator steps exactly as the
engine's, and on a series far shorter than the matrix method's 20 steps it recovers the classic
structures it offers (logistic growth, a Bass move, a hidden epidemic source's shape)."""

import json

import numpy as np
import pytest

from sdlab.discovery.simulate import Model
from sdlab.discovery.strategies import archetypes
from sdlab.discovery.strategies.archetypes.sim import run
from sdlab.discovery.strategies.archetypes.terms import Term, arrays
from sdlab.discovery.strategies.archetypes.write import flows as to_flows


@pytest.fixture(autouse=True)
def quick(monkeypatch):
    monkeypatch.setenv("SDLAB_ARCHETYPES", json.dumps({"seconds": 20}))


def engine_run(flows, ids, x0, T, injections=None):
    m = Model(flows, ids)
    L = np.array([[v] for v in x0], dtype=float)
    out = [L[:, 0].copy()]
    for k in range(1, T + 1):
        L = m.run(L, np.array([[float(k)]]), injections)
        out.append(L[:, 0].copy())
    return np.array(out).T


def test_simulator_is_the_engines_step():
    ids = ["A", "B"]
    terms = [Term(None, 0, (0,)), Term(0, None, (0, 0)), Term(0, 1, (0, 1)), Term(1, None, (1,)), Term(None, 1, ())]
    theta = np.array([0.9, 0.004, 0.002, 0.3, 1.5])
    x0 = np.array([5.0, 2.0])
    T = 15
    inj = np.zeros((T + 1, 2))
    inj[6, 1] = 4.0
    X = run(theta, x0, *arrays(terms), inj, T, 1e12)
    levels = engine_run(to_flows(terms, theta, ids, X), ids, x0, T, [{"t": 6, "stock": "B", "amount": 4.0}])
    assert np.allclose(X, levels, rtol=1e-5, atol=1e-6)        # the written numbers have 6 digits


def logistic(r=0.8, K=250.0, x0=5.0, T=10):
    X = run(np.array([r, r / K]), np.array([x0]), *arrays([Term(None, 0, (0,)), Term(0, None, (0, 0))]), np.zeros((T + 1, 1)), T, 1e12)
    return X[0]


def test_ten_steps_of_logistic_growth_are_births_and_crowding():
    x = logistic()
    r = archetypes.identify([{"id": "P"}], {"t": list(range(11)), "levels": {"P": [float(v) for v in x]}}, {})
    flows = r["flows"]
    births = [f for f in flows if f["from"] is None and f["to"] == "P"]
    deaths = [f for f in flows if f["from"] == "P" and f["to"] is None]
    assert len(births) == 1 and len(deaths) == 1 and deaths[0].get("effects"), flows
    assert births[0]["rate"]["k"] == pytest.approx(0.8, rel=1e-3)
    e = deaths[0]["effects"][0]
    assert deaths[0]["rate"]["k"] / e["normal"] == pytest.approx(0.8 / 250, rel=1e-3)


def test_noisy_short_logistic_still_saturates():
    rng = np.random.default_rng(3)
    x = logistic(T=12)
    y = np.maximum(0.0, x * (1 + 0.07 * rng.standard_normal(len(x))))
    r = archetypes.identify([{"id": "P"}], {"t": list(range(13)), "levels": {"P": [float(v) for v in y]}}, {})
    assert r["archetypes"]["family"] in ("logistic", "search")
    ids = ["P"]
    ahead = engine_run(r["flows"], ids, [y[-1]], 30)[0]
    assert 150 < ahead[-1] < 400                     # runs to a level near K = 250, not off to infinity


def test_bass_move_between_two_shares():
    T = 14
    terms = [Term(0, 1, (0,)), Term(0, 1, (0, 1))]
    X = run(np.array([0.02, 0.006]), np.array([97.0, 3.0]), *arrays(terms), np.zeros((T + 1, 2)), T, 1e12)
    r = archetypes.identify([{"id": "N"}, {"id": "A"}], {"t": list(range(T + 1)), "levels": {"N": list(X[0]), "A": list(X[1])}}, {})
    moves = [f for f in r["flows"] if f["from"] == "N" and f["to"] == "A"]
    assert len(moves) == 2 and len(r["flows"]) == 2, r["archetypes"]


def test_nothing_from_a_flat_series():
    r = archetypes.identify([{"id": "X"}], {"t": list(range(8)), "levels": {"X": [10.0] * 8}}, {})
    assert r["flows"] == []
