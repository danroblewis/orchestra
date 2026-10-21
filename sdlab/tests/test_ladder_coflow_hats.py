"""Strategy coflow_hats (sdlab/discovery/strategies/coflow_hats): effect_hats plus co-flows and cyclic
links found after the model is chosen. Without noise it recovers a co-flow on an outside inflow
(128), a co-flow whose used stock runs dry (129) and a link whose strength follows a daily cycle (132),
and it adds nothing to a plain chain."""

import numpy as np
import pytest

from sdlab.discovery.strategies.coflow_hats import coflows
from sdlab.ladder import cases as casemod
from sdlab.ladder import data, runner, score


@pytest.fixture(autouse=True)
def cache(tmp_path, monkeypatch):
    monkeypatch.setenv("SDLAB_LADDER_CACHE", str(tmp_path / "ladder"))


def run_case(case_id, variant):
    c = casemod.load(case_id)
    model = casemod.truth_model(c, variant)
    d = {**data.load(c, variant), **casemod.announced(c)}   # as the runner announces it (a declared boundary)
    r = runner.discover("coflow_hats", model, d)
    return r, score.equations(c, casemod.variant(c, variant)["noise"], model, r["flows"], d)


def test_per_from_jumps_reads_the_opposite_jumps():
    f = np.r_[np.full(50, 40.0), np.full(50, 20.0), np.full(50, 40.0)]
    g = np.r_[np.full(30, 110.0), np.full(20, 60.0), np.full(50, 80.0), np.full(50, 60.0)]
    assert coflows.per_from_jumps(f, g) == pytest.approx(1.0)
    assert coflows.per_from_jumps(f, -g) is None


@pytest.mark.parametrize("case_id", ["128-coflow-on-outside-inflow", "129-coflow-runs-empty", "132-link-with-daily-cycle"])
def test_recovers_the_distilled_case_without_noise(case_id):
    r, s = run_case(case_id, "none-short")
    assert s["status"] == "pass", (r.get("chosen"), [(p["key"], p["ok"]) for p in s["parts"]])


def test_adds_nothing_to_a_chain():
    r, s = run_case("004-chain-3", "none-short")
    assert s["status"] == "pass"
    assert not any(f.get("uses") or f.get("byTime") for f in r["flows"])
