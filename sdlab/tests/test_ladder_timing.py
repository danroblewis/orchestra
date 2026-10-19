"""Time measurements in the ladder (queue item 1b): each result's discovery, scoring, wall and wait seconds,
each run's counts, time per cell by set and version (timing.py), the watcher's pace and backlog ETA
(runs.py), and `sdlab-ladder cost` (cost.py)."""

import sqlite3
import time

import pytest
from fastapi.testclient import TestClient

from sdlab.ladder import cli, runner, runs, store, timing
from sdlab.ladder import cases as casemod


@pytest.fixture(autouse=True)
def cache(tmp_path, monkeypatch):
    monkeypatch.setenv("SDLAB_LADDER_CACHE", str(tmp_path / "ladder"))
    return tmp_path / "ladder"


def item(case="003-chain-2", variant="none-short", strategy="matrix"):
    return runner.plan([case], [{"name": strategy, "hash": "m1"}], [variant])[0]


def test_a_result_records_its_times_and_the_plan_does_not_change():
    it = item()
    row = runner.run_item(it, run_id=None, queued=time.time() - 2)
    assert row["status"] == "pass"
    assert row["seconds"] >= 0 and row["score_seconds"] > 0 and row["wall_seconds"] >= row["seconds"] + row["score_seconds"] - 1e-3
    assert 2 <= row["wait_seconds"] < 60
    store.record(row)
    got = store.latest()[0]
    assert {k: got[k] for k in ("score_seconds", "wall_seconds", "wait_seconds")} == {k: row[k] for k in ("score_seconds", "wall_seconds", "wait_seconds")}
    assert runner.plan(["003-chain-2"], [{"name": "matrix", "hash": row["strategy_hash"]}], ["none-short"]) == [], "times are in no hash"


def test_a_timeout_records_its_wall_seconds(monkeypatch):
    monkeypatch.setattr(runner, "discover", lambda *a: time.sleep(5))
    row = runner.run_item(item(), timeout=0.3)
    assert row["status"] == "timeout" and row.get("seconds") is None and 0.3 <= row["wall_seconds"] < 3


def test_a_run_records_its_workers_backlog_and_counts(monkeypatch):
    items = [item(variant=v) for v in ("none-short", "none-long")]
    real, calls = runner.discover, []

    def flaky(strategy, model, d):
        calls.append(1)
        if len(calls) == 1:
            raise ValueError("no luck")
        return real(strategy, model, d)
    monkeypatch.setattr(runner, "discover", flaky)
    rows = runner.execute(items, jobs=1, command="watch", backlog=50)
    assert sorted(r["status"] for r in rows) == ["error", "pass"]
    r = store.runs(5)[0]
    assert (r["command"], r["total"], r["jobs"], r["backlog"], r["done"], r["errors"], r["timeouts"]) == ("watch", 2, 1, 50, 2, 1, 0)
    assert r["finished"] and r["pid"] and r["busy"] > 0
    assert {x["run_id"] for x in store.latest()} == {r["id"]}
    assert runs.state_of(r) == "finished"


def test_an_old_store_gains_the_new_columns(cache):
    cache.mkdir(parents=True)
    con = sqlite3.connect(cache / "results.sqlite")
    con.executescript("""
        CREATE TABLE results (id INTEGER PRIMARY KEY AUTOINCREMENT, case_id TEXT NOT NULL, case_hash TEXT NOT NULL, variant TEXT NOT NULL,
            strategy TEXT NOT NULL, strategy_hash TEXT NOT NULL, score_hash TEXT NOT NULL, at TEXT NOT NULL, latest INTEGER NOT NULL DEFAULT 1,
            status TEXT NOT NULL, seconds REAL, error TEXT, scores TEXT, found TEXT);
        CREATE TABLE runs (id INTEGER PRIMARY KEY AUTOINCREMENT, command TEXT, started TEXT NOT NULL, finished TEXT, total INTEGER NOT NULL DEFAULT 0);
        INSERT INTO results (case_id, case_hash, variant, strategy, strategy_hash, score_hash, at, status, seconds)
            VALUES ('003-chain-2', 'c', 'none-short', 'matrix', 'm1', 's', '2026-10-18T00:00:00Z', 'pass', 0.5);
        INSERT INTO runs (command, started, finished, total) VALUES ('watch', '2026-10-18T00:00:00Z', '2026-10-18T00:10:00Z', 100);
    """)
    con.commit()
    con.close()
    old = store.latest()[0]
    assert old["seconds"] == 0.5 and "score_seconds" not in old, "an old row reads as before"
    r = store.runs()[0]
    assert r["done"] is None and runs.done_of(r) == 100
    assert store.times_after(0)[0][-3:] == (0.5, None, None)


