"""own_tables: a curve of a stock's own level with free points, read back as one table flow or a
drain beside an inflow table; on synthetic rows and the distilled cases 122 and 123 (none-short)."""

import numpy as np
import pytest

from sdlab.discovery.strategies import own_tables
from sdlab.discovery.strategies.own_tables import curve, split
from sdlab.ladder import cases as casemod
from sdlab.ladder import data, score


@pytest.fixture(autouse=True)
def cache(tmp_path, monkeypatch):
    monkeypatch.setenv("SDLAB_LADDER_CACHE", str(tmp_path / "ladder"))


def test_free_points_find_the_bends():
    x = np.random.default_rng(3).uniform(0, 80, 600)
    y = -np.interp(x, [0, 4, 16, 36, 81], [0, 1, 2, 3, 4.5])
    cv = curve.search(y, x, np.zeros((0, 600)), 1e-10)
    assert len(cv["knots"]) == 5
    assert np.allclose(cv["knots"][1:4], [4, 16, 36], atol=0.05)


def test_a_switch_beside_a_drain_is_read_as_both():
    kn = np.array([10.0, 18.0, 22.0, 40.0])
    g = 5 * np.array([1, 1, 0, 0]) - 0.1 * kn
    rd = split.readings(kn, g, 1e-6)[0]
    assert rd["other"][0] == "drain" and rd["other"][1] == pytest.approx(0.1)
    assert np.allclose(rd["values"], [5, 5, 0, 0])


def run_case(case_id, variant):
    c = casemod.load(case_id)
    model = casemod.truth_model(c, variant)
    d = data.load(c, variant)
    inj = [{"t": j["t"], "stock": j["stock"], "amount": j["amount"]} for j in d.get("injections") or []]
    r = own_tables.identify(casemod.page_stocks(model), {"t": d["t"], "levels": d["levels"]}, {"eras": None, "injections": inj})
    return r, score.equations(c, casemod.variant(c, variant)["noise"], model, r["flows"], d)


@pytest.mark.parametrize("case_id", ["122-concave-drain", "123-inflow-shut-by-own-level"])
def test_distilled_cases(case_id):
    r, s = run_case(case_id, "none-short")
    assert s["status"] == "pass", s["parts"]
    assert r["own_tables"]
