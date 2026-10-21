"""The ladder's "current" is the sdlab HEAD's hashes (head_hashes.py), not the working tree's: an
uncommitted edit to the scorer or a strategy marks no result stale on the pages; a new commit that
changes them does. While a new HEAD is being planned the last known plan is served."""

import json

import pytest

from sdlab.ladder import api, head_hashes, score, store, summary_build
from sdlab.ladder import cases as casemod
from sdlab.ladder.pool import gitcode, jobs, planner

CASES = ("001-inflow-only", "002-inflow-outflow")


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("SDLAB_LADDER_CACHE", str(tmp_path / "ladder"))
    monkeypatch.setenv("SDLAB_POOL_HOME", str(tmp_path / "pool"))
    f = tmp_path / "cases"
    f.mkdir()
    for cid in CASES:
        (f / f"{cid}.json").write_text(json.dumps(casemod.spec(cid)))
    monkeypatch.setattr(casemod, "CASES", f)
    monkeypatch.setattr(head_hashes, "ENABLED", True)
    monkeypatch.setattr(head_hashes, "_last", {"head": None, "cells": None, "strategies": None})
    summary_build._stores.clear()
    return tmp_path


def _plan(strategy_hash="m1", score_hash="committed-scorer"):
    return {"strategies": {"matrix": strategy_hash}, "skipped": {}, "parked": [], "retired": [],
            "cases": {cid: {"hash": casemod.load(cid)["hash"], "tags": [], "timeout": 300,
                            "variants": [{"name": v["name"], "score_hash": score_hash} for v in casemod.load(cid)["variants"]]}
                      for cid in CASES}}


def _head(monkeypatch, commit, plan):
    monkeypatch.setattr(jobs, "mainline_plan", lambda wait=False: (commit, plan) if plan is not None else None)


def _record(cid="001-inflow-only", variant="none-short"):
    store.record({"case": cid, "variant": variant, "strategy": "matrix", "case_hash": casemod.load(cid)["hash"], "strategy_hash": "m1",
                  "score_hash": "committed-scorer", "status": "pass", "seconds": 1.0, "scores": {"recall": 1.0}, "found": []})


def _stale(sm, cid="001-inflow-only", variant="none-short"):
    return next(c["stale"] for c in sm["cells"] if (c["case"], c["variant"], c["strategy"]) == (cid, variant, "matrix"))


def test_working_tree_edits_mark_nothing_stale(monkeypatch):
    _head(monkeypatch, "c1", _plan())
    _record()
    working = [{"name": "matrix", "hash": "m1-edited-on-disk", "available": True}]          # an uncommitted strategy edit
    monkeypatch.setattr(score, "score_hash", lambda: "uncommitted-scorer")                  # an uncommitted scorer edit
    sm = summary_build.build(None, working)
    assert _stale(sm) is None
    assert _stale(sm, variant="counts-short") == "new"
    assert sm["totals"]["matrix"]["stale"] == 0


def test_a_new_commit_that_changes_them_marks_results_stale(monkeypatch):
    _head(monkeypatch, "c1", _plan())
    _record()
    listing = [{"name": "matrix", "hash": "m1", "available": True}]
    assert _stale(summary_build.build(None, listing)) is None
    _head(monkeypatch, "c2", _plan(strategy_hash="m2"))
    assert head_hashes.version() == "c2"
    assert _stale(summary_build.build(None, listing)) == "strategy changed"
    _head(monkeypatch, "c3", _plan(strategy_hash="m2", score_hash="new-scorer"))
    _record()                                                                               # (a result at the old hashes again)
    assert _stale(summary_build.build(None, listing)) == "strategy changed"
    _head(monkeypatch, "c4", _plan(score_hash="new-scorer"))
    assert _stale(summary_build.build(None, listing)) == "score_only"


def test_the_last_plan_is_served_while_a_new_head_is_planned(monkeypatch, env):
    _head(monkeypatch, "c1", _plan())
    _record()
    listing = [{"name": "matrix", "hash": "edited", "available": True}]
    assert _stale(summary_build.build(None, listing)) is None
    _head(monkeypatch, "c2", None)                                                          # HEAD moved; its plan is being made
    assert head_hashes.version() == "c1"
    assert _stale(summary_build.build(None, listing)) is None
    # after a restart nothing is in memory: the newest main-line plan on disk is used
    monkeypatch.setattr(head_hashes, "_last", {"head": None, "cells": None, "strategies": None})
    d = gitcode.home() / "plans"
    d.mkdir(parents=True)
    (d / (planner._key("c0", jobs.MAINLINE_SPEC) + ".json")).write_text(json.dumps(_plan()))
    assert head_hashes.version() == "c0"
    assert _stale(summary_build.build(None, listing)) is None


def test_off_or_not_in_heads_plan_uses_the_working_tree(monkeypatch):
    _head(monkeypatch, "c1", _plan())
    _record()
    listing = [{"name": "matrix", "hash": "edited", "available": True}, {"name": "brand-new", "hash": "n1", "available": True}]
    sm = summary_build.build(None, listing)
    assert next(c["stale"] for c in sm["cells"] if c["strategy"] == "brand-new") == "new"   # not committed yet: the working tree's
    monkeypatch.setattr(head_hashes, "ENABLED", False)                                      # the command line and other tests
    assert head_hashes.current() is None
    summary_build._stores.clear()
    assert _stale(summary_build.build(None, listing)) == "strategy changed"


def test_the_summary_is_rebuilt_when_head_moves(monkeypatch):
    from sdlab.ladder import catalog
    monkeypatch.setattr(catalog, "listing", lambda check=True: [{"name": "matrix", "hash": "m1", "available": True}])
    monkeypatch.setattr(api, "_summaries", {})
    _head(monkeypatch, "c1", _plan())
    _record()
    assert _stale(api.summary()) is None
    _head(monkeypatch, "c2", _plan(strategy_hash="m2"))
    api._refresh((tuple(), str(store.path())), None, False)
    assert _stale(api.summary()) == "strategy changed"