def rec(case, strategy, h, secs, status="pass", score_s=None, wall=None, variant="none-short"):
    store.record({"case": case, "variant": variant, "strategy": strategy, "case_hash": "c", "strategy_hash": h, "score_hash": "s",
                  "status": status, "seconds": secs, "score_seconds": score_s, "wall_seconds": wall})


SETS = {"a": "tests", "b": "tests", "c": "tests", "d": "tests", "e": "tests", "r": "realistic"}


def test_time_per_cell_by_set_version_and_trend():
    for i, case in enumerate("abcde"):
        rec(case, "s1", "v1", 1.0 + i)                      # v1: 1..5 s
    for i, case in enumerate("abcde"):
        rec(case, "s1", "v2", 2.0 * (1.0 + i), score_s=0.5)   # v2: twice as slow on the same cells
    rec("r", "s1", "v2", None, status="timeout")             # a timeout counts as its limit
    t = timing.table()
    st = timing.stats(t, "s1", SETS)
    assert st["sets"]["tests"] == [6.0, 10.0, 5]
    assert st["sets"]["realistic"][2] == 1 and st["sets"]["realistic"][0] == runner.case_timeout("r", timing.WATCH_TIMEOUT)
    assert st["score"]["tests"] == [0.5, 5]
    assert st["trend"] == {"ratio": 2.0, "n": 5, "hash": "v2", "prev": "v1"}
    vs = timing.versions(t, "s1", SETS)
    assert [v["hash"] for v in vs] == ["v1", "v2"] and vs[0]["sets"]["tests"] == [3.0, 5.0, 5]
    rec("a", "s1", "v2", 100.0)                              # topped up: only what is new is read
    assert timing.table() is t and timing.stats(t, "s1", SETS)["sets"]["tests"][0] == 8.0


def test_p95_is_the_nearest_rank():
    assert timing.p95([]) is None and timing.p95([3.0]) == 3.0
    assert timing.p95([float(i) for i in range(1, 101)]) == 95.0 and timing.p95([float(i) for i in range(1, 21)]) == 19.0


def test_set_of():
    assert timing.set_of(casemod.load("003-chain-2")) == "tests"
    assert timing.set_of({"tags": ["noisy"]}) == "noisy" and timing.set_of({"tags": ["canonical"]}) == "canonical"
    assert timing.set_of({"example": "x", "tags": []}) == "realistic" and timing.set_of({"physics": {"system": "x"}, "tags": []}) == "physics"
    assert timing.set_of({"real": {"x": 1}, "tags": ["real"]}) == "real" and timing.set_of({"particles": {"x": 1}, "tags": []}) == "physics"


def test_a_cell_s_cost_comes_from_the_best_evidence():
    rec("a", "s1", "v1", 2.0, score_s=1.0, wall=3.5)         # its own wall time
    rec("b", "s1", "v1", 2.0)                                # old: discovery only; scoring from other strategies on the cell
    rec("b", "s2", "v1", 9.0, score_s=0.25)
    rec("c", "s2", "v1", 4.0)                                # s1 never ran c: the cell's median over strategies
    rec("d", "s3", "v1", 6.0)                                # s1 never ran e, nobody did: s1's median in the set
    est = timing.Estimator(timing.table(), SETS)
    assert est.estimate("a", "none-short", "s1") == (3.5, "measured")
    assert est.estimate("a", "none-short", "s1", "rescore") == (1.0, "measured")
    assert est.estimate("b", "none-short", "s1") == (2.25, "measured")
    assert est.estimate("c", "none-short", "s1")[1] == "cell" and est.estimate("c", "none-short", "s1")[0] == pytest.approx(4.0 + est.scoring("c", "none-short", "s1")[0])
    assert est.estimate("e", "none-short", "s1")[1] == "strategy"
    assert est.estimate("e", "none-short", "s9")[1] == "set"
    assert est.estimate("x", "none-short", "s1") == (0.0, "unknown")
    rec("d", "s1", "v1", 1000.0, score_s=2.0)                # run with a longer timeout: the watcher stops it at 300 s
    est = timing.Estimator(timing.table(), SETS)
    assert est.estimate("d", "none-short", "s1") == (timing.WATCH_TIMEOUT + 2.0, "measured")


