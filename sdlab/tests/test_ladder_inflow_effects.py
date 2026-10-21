"""inflow_effects: outside inflows that are a base (a measured input or an unannounced schedule)
times a table of a stock's level (docs/research/inflow_effects.md)."""

from __future__ import annotations

import pytest

from sdlab.discovery.strategies.inflow_effects import gate
from sdlab.ladder import cases as casemod
from sdlab.ladder import data, runner, score


@pytest.fixture(autouse=True)
def cache(tmp_path, monkeypatch):
    monkeypatch.setenv("SDLAB_LADDER_CACHE", str(tmp_path / "ladder"))


def run_case(case_id, variant):
    c = casemod.load(runner.select_cases(case_id)[0])
    model = casemod.truth_model(c, variant)
    d = {**data.load(c, variant), **casemod.announced(c)}   # as the runner announces it (a declared boundary)
    r = runner.discover("inflow_effects", model, d)
    return r, score.equations(c, casemod.variant(c, variant)["noise"], model, r["flows"], d)


def test_a_measured_inflow_gated_by_its_own_level():
    r, s = run_case("217", "none-short")
    assert s["status"] == "pass", r["flows"]
    gated = [f for f in r["flows"] if f.get("to") == "Q" and f.get("effects")]
    assert len(gated) == 1 and gated[0].get("input") == "arrivals"


def test_adds_no_effect_to_a_plain_chain():
    r, s = run_case("004", "none-short")
    assert s["status"] == "pass"
    assert not any(f.get("effects") for f in r["flows"])


@pytest.mark.parametrize("case_id", ["039-random-inflow-outflow#1", "056-sweep-zero-floor#1"])
def test_no_flat_table_on_a_constant_inflow_without_noise(case_id):
    # noise-free levels are rounded: a table that only fits the rounding is not an effect
    r, s = run_case(case_id, "none-long")
    assert s["status"] == "pass", r["flows"]
    assert not any(f.get("effects") for f in r["flows"])


def test_size_counts_a_tables_points_and_a_schedules_values_and_changes():
    f = {"from": None, "to": "A", "rate": {"form": "constant", "value": 1},
         "inflow": [{"from": 1, "to": 9, "value": 1.0}, {"from": 10, "to": 19, "value": 2.0}, {"from": 20, "to": 30, "value": 1.0}],
         "effects": [{"stock": "N", "shape": "table", "points": [[0, 0], [1, 1], [2, 1]]}], "uses": [{"stock": "N", "per": 0.4}]}
    assert gate.size([f]) == 2 + 2 + 3 + 1
