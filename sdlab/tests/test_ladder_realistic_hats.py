"""Strategy realistic_hats (sdlab/discovery/strategies/realistic_hats; docs/research/realistic-hats.md):
effect_hats' search, anytime. With time to spare it finds what effect_hats finds (018's table effect);
when the caller's timer runs short it returns the best model so far instead of timing out."""

import signal

import pytest

from sdlab.ladder import cases as casemod
from sdlab.ladder import data, runner, score


@pytest.fixture(autouse=True)
def cache(tmp_path, monkeypatch):
    monkeypatch.setenv("SDLAB_LADDER_CACHE", str(tmp_path / "ladder"))


def run_case(case_id, variant, strategy="realistic_hats"):
    c = casemod.load(case_id)
    model = casemod.truth_model(c, variant)
    d = data.load(c, variant)
    r = runner.discover(strategy, model, d)
    return r, score.equations(c, casemod.variant(c, variant)["noise"], model, r["flows"], d)


def test_finds_a_table_effect_as_effect_hats_does():
    r, s = run_case("018-table-effect", "none-short")
    assert s["status"] == "pass"
    assert any(f.get("effects") for f in r["flows"])


def test_returns_the_best_model_so_far_when_time_runs_short(monkeypatch):
    """A tiny share of the caller's timer: the search stops at once and the base (inflows re-cut or
    not) comes back, with a note, instead of the caller's timer firing."""
    monkeypatch.setenv("SDLAB_REALISTIC_HATS_OPTS", '{"share": 0.0001}')
    fired = []
    prev = signal.signal(signal.SIGALRM, lambda *_: fired.append(1))
    signal.setitimer(signal.ITIMER_REAL, 600)
    try:
        r, _ = run_case("018-table-effect", "none-long")
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, prev)
    assert not fired
    assert r["flows"]
    assert "out of time" in str(r.get("chosen"))
