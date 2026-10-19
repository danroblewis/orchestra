"""Harness fixes from queue item 2k (2026-10-19): the scorer reads a linear rate of a switch (sim.amounts),
`check` runs on a case whose runs are under 20 steps (checks.problems), and `prune` archives latest
results whose case or variant is gone (prune.py)."""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from sdlab.ladder import cases as casemod
from sdlab.ladder import checks, data, prune, score, store
from sdlab.ladder.caseformat import compile_case

HEAD = "title: t\nlevel: 1\ntags: [x]\ntests: x\n"
CASES = Path(casemod.__file__).resolve().parent / "cases"


@pytest.fixture(autouse=True)
def cache(tmp_path, monkeypatch):
    monkeypatch.setenv("SDLAB_LADDER_CACHE", str(tmp_path / "ladder"))


def _model(text: str, steps: int) -> dict:
    m = compile_case(HEAD + text)["model"]
    return {"id": "x", "name": "x", "time_unit": "step", "seed": 1, "steps": steps, "noise": {},
            "stocks": [{"name": s["id"], "unit": "things", **s} for s in m["stocks"]],
            "flows": [{"name": f["id"], **f} for f in m["flows"]]}


@pytest.mark.parametrize("heating", ["8 * heater", '"8 * max(0, heater)"'])
def test_a_linear_rate_that_reads_a_switch_is_scored(heating):
    """225's heater written plainly (a proportional rate of the switch) used to crash sim.amounts."""
    tm = _model("switches:\n  heater: {of: T, on_below: 180, off_above: 220, initial: 1}\nstocks: {T: 200}\n"
                f"flows:\n  outside -> T as heating: {heating}\n  T -> outside: 0.02 * T\n", 200)
    d = data.simulate(tm, 1, 200)
    right = [dict(f) for f in tm["flows"]]
    assert score.equations({"tolerance": {}}, "none", tm, right, d)["status"] == "pass"
    wrong = [{**right[0], "rate": {"form": "constant", "value": 4}}, right[1]]       # a constant inflow, 123's mistake
    assert score.equations({"tolerance": {}}, "none", tm, wrong, d)["status"] == "fail"


def _short_case(lengths: str) -> dict:
    text = (CASES / "112-distilled-short-logistic.yaml").read_text().replace("lengths: {short: 10, long: 20}", f"lengths: {lengths}")
    assert f"lengths: {lengths}" in text
    return casemod._build("999-short-run", compile_case(text))["case"]


@pytest.mark.parametrize("lengths", ["{short: 10, long: 15}", "{short: 5, long: 6}"])
def test_check_runs_on_a_case_whose_runs_are_under_20_steps(lengths):
    assert checks.problems(_short_case(lengths)) == []


def _row(case: str, variant: str, strategy: str = "lna") -> dict:
    return {"case": case, "variant": variant, "strategy": strategy, "case_hash": "c", "strategy_hash": "s", "score_hash": "h", "status": "pass"}


def test_prune_lists_then_archives_results_whose_case_or_variant_is_gone(capsys):
    live = store.record(_row("001-inflow-only", "none-short"))
    old_variant = store.record(_row("001-inflow-only", "counts-run"))
    old_case = store.record(_row("223-no-such-case", "none-short"))
    o = prune.orphans()
    assert sorted((g[0], g[4]) for g in o["gone"]) == [(old_variant, "variant gone"), (old_case, "case gone")]

    assert prune.main(argparse.Namespace(dry_run=True)) == 0
    assert "2 latest results to archive" in capsys.readouterr().out
    assert len(store.latest()) == 3                                           # a dry run changes nothing

    assert prune.main(argparse.Namespace(dry_run=False)) == 0
    assert [r["id"] for r in store.latest()] == [live]
    assert [r["id"] for r in store.history("223-no-such-case", "none-short", "lna")] == [old_case]     # kept, not deleted
    with store.connect(readonly=True) as con:
        assert dict(con.execute("SELECT result_id, why FROM archived").fetchall()) == {old_variant: "variant gone", old_case: "case gone"}
    assert prune.orphans()["gone"] == []
