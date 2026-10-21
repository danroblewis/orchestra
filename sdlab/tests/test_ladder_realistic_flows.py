"""Strategy realistic_flows (sdlab/discovery/strategies/realistic_flows; docs/research/realistic-flows.md):
realistic_hats with coflow_hats' co-flow stages and the matrix's rows' own drains kept."""

import pytest

from sdlab.ladder import cases as casemod
from sdlab.ladder import data, runner, score


@pytest.fixture(autouse=True)
def cache(tmp_path, monkeypatch):
    monkeypatch.setenv("SDLAB_LADDER_CACHE", str(tmp_path / "ladder"))


def run_case(case_id, variant):
    c = casemod.load(case_id)
    model = casemod.truth_model(c, variant)
    d = {**data.load(c, variant), **casemod.announced(c)}   # as the runner announces it (a declared boundary)
    r = runner.discover("realistic_flows", model, d)
    return r, score.equations(c, casemod.variant(c, variant)["noise"], model, r["flows"], d)


def test_keeps_the_drain_left_after_a_move():
    """154: B's leave (0.024 B) less the births read as a move (0.022 B) is 0.002 B, about 200 a step;
    it is kept, not folded into B's outside inflow."""
    r, s = run_case("154-move-into-stepping-fed-stock", "none-short")
    assert s["status"] in ("pass", "equivalent")
    assert "own drains" in r["chosen"]


def test_keeps_a_small_link_from_a_large_stock():
    r, s = run_case("153-link-from-large-slow-stock", "none-short")
    assert s["status"] in ("pass", "equivalent")
    assert any(f.get("from") is None and f.get("to") == "H" and (f.get("rate") or {}).get("form") == "linear" for f in r["flows"])


def test_coflow_on_an_outside_inflow():
    r, s = run_case("128-coflow-on-outside-inflow", "none-short")
    assert s["status"] == "pass"
    assert any(f.get("uses") for f in r["flows"])


def test_finds_a_table_effect():
    r, s = run_case("018-table-effect", "none-short")
    assert s["status"] == "pass"
    assert any(f.get("effects") for f in r["flows"])
