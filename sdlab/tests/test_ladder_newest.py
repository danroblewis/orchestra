"""The newest cases view: case dates from git (case_dates.py, cached), where distilled cases came from,
regressions, and the /api/ladder/newest endpoints (newest.py, newest_routes.py)."""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from sdlab.ladder import case_dates, newest, newest_routes, store
from sdlab.ladder import cases as casemod

LOG = """@@aaa|2026-10-18T15:53:34-07:00|Ladder: tiny cases
A\tc/001-one.json
A\tc/002-two.json

@@bbb|2026-10-18T23:39:13Z|rewrite in yaml
D\tc/001-one.json
A\tc/001-one.yaml
R100\tc/002-two.json\tc/002-renamed.json

@@ccc|2026-10-19T07:41:57Z|Ladder: 20 distilled cases
A\tc/120-new.yaml
M\tc/001-one.yaml
"""


def test_parse_log_first_add_renames_and_utc():
    first = case_dates.parse_log(LOG)
    assert first["c/001-one.json"] == {"commit": "aaa", "at": "2026-10-18T22:53:34Z", "subject": "Ladder: tiny cases"}
    assert first["c/002-renamed.json"]["commit"] == "aaa"            # a rename keeps the first add
    assert first["c/001-one.yaml"]["commit"] == "bbb"                 # a new path; _entries merges it by stem
    assert first["c/120-new.yaml"]["at"] == "2026-10-19T07:41:57Z"


def _git(root: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, check=True).stdout.strip()


