"""Cases as mathematical probes (sdlab/ladder/analysis.py, fisher.py, sweep.py, draws.py grid): what
the data can deliver per case and variant (identifiability, the Cramér-Rao bound, the label), the
bound checked against maximum-likelihood refits by Monte Carlo, and the sweeps."""

import numpy as np
import pytest
from fastapi.testclient import TestClient

from sdlab.ladder import analysis, checks, draws, sweep
from sdlab.ladder import cases as casemod
from sdlab.ladder.caseformat import CaseError
from sdlab.ladder.data import simulate
from sdlab.ladder.fisher import TruthParams, bound


@pytest.fixture(autouse=True)
def cache(tmp_path, monkeypatch):
    monkeypatch.setenv("SDLAB_LADDER_CACHE", str(tmp_path / "ladder"))
    return tmp_path / "ladder"


@pytest.mark.parametrize("case", ["034-identical-twins", "035-identical-twins-different-starts", "038-identical-twin-chains"])
@pytest.mark.parametrize("variant", ["none-short", "none-long"])
def test_identical_stocks_without_noise_are_rank_deficient(case, variant):
    a = analysis.analyse(case, variant)
    assert a["label"] == "unidentifiable"
    rows = a["design"]
    assert all(r["rank"] < r["of"] for r in rows)                   # every row's design loses rank
    assert any(g["exact"] for r in rows for g in r["collinear"])
    assert any("collinear" in w for w in a["why"])


@pytest.mark.parametrize("case", ["034-identical-twins", "038-identical-twin-chains"])
def test_counting_noise_tells_identical_stocks_apart(case):
    a = analysis.analyse(case, "counts-long")
    assert a["label"] == "achievable"
    assert all(r["rank"] == r["of"] for r in a["design"])


def test_births_and_deaths_only_their_difference_without_noise():
    a = analysis.analyse("009-births-and-deaths", "none-long")
    assert a["label"] == "unidentifiable"
    assert {p["name"] for p in a["parameters"] if p["unidentified"]} == {"births.k", "deaths.k"}
    # with counting noise the variance (births + deaths) separates them: identifiable, through the variance only
    c = analysis.analyse("009-births-and-deaths", "counts-long")
    assert c["label"] != "unidentifiable"
    assert any(r.get("variance_only") for r in c["parts"])


def test_a_link_and_a_move_with_a_smaller_drain_are_the_same_levels():
    a = analysis.analyse("007-link", "none-short")
    assert a["label"] == "unidentifiable" and any("move A -> B" in w for w in a["why"])
    c = analysis.analyse("007-link", "counts-long")                   # the noise's covariance tells them apart
    assert c["label"] == "achievable" and c["structure_p"] > 0.9


def test_a_chain_is_achievable_and_the_hidden_mirror_is_not():
    assert analysis.analyse("003-chain-2", "counts-short")["label"] == "achievable"
    assert analysis.analyse("003-chain-2", "none-short")["label"] == "achievable"
    assert analysis.analyse("015-hidden-stock", "none-short")["label"] == "unidentifiable"


def test_the_bound_matches_the_spread_of_ml_refits_on_a_chain():
    """The Cramér-Rao bound against the spread of the true structure refitted by ML on 40 fresh seeds
    (003 counts-long): within 25% for every number (the spread itself is known to about 11%)."""
    c = casemod.load("003-chain-2")
    tm = casemod.truth_model(c, "counts-long")
    est, ses = [], []
    for s in range(40):
        d = simulate(tm, 500 + s, 2000)
        tp = TruthParams(tm, d, "counts")
        est.append(tp.ml_fit())
        C, null = bound(tp.fisher()["full"])
        assert null.size == 0
        ses.append(np.sqrt(np.diag(C)))
    sd, crb = np.array(est).std(axis=0, ddof=1), np.array(ses).mean(axis=0)
    assert np.all(np.abs(sd / crb - 1) < 0.25), (sd, crb)
    assert np.all(np.abs(np.array(est).mean(axis=0) - tp.theta0) < 3 * crb / np.sqrt(40) + 1e-9)


def test_cache_and_cell(cache):
    c = casemod.load("002-inflow-outflow")
    assert analysis.cell(c["id"], "counts-short", c["hash"]) == {}
    got = analysis.get(c["id"], "counts-short")
    assert analysis.cell(c["id"], "counts-short", c["hash"]) == {"analysis": got["label"], "achievable_p": got["p"]}


# ---- sweeps ----

GRID = """\
title: a sweep
level: 2
tags: [sweep]
tests: one quantity along a grid
stocks: {A: 0}
flows:
  outside -> A: grid(5, 10, 20)
  A -> outside: grid(0.1, 0.2, 0.3) * A
"""


def test_grid_draws_take_the_ith_value():
    ss = draws.sites(GRID)
    assert draws.count(GRID) == 3
    assert [draws.values(ss, 1, i) for i in (1, 2, 3)] == [[5, 0.1], [10, 0.2], [20, 0.3]]
    assert draws.values(ss, 1, 2) == draws.values(ss, 1, 2, attempt=5)     # a grid is not drawn again
    with pytest.raises(CaseError):
        draws.count(GRID.replace("grid(0.1, 0.2, 0.3)", "grid(0.1, 0.2)"))
    with pytest.raises(CaseError):
        draws.count("draws: 4\n" + GRID)


def test_sweep_cases_compile_and_pass_the_checks():
    sw = sweep.sweeps()
    assert len(sw) >= 8
    for s in sw:
        assert len(s["values"]) == len(s["draws"])
        for cid in s["draws"]:
            assert checks.problems(casemod.load(cid)) == [], cid


def test_sweep_endpoints():
    from sdlab.server import create_app

    client = TestClient(create_app())
    sw = client.get("/api/ladder/sweeps").json()
    base = next(s["base"] for s in sw if s["base"].startswith("049"))
    ph = client.get(f"/api/ladder/sweeps/{base}/none-short?strategies=matrix").json()
    assert [p["label"] for p in ph["points"]][0] == "unidentifiable"       # r = 1: identical stocks
    assert client.get(f"/api/ladder/sweeps/{base}/none-short.svg?strategies=matrix").text.startswith("<svg")
    assert client.get(f"/api/ladder/analysis/{base}%231/none-short").json()["label"] == "unidentifiable"
    assert client.get("/api/ladder/sweeps/nope/none-short").status_code == 404
    assert client.get("/api/ladder/analysis/001-inflow-only/nope").status_code == 404
