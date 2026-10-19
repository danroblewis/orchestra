"""Experiment hidden_transit (docs/research/hidden_transit.md): a transit stock A -> H -> B found by
refitting the pair's rows with a Kalman filter, on the ladder's hidden-stock rung and on rungs that
have none."""

from __future__ import annotations

import numpy as np
import pytest

from sdlab.discovery.strategies.hidden_transit import counts
from sdlab.discovery.strategies.hidden_transit.fit import fit_transit
from sdlab.discovery.strategies.hidden_transit.kalman import Pair
from sdlab.ladder import cases as casemod
from sdlab.ladder import data, runner, score


@pytest.fixture(autouse=True)
def cache(tmp_path, monkeypatch):
    monkeypatch.setenv("SDLAB_LADDER_CACHE", str(tmp_path / "ladder"))


def found(case_id: str, variant: str) -> tuple[dict, dict]:
    c = casemod.load(case_id)
    model = casemod.truth_model(c, variant)
    d = data.load(c, variant)
    r = runner.discover("hidden_transit", model, d)
    return r, score.equations(c, casemod.variant(c, variant)["noise"], model, r["flows"], d)


@pytest.mark.parametrize("case_id,variant", [("015-hidden-stock", "none-short"), ("015-hidden-stock", "none-long"),
                                             ("015-hidden-stock", "counts-long"), ("026-hidden-stock-driven", "counts-short")])
def test_the_hidden_stock_rungs_pass(case_id, variant):
    r, s = found(case_id, variant)
    assert s["status"] == "pass", s["parts"]
    assert set(r["inferred_levels"]) == {"A~B"}


@pytest.mark.parametrize("case_id,variant", [("003-chain-2", "counts-short"), ("014-split", "none-short"), ("013-merge", "counts-long")])
def test_no_transit_stock_where_there_is_none(case_id, variant):
    r, _ = found(case_id, variant)
    assert not any(f.get("hidden") for f in r["flows"])
    assert not r.get("inferred_levels")


def test_the_mirror_is_told_apart_by_a_s_balance():
    """B's response to A is the same with the delay and B's drain swapped (kin scaled); with all of
    A's loss going to H only the true one fits A as well."""
    d = data.load(casemod.load("015-hidden-stock"), "none-short")
    A, B = (np.array(d["levels"][s], dtype=float) for s in "AB")
    z = np.zeros(len(A) - 1)
    f = fit_transit(Pair(A, B, z, z, z, z, 0.0, np.zeros(len(z), int)), False, True)
    assert abs(1 / f["d"] - 10) < 0.01 and abs(f["kb"] - 0.2) < 1e-3 and abs(f["kin"] - 0.2) < 1e-3


def test_counts_are_told_from_exact_levels():
    c = casemod.load("015-hidden-stock")
    assert counts({"levels": data.load(c, "counts-short")["levels"]})
    assert not counts({"levels": data.load(c, "none-short")["levels"]})


# Hidden stages on one stock's inflow (stage.py, stagekf.py): the distilled cases 133-135 and the
# canonical cases they came from.

@pytest.mark.parametrize("case_id,variant", [("133-hidden-supply-line", "none-long"), ("133-hidden-supply-line", "counts-long"),
                                             ("134-delayed-measured-input", "counts-long"), ("135-hidden-rework", "none-short"),
                                             ("135-hidden-rework", "counts-long"), ("107-canonical-rework", "counts-long"),
                                             ("110-canonical-world3-pollution", "none-short")])
def test_a_hidden_stage_is_found(case_id, variant):
    r, s = found(case_id, variant)
    assert s["status"] == "pass", s["parts"]
    assert any(h.endswith("~stage") or "~stages" in h for h in r["inferred_levels"])


def test_rework_is_written_as_a_move_out_and_back():
    r, _ = found("135-hidden-rework", "none-long")
    out = [f for f in r["flows"] if f.get("from") == "W" and f.get("hidden")]
    back = [f for f in r["flows"] if f.get("to") == "W" and f.get("hidden")]
    assert len(out) == 1 and len(back) == 1
    assert abs(out[0]["rate"]["k"] - 0.025) < 1e-4 and abs(1 / back[0]["rate"]["k"] - 15) < 0.01


def test_a_delayed_input_without_noise_is_the_truth_or_its_mirror():
    """134 none: an input into H, H into T: T's levels cannot tell the delay from T's drain (the
    mirror); the stage is one of the two, exactly."""
    r, _ = found("134-delayed-measured-input", "none-short")
    drain = next(f["rate"]["k"] for f in r["flows"] if f.get("from") == "T" and f.get("to") is None)
    delay = 1 / next(f["rate"]["k"] for f in r["flows"] if f.get("to") == "T" and f.get("hidden"))
    assert (abs(drain - 0.2) < 1e-3 and abs(delay - 8) < 0.01) or (abs(drain - 0.125) < 1e-3 and abs(delay - 5) < 0.01)