@pytest.fixture
def repo(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    cases = root / "lad" / "cases"
    cases.mkdir(parents=True)
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "t")
    (cases / "001-one.json").write_text("{}")
    _git(root, "add", ".")
    _git(root, "commit", "-q", "-m", "first cases", "--date", "2026-10-18T10:00:00Z")
    (cases / "001-one.json").unlink()
    (cases / "001-one.yaml").write_text("title: x\n")
    (cases / "002-two.yaml").write_text("title: y\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "yaml and a second case", "--date", "2026-10-19T10:00:00Z")
    (cases / "003-draft.yaml").write_text("title: z\n")              # not committed
    files = lambda: {p.stem: p for p in sorted(cases.glob("*.yaml"))}   # noqa: E731
    monkeypatch.setattr(case_dates, "CASES", cases)
    monkeypatch.setattr(case_dates, "_files", files)
    monkeypatch.setenv("SDLAB_LADDER_CACHE", str(tmp_path / "cache"))
    monkeypatch.setattr(case_dates, "_state", {"head": None, "entries": None, "checked": 0.0})
    return root


def test_dates_from_git_cached_by_head(repo, monkeypatch):
    e = case_dates.refresh()
    assert e["001-one"]["subject"] == "first cases"                   # the .json -> .yaml rewrite keeps the first date
    assert e["002-two"]["subject"] == "yaml and a second case"
    assert e["003-draft"]["commit"] is None and e["003-draft"]["seen"]
    assert case_dates.added_at(e["003-draft"]) == e["003-draft"]["seen"]
    assert case_dates.head(repo) == _git(repo, "rev-parse", "HEAD")
    assert json.loads(case_dates.cache_path().read_text())["head"] == _git(repo, "rev-parse", "HEAD")

    # a fresh process at the same HEAD loads the cache and never runs git
    monkeypatch.setattr(case_dates, "_state", {"head": None, "entries": None, "checked": 0.0})
    monkeypatch.setattr(case_dates, "_git_log", lambda root: (_ for _ in ()).throw(AssertionError("git ran")))
    assert case_dates.dates()["001-one"]["commit"] == e["001-one"]["commit"]
    case_dates.warm()
    assert case_dates.dates()["002-two"]["subject"] == "yaml and a second case"


def test_dates_refresh_in_background_when_head_moves(repo, monkeypatch):
    case_dates.refresh()
    (repo / "lad" / "cases" / "004-later.yaml").write_text("title: w\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "a later case")
    case_dates._state["checked"] = 0.0
    case_dates.dates()                                                # sees HEAD moved: refreshes in a thread
    for _ in range(100):
        if case_dates._busy.acquire(timeout=0.1):
            case_dates._busy.release()
            if case_dates._state["entries"].get("004-later", {}).get("commit"):
                break
    assert case_dates.dates()["004-later"]["subject"] == "a later case"


def test_distilled_source_parses_the_ladder_doc():
    src = newest.parse_distilled(newest.LADDER_MD.read_text())
    assert {f"{i}" for i in range(120, 140)} <= set(src)
    assert "SIR" in src["126"]["hard"] and src["126"]["case"].startswith("126-product-move")
    assert src["120"]["mistake"]


def test_kind_and_capabilities():
    assert newest.kind({"tags": ["distilled", "product"]}) == "distilled"
    assert newest.kind({"tags": ["chain"]}) == "test"
    assert newest.kind({"tags": ["physics"], "physics": {}}) == "physics"
    assert newest.kind({"tags": ["realistic"], "example": "sd-x"}) == "realistic"
    assert newest.capabilities(["distilled", "product", "short-series", "noisy"]) == ["product", "short-series"]


def _summary():
    cases = [{"id": "001-old", "title": "old", "level": 1, "tags": ["chain"], "tests": "a chain", "variants": ["none", "counts"]},
             {"id": "120-new", "title": "new", "level": 2, "tags": ["distilled", "product"], "tests": "a product", "variants": ["none", "counts"]},
             {"id": "sd-x", "title": "ex", "level": 20, "tags": ["realistic"], "tests": "", "variants": ["counts"], "example": "sd-x"}]
    st = {"001-old": {"A": ["pass", "pass"], "B": ["pass", "fail"]}, "120-new": {"A": ["fail", "fail"], "B": ["fail", None]},
          "sd-x": {"A": ["pass"], "B": ["fail"]}}
    cells = [{"case": c["id"], "variant": v, "strategy": s, "status": st[c["id"]][s][i]}
             for c in cases for s in ("A", "B") for i, v in enumerate(c["variants"])]
    return {"strategies": [{"name": "A", "available": True}, {"name": "B", "available": True}], "cases": cases, "cells": cells,
            "totals": {"A": {"pass": 2, "total": 4, "missing": 0}, "B": {"pass": 1, "total": 4, "missing": 1}}, "score_hash": "s"}


@pytest.fixture
def client(monkeypatch):
    ago = lambda h: (datetime.now(timezone.utc) - timedelta(hours=h)).strftime("%Y-%m-%dT%H:%M:%SZ")   # noqa: E731
    dates = {"001-old": {"at": ago(30 * 24), "commit": "aaaaaaaaaaaa", "subject": "old cases", "path": "x"},
             "120-new": {"at": ago(1), "commit": "bbbbbbbbbbbb", "subject": "distilled", "path": "y"},
             "sd-x": {"at": None, "commit": None, "subject": None, "seen": ago(0.1), "path": "z"}}
    sm = _summary()
    monkeypatch.setattr(newest.api, "summary", lambda *a: sm)
    monkeypatch.setattr(newest.api, "strategy_names", lambda: ["A", "B"])
    monkeypatch.setattr(newest.case_dates, "dates", lambda: dates)
    reg = {"items": [{"strategy": "B", "case": "001-old", "variant": "counts", "from": "pass", "to": "fail", "scorer_changed": False}],
           "by_strategy": {"B": {"n": 1, "fail": 1, "error": 0, "scorer_changed": 0}}, "n": 1, "n_fail": 1, "n_clean": 1, "computed": "now"}
    monkeypatch.setattr(newest, "regressions", lambda wait=False: reg)
    monkeypatch.setattr(newest, "_cache", {})
    app = FastAPI()
    app.include_router(newest_routes.router)
    return TestClient(app)


def test_api_newest(client):
    d = client.get("/api/ladder/newest").json()
    assert [r["id"] for r in d["rows"]] == ["sd-x", "120-new", "001-old"]       # newest first (an uncommitted file by its time)
    new = d["rows"][1]
    assert new["kind"] == "distilled" and new["capabilities"] == ["product"]
    assert new["added"]["commit"] == "bbbbbbbbbb" and new["added"]["subject"] == "distilled"
    assert new["from"] and "Gause" in new["from"]["hard"]                           # 120's number maps to LADDER.md's 120 row
    assert new["leaders"]["A"] == {"p": 0, "e": 0, "f": 2, "o": 0, "n": 2, "of": 2, "v": "FF"}
    assert new["leaders"]["B"]["v"] == "F." and new["fails_everyone"]
    assert not d["rows"][2]["fails_everyone"] and d["rows"][0]["added"]["committed"] is False
    imp = d["impact"]["strategies"]["A"]                                          # Tests only: the realistic sd-x is left out
    assert imp["all"] == {"pass": 2, "ran": 4, "rate": 0.5}
    assert imp["old24"] == {"pass": 2, "ran": 2, "rate": 1.0} and imp["new24"] == {"pass": 0, "ran": 2, "rate": 0.0}
    assert imp["new6"]["ran"] == 2 and imp["old168"]["ran"] == 2
    assert d["regressions"]["n_fail"] == 1
    assert len(json.dumps(d)) < 20000


def test_api_newest_strategies_and_ages(client):
    assert client.get("/api/ladder/newest?strategies=nope").status_code == 404
    d = client.get("/api/ladder/newest?strategies=B").json()
    assert [x["name"] for x in d["leaders"]] == ["B"] and set(d["rows"][1]["leaders"]) == {"B"}
    a = client.get("/api/ladder/newest/ages").json()
    assert a["added"]["120-new"] < a["added"]["sd-x"] and a["added"]["001-old"] < a["added"]["120-new"]
    assert a["regressions"]["n_fail"] == 1
    assert client.get("/api/ladder/newest/regressions").json()["n"] == 1


def test_regressions_against_the_previous_version(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "path", lambda: tmp_path / "results.sqlite")    # a private store; the case caches stay shared
    monkeypatch.setattr(newest.api, "strategy_names", lambda: ["S", "T"])
    cid = next(iter(casemod.case_files()))
    h = casemod.load(cid)["hash"]
    row = lambda strat, sh, status, ch=h, score="x": store.record({"case": cid, "variant": "none", "strategy": strat, "case_hash": ch,  # noqa: E731
                                                                   "strategy_hash": sh, "score_hash": score, "status": status})
    for args in (("S", "v1", "pass"), ("S", "v1", "pass"), ("S", "v2", "fail")):       # S: v1 passed, v2 fails -> a regression
        row(*args)
    for args in (("T", "v1", "fail"), ("T", "v2", "pass")):                              # T: got better
        row(*args)
    row("T", "v3", "pass", score="y")
    r = newest._compute_regressions()
    assert r["n"] == 1 and r["items"][0]["strategy"] == "S" and (r["items"][0]["from"], r["items"][0]["to"]) == ("pass", "fail")
    assert r["n_clean"] == 1
    row("S", "v3", "pass", ch="other-case-hash")                                 # a changed case is not compared
    assert newest._compute_regressions()["n"] == 0
