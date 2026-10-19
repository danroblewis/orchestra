"""combined_misfit (sdlab/discovery/strategies/combined_misfit): the goodness-of-fit tests behind its
switch, and the switch itself: combined's choice stands where the winner fits the counts to their
noise, and multi-step error picks where it does not."""

import pytest

from sdlab.discovery.strategies import combined_misfit as M
from sdlab.discovery.strategies.combined_misfit._vendored import combined as C
from sdlab.discovery.strategies.combined_misfit._vendored.combined import judge as J
from sdlab.discovery.strategies.combined_misfit.fitcheck import goodness
from sdlab.ladder import cases as casemod
from sdlab.ladder import data
from sdlab.skill import truth_by_time


@pytest.fixture(autouse=True)
def cache(tmp_path, monkeypatch):
    monkeypatch.setenv("SDLAB_LADDER_CACHE", str(tmp_path / "ladder"))
    return tmp_path / "ladder"


def cell(case_id, variant):
    c = casemod.load(case_id)
    model = casemod.truth_model(c, variant)
    d = data.load(c, variant)
    stocks = casemod.page_stocks(model)
    run = {"t": d["t"], "levels": d["levels"]}
    return model, d, stocks, run, J.Data(stocks, run, None, d.get("inputs"))


@pytest.mark.parametrize("case_id", ["003-chain-2", "012-rework", "016-coflow"])
def test_the_true_model_fits_counts_to_their_noise(case_id):
    model, d, _, _, D = cell(case_id, "counts-long")
    fit = goodness(truth_by_time(model, d["t"])[0], D)
    assert abs(fit["dispersion"]) < 5 and fit["whiteness"] < 5, fit


def test_a_model_missing_a_flow_does_not():
    model, d, _, _, D = cell("003-chain-2", "counts-long")
    truth = truth_by_time(model, d["t"])[0]
    wrong = [f for f in truth if f.get("from")]               # the outside inflow left out
    fit = goodness(wrong, D)
    assert fit["dispersion"] > 5 or fit["whiteness"] > 5, fit


def test_noise_free_data_are_not_tested():
    model, d, _, _, D = cell("003-chain-2", "none-short")
    assert goodness(truth_by_time(model, d["t"])[0], D) == {"dispersion": None, "whiteness": None}


def test_where_the_winner_fits_combined_s_choice_stands():
    _, _, stocks, run, _ = cell("002-inflow-outflow", "counts-short")
    names = ["censored", "lna"]
    r = M.identify(stocks, run, {"specialists": names})
    base = C.identify(stocks, run, {"specialists": names})
    assert r["combined"]["chosen"] == base["combined"]["chosen"]
    assert not r["combined"]["misfit"].get("switched")
    assert r["flows"] == base["flows"]


def test_where_no_candidate_fits_the_lowest_multi_step_error_is_chosen(monkeypatch):
    """A stand-in specialist whose model is wrong by much (no drain) has the lower BIC by fiat; the
    winner fails the fit test, so the candidate that behaves better over many steps is chosen."""
    model, d, stocks, run, D = cell("002-inflow-outflow", "counts-long")
    truth = truth_by_time(model, d["t"])[0]
    inflow = [f for f in truth if not f.get("from")]

    def fake(*a, **k):
        return {"flows": inflow}
    monkeypatch.setitem(C.STRATEGIES, "periodic_inflows", fake)
    real_score = J.score

    def score(flows, data, *a, **k):                         # the wrong model wins on price
        s = real_score(flows, data, *a, **k)
        return {**s, "bic": s["bic"] - 1e9} if flows == inflow else s
    monkeypatch.setattr(J, "score", score)
    r = M.identify(stocks, run, {"specialists": ["periodic_inflows", "lna"], "refit": False, "guard": 1e9})
    how = r["combined"]["misfit"]
    assert how["bic_choice"] == "periodic_inflows" and how["switched"]
    assert r["combined"]["chosen"] == "lna"
