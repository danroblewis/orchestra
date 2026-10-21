"""On the pool, none-long only confirms a none-short pass (confirm.py; the user, 2026-10-20), as the local
planner does (tests/test_ladder_confirm_long.py): held until the same job's none-short result comes, then
queued on a pass and skipped otherwise; decided at once from a stored current result; kept by jobs that
name none-long or ask for every variant; followed by the main line. Uses test_pool's fake worker."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from sdlab.ladder import store
from sdlab.ladder.pool import agent, cli, db, jobs, planner
from test_pool import FakeWorker, H, MAIN, submit
from test_pool import pool as pool  # noqa: F401  (the fixture)


def confirm_plan(commit: str, spec: dict) -> dict:
    strategies = {"s1": "h1", "s2": "h2"}
    want = spec.get("strategies") or "all"
    if want not in ("all", "everything"):
        strategies = {k: v for k, v in strategies.items() if k in want.split(",")}
    cases = {"c1": {"hash": "ch1", "tags": [], "timeout": 300, "variants": [
        {"name": "none-short", "noise": "none", "length": "short", "steps": 40, "score_hash": "sc-s"},
        {"name": "none-long", "noise": "none", "length": "long", "steps": 400, "score_hash": "sc-l"},
        {"name": "counts-long", "noise": "counts", "length": "long", "steps": 400, "score_hash": "sc-c"}]}}
    return {"strategies": strategies, "skipped": {}, "parked": [], "retired": [], "cases": cases}


@pytest.fixture
def cpool(pool, monkeypatch):  # noqa: F811
    monkeypatch.setattr(planner, "RUN", confirm_plan)
    return pool


def _states(job_id: int) -> dict:
    with db.connect(readonly=True) as con:
        return {(r[0], r[1]): (r[2], r[3]) for r in con.execute(
            "SELECT variant, strategy, state, error FROM pool_items WHERE job_id = ?", (job_id,))}


def _job(client, job_id: int) -> dict:
    return client.get(f"/api/pool/jobs/{job_id}").json()["job"]


def _record(variant: str, strategy: str, status: str, score_hash: str) -> None:
    store.record({"case": "c1", "variant": variant, "strategy": strategy, "case_hash": "ch1", "strategy_hash": {"s1": "h1", "s2": "h2"}[strategy],
                  "score_hash": score_hash, "status": status, "found": []})


def test_none_long_waits_for_the_jobs_none_short_then_runs_or_is_skipped(cpool):
    j = submit(cpool, strategies="s1,s2", cases="c1")
    assert j["total"] == 6 and j["counts"]["held"] == 2 and j["counts"]["queued"] == 4
    w = FakeWorker(cpool)
    first = w.claim(slots=10)
    assert {(i["variant"], i["strategy"]) for i in first} == {(v, s) for v in ("none-short", "counts-long") for s in ("s1", "s2")}
    for it in first:                                                      # s1's none-short passes, s2's fails
        assert w.post(it, status="fail" if (it["variant"], it["strategy"]) == ("none-short", "s2") else "pass").status_code == 200
    st = _states(j["id"])
    assert st[("none-long", "s1")][0] == "queued"
    assert st[("none-long", "s2")] == ("skipped", "skipped: none-short did not pass (fail)")
    got = w.claim(slots=10)
    assert [(i["variant"], i["strategy"]) for i in got] == [("none-long", "s1")]
    w.post(got[0])
    j = _job(cpool, j["id"])
    assert j["state"] == "done" and j["counts"]["skipped"] == 1 and j["counts"]["done"] == 5
    assert j["statuses"] == {"pass": 4, "fail": 1}                          # the skipped item is no result and no fail
    res = cpool.get(f"/api/pool/jobs/{j['id']}/results").json()["results"]
    assert len(res) == 5 and not any(r["variant"] == "none-long" and r["strategy"] == "s2" for r in res)
    line = cli._job_line(j)
    assert "6/6 done" in line and "1 skipped: none-short did not pass" in line
    assert "1 none-long skipped" in agent.summary(j, res)
    assert not store.latest("c1", "none-long", "s2")                       # never stored


def test_a_held_item_is_never_handed_out_or_accepted(cpool):
    j = submit(cpool, strategies="s1", cases="c1")
    w = FakeWorker(cpool)
    assert all(i["variant"] != "none-long" for i in w.claim(slots=10))
    with db.connect(readonly=True) as con:
        hid = con.execute("SELECT id FROM pool_items WHERE job_id = ? AND variant = 'none-long'", (j["id"],)).fetchone()[0]
    fake = {"item_id": hid, "lease_id": "x", "commit": MAIN, "case": "c1", "variant": "none-long", "strategy": "s1",
            "case_hash": "ch1", "strategy_hash": "h1", "score_hash": "sc-l"}
    assert w.post(fake).json() == {"accepted": False, "stale": True, "state": "held"}
    assert _job(cpool, j["id"])["state"] == "running"                     # held items keep the job open


@pytest.mark.parametrize("body", [{"every_variant": True}, {"variants": "none-long"}, {"variants": "none-short,none-long"}])
def test_every_variant_or_naming_none_long_keeps_it(cpool, body):
    j = submit(cpool, strategies="s1,s2", cases="c1", **body)
    assert j["counts"]["held"] == 0 and j["counts"]["skipped"] == 0
    assert all(st == "queued" for st, _ in _states(j["id"]).values())


def test_a_stored_current_none_short_decides_at_expansion(cpool):
    _record("none-short", "s1", "pass", "sc-s")
    _record("none-short", "s2", "fail", "sc-s")
    j = submit(cpool, strategies="s1,s2", cases="c1")                     # none-short reused: decided now
    st = _states(j["id"])
    assert st[("none-short", "s1")][0] == "reused" and st[("none-long", "s1")][0] == "queued"
    assert st[("none-long", "s2")] == ("skipped", "skipped: none-short did not pass (fail)")
    j2 = submit(cpool, strategies="s1,s2", cases="c1", variants="long")    # none-short not in the job: the store decides
    st2 = _states(j2["id"])
    assert st2[("none-long", "s1")][0] == "queued" and st2[("none-long", "s2")][0] == "skipped"


def test_no_current_none_short_means_skipped_and_a_fresh_job_holds(cpool):
    _record("none-short", "s1", "pass", "an-old-score-hash")              # stale: not current
    j = submit(cpool, strategies="s1", cases="c1", variants="long")
    assert _states(j["id"])[("none-long", "s1")] == ("skipped", "skipped: none-short did not pass (no current result)")
    _record("none-short", "s1", "pass", "sc-s")
    j2 = submit(cpool, strategies="s1", cases="c1", fresh=True)           # fresh: none-short runs again, so none-long waits for it
    assert _states(j2["id"])[("none-long", "s1")][0] == "held"


def test_a_none_short_that_errors_or_is_cancelled_skips_its_long(cpool):
    j = submit(cpool, strategies="s1", cases="c1", variants="none")
    small, large = FakeWorker(cpool, name="small", free_mb=8000), FakeWorker(cpool, name="large", free_mb=40000)
    small.heartbeat()
    large.heartbeat()
    short = small.claim(slots=10)[0]
    assert short["variant"] == "none-short"                               # the only item handed out: none-long is held
    small.post(short, outcome="crashed", free=8000)
    short = large.claim(slots=10)[0]
    large.post(short, outcome="crashed", free=40000)                      # the second crash: an error result
    assert _states(j["id"])[("none-long", "s1")] == ("skipped", "skipped: none-short did not pass (error)")
    j2 = submit(cpool, strategies="s2", cases="c1")
    assert cpool.delete(f"/api/pool/jobs/{j2['id']}", headers=H).json()["job"]["state"] == "cancelled"
    assert _states(j2["id"])[("none-long", "s2")][0] == "cancelled"


def test_the_main_line_follows_the_rule(cpool):
    w = FakeWorker(cpool, name="mac-pool", machine="mac", free_mb=60000)
    w.heartbeat()
    got = jobs.refresh_mainline(force=True)
    assert got["held"] == 2 and got["queued"] == 4
    for it in w.claim(slots=10):
        w.post(it, status="fail" if (it["variant"], it["strategy"]) == ("none-short", "s2") else "pass")
    st = _states(got["job"])
    assert st[("none-long", "s1")][0] == "queued" and st[("none-long", "s2")][0] == "skipped"
    w.run_all()
    assert store.latest("c1", "none-long", "s1") and not store.latest("c1", "none-long", "s2")
    again = jobs.refresh_mainline(force=True)                              # only the skipped none-long is stale: no new job
    assert again == {"queued": 0, "head": MAIN, "skipped_long": 1}
    s = cpool.get("/api/pool/status").json()
    assert "held" in s["totals"] and "skipped" in s["mainline"]


def test_the_main_line_holds_for_a_none_short_running_in_an_earlier_generation(cpool, monkeypatch):
    w = FakeWorker(cpool, name="mac-pool", machine="mac", free_mb=60000)
    w.heartbeat()
    g1 = jobs.refresh_mainline(force=True)
    short = next(i for i in w.claim(slots=10) if (i["variant"], i["strategy"]) == ("none-short", "s1"))
    with db.LOCK, db.connect() as con:                                    # the earlier generation's other items are gone
        con.execute("UPDATE pool_items SET state = 'cancelled', lease_id = NULL WHERE job_id = ? AND id != ?", (g1["job"], short["item_id"]))
    g2 = jobs.refresh_mainline(force=True)                                 # a new generation while none-short s1 still runs in g1
    assert g2["job"] != g1["job"]
    st = _states(g2["job"])
    assert ("none-short", "s1") not in st and st[("none-long", "s1")][0] == "held"
    w.post(short, status="pass")
    assert _states(g2["job"])[("none-long", "s1")][0] == "queued"


def test_status_and_page_show_held_and_skipped(cpool):
    _record("none-short", "s2", "fail", "sc-s")
    submit(cpool, strategies="s1,s2", cases="c1")
    s = cpool.get("/api/pool/status").json()
    assert s["totals"]["held"] == 1 and s["totals"]["skipped"] == 1 and s["jobs"][0]["counts"]["skipped"] == 1
    line = cli._job_line(s["jobs"][0])
    assert "1 held for their none-short" in line and "1 skipped" in line
    page = (Path(__file__).resolve().parents[1] / "sdlab" / "static" / "pool.html").read_text()
    assert "c.held" in page and "c.skipped" in page and "s.totals.skipped" in page


def test_an_older_pool_items_table_gains_the_column(tmp_path, monkeypatch):
    monkeypatch.setenv("SDLAB_LADDER_CACHE", str(tmp_path / "cache"))
    db.reset_cache()
    p = store.path()
    p.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(p)
    con.executescript(db.SCHEMA)                                          # the tables as they were made before confirm_id
    assert "confirm_id" not in {r[1] for r in con.execute("PRAGMA table_info(pool_items)")}
    con.execute("INSERT INTO pool_items (job_id, case_id, variant, strategy, case_hash, strategy_hash, score_hash) VALUES (1, 'c', 'v', 's', 'a', 'b', 'c')")
    con.commit()
    con.close()
    with db.connect() as con:
        cols = {r[1] for r in con.execute("PRAGMA table_info(pool_items)")}
        assert "confirm_id" in cols
        assert con.execute("SELECT COUNT(*) FROM pool_items").fetchone()[0] == 1
    db.reset_cache()