def test_pace_eta_and_backlog():
    now = time.time()
    iso = runs._iso
    batches = [{"id": 2, "command": "watch", "started": iso(now - 1800), "finished": None, "total": 2000, "done": 1000, "jobs": 4,
                "busy": 3600.0, "pid": None, "errors": 0, "timeouts": 0},
               {"id": 1, "command": "watch", "started": iso(now - 3600), "finished": iso(now - 1800), "total": 2000, "done": None, "jobs": None,
                "busy": None, "pid": None}]
    pc = runs.pace(6, now, batches)
    assert pc["per_hour"] == pytest.approx(3000, rel=1e-3) and pc["done"] == 3000 and pc["batches"] == 2
    assert pc["efficiency"] == pytest.approx(3600 / (1800 * 4), rel=1e-3) and pc["jobs"] == 4
    bl = {"items": 6000, "seconds": 7200.0}
    e = runs.eta(bl, pc, now)
    assert e["by_pace"] == 2.0 and e["by_cost"] == pytest.approx(1.0, abs=0.01) and e["ideal"] == 0.5 and e["at"]

    rec("a", "s1", "v1", 2.0, wall=3.0)
    sm = {"cases": [{"id": "a"}, {"id": "b"}],
          "cells": [{"case": "a", "variant": "none-short", "strategy": "s1", "stale": "strategy changed"},
                    {"case": "b", "variant": "none-short", "strategy": "s1", "stale": None},
                    {"case": "a", "variant": "none-short", "strategy": "s2", "stale": "new"}]}
    got = runs.backlog(sm, timing.Estimator(timing.table(), SETS))
    assert (got["items"], got["run"], got["rescore"]) == (2, 2, 0) and got["seconds"] == pytest.approx(3.0 + 2.0) and got["by_set"]["tests"][0] == 2


def test_the_cost_command(capsys, monkeypatch):
    monkeypatch.setattr(casemod, "case_ids", lambda: ["003-chain-2"])    # every case's first load in a fresh cache takes minutes
    assert cli.main(["run", "--strategies", "matrix", "--cases", "003", "--variants", "none-short,none-long", "--jobs", "1", "--quiet"]) == 0
    capsys.readouterr()
    assert cli.main(["cost", "--strategies", "matrix", "--cases", "003", "--server", "http://127.0.0.1:9"]) == 0
    out = capsys.readouterr().out
    assert "Cost of re-running matrix on 1 cases: 4 items" in out and "busy time" in out and "wall time at" in out
    assert "2 its own stored time" in out and "2 other strategies on the cell" not in out
    assert cli.main(["cost", "--strategies", "matrix", "--cases", "003", "--stale", "--server", "http://127.0.0.1:9"]) == 0
    assert "2 items" in capsys.readouterr().out, "two variants never ran"


def test_the_endpoints_answer_from_memory(monkeypatch, tmp_path):
    monkeypatch.setenv("SDLAB_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(casemod, "case_ids", lambda: ["003-chain-2"])    # as above: one case, not every case's first load
    cli.main(["run", "--strategies", "matrix", "--cases", "003", "--variants", "none-short", "--jobs", "1", "--quiet"])
    from sdlab.server import create_app
    with TestClient(create_app()) as c:
        for url in ("/api/ladder/timing", "/api/ladder/timing/matrix", "/api/ladder/runs"):
            for _ in range(600):
                got = c.get(url).json()
                if not got.get("pending"):
                    break
                time.sleep(0.1)
            assert not got.get("pending"), url
        assert c.get("/api/ladder/timing").json()["strategies"]["matrix"]["sets"]["tests"][2] == 1
        one = c.get("/api/ladder/timing/matrix").json()
        assert one["versions"][0]["n"] == 1
        p = c.get("/api/ladder/runs").json()
        assert p["runs"][0]["command"] == "run" and p["runs"][0]["done"] == 1 and "backlog" in p["watcher"]
        assert c.get("/api/ladder/timing/nope").status_code == 404
