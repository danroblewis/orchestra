"""The censored strategy: a floored link and a capped demand are recovered in their real form, on
synthetic rows and on ladder rungs 024 (floor binds) and 025 (runs empty), and a plain linear case
is left as the main line found it."""

import numpy as np
import pytest

from sdlab.discovery.strategies import censored
from sdlab.discovery.strategies.censored import cap, floor
from sdlab.ladder import cases as casemod
from sdlab.ladder import data, score


@pytest.fixture(autouse=True)
def cache(tmp_path, monkeypatch):
    monkeypatch.setenv("SDLAB_LADDER_CACHE", str(tmp_path / "ladder"))


def test_hinge_search_finds_the_floor():
    rng = np.random.default_rng(1)
    a = np.concatenate([np.full(50, 50.0), np.linspace(50, 200, 50), np.full(100, 200.0), np.linspace(200, 50, 50)]) + rng.normal(0, 1, 250)
    b = rng.uniform(0, 100, 250)
    y = np.maximum(0.0, 30 - 0.25 * a) - 0.1 * b
    fits = floor.search(y, np.array([a, b]), 1, [0])
    best = min(fits, key=lambda f: f["rss"])
    best["i"] = 1
    assert best["j"] == 0 and best["s"] == -1.0
    assert best["theta"] == pytest.approx(120, rel=0.01)
    flows = floor.as_flows(best, ["A", "B"])
    link = next(f for f in flows if f["from"] is None)
    assert link["rate"]["c"] == pytest.approx(30, rel=0.01)
    assert link["rate"]["terms"][0]["k"] == pytest.approx(-0.25, rel=0.01)


def test_cap_profile_separates_demand_from_inflow():
    u = np.concatenate([np.full(100, 2.0), np.full(100, 10.0), np.full(100, 2.0)])
    x = [2.0]
    for k in range(299):
        x.append(x[-1] + u[k] - min(7.0, x[-1]))
    x = np.array(x)
    y = np.diff(x)
    z = np.zeros_like(y)
    fit = cap.search(x[:-1], y, z, z, 0.0, 1e-6)
    assert fit["D"] == pytest.approx(7, rel=0.01)
    assert fit["score"] < fit["plain"]


def run_case(case_id, variant):
    c = casemod.load(case_id)
    model = casemod.truth_model(c, variant)
    d = data.load(c, variant)
    r = censored.identify(casemod.page_stocks(model), {"t": d["t"], "levels": d["levels"]}, {"eras": None})
    return r, score.equations(c, casemod.variant(c, variant)["noise"], model, r["flows"], d)


@pytest.mark.parametrize("variant", ["none-short", "counts-short"])
def test_floor_binds_rung(variant):
    r, s = run_case("024-floor-binds", variant)
    assert s["status"] == "pass", s["parts"]
    assert any("floor on A into B" in x["rewrite"] for x in r["censored"])


@pytest.mark.parametrize("variant", ["none-short", "counts-short"])
def test_runs_empty_rung(variant):
    r, s = run_case("025-runs-empty", variant)
    assert s["status"] == "pass", s["parts"]
    assert any(x["rewrite"].startswith("demand") for x in r["censored"])


def test_linear_case_is_left_alone():
    r, s = run_case("003-chain-2", "none-short")
    assert s["status"] == "pass"
    assert not any("floor" in x["rewrite"] or "demand" in x["rewrite"] for x in r["censored"])
