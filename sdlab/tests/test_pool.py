"""The CPU pool's server side (docs/pool.md) against a fake worker speaking its HTTP API: the token, jobs and
their planning, priorities, leases and heartbeats, idempotent posts, hash rejection, crashes and memory
admission, the standing main-line job and the main line's latest rule. The planner (a checkout at the
job's commit) and the repository's refs are replaced by fakes; the bundle test uses the real repository."""

from __future__ import annotations

import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from sdlab.ladder import store
from sdlab.ladder.pool import accept, db, gitcode, jobs, leases, planner
from sdlab.ladder.pool.routes import router

MAIN = "a" * 40          # the sdlab branch's HEAD
FEATURE = "b" * 40       # a feature branch: s1's code differs
TOKEN = "test-token-123"


def fake_plan(commit: str, spec: dict) -> dict:
    strategies = {"s1": "h1" if commit == MAIN else "h1-feature", "s2": "h2", "slow": "h3"}
    want = spec.get("strategies") or "all"
    if want not in ("all", "everything"):
        strategies = {k: v for k, v in strategies.items() if k in want.split(",")}
    cases = {
        "c1": {"hash": "ch1", "tags": [], "timeout": 300, "variants": [
            {"name": "none", "noise": "none", "length": "short", "steps": 40, "score_hash": "sc1"},
            {"name": "counts-long", "noise": "counts", "length": "long", "steps": 400, "score_hash": "sc1"}]},
        "big": {"hash": "ch2", "tags": ["realistic", "heavy", "kubernetes"], "timeout": 1800, "variants": [
            {"name": "none", "noise": "none", "length": "short", "steps": 2000, "score_hash": "sc2"}]},
        "k8s": {"hash": "ch3", "tags": ["kubernetes"], "timeout": 300, "variants": [
            {"name": "none", "noise": "none", "length": "short", "steps": 40, "score_hash": "sc3"}]},
    }
    if spec.get("cases") not in (None, "*", "all"):
        cases = {k: v for k, v in cases.items() if k in spec["cases"].split(",")}
    return {"strategies": strategies, "skipped": {}, "parked": ["slow"], "retired": [], "cases": cases}


@pytest.fixture
def pool(tmp_path, monkeypatch):
    monkeypatch.setenv("SDLAB_LADDER_CACHE", str(tmp_path / "cache"))
    monkeypatch.setenv("SDLAB_POOL_HOME", str(tmp_path / "pool"))
    tok = tmp_path / "pool.token"
    tok.write_text(TOKEN + "\n")
    monkeypatch.setenv("SDLAB_POOL_TOKEN_FILE", str(tok))
    monkeypatch.setenv("SDLAB_MACHINE", "mac")
    monkeypatch.setattr(planner, "RUN", fake_plan)
    monkeypatch.setattr(jobs, "BACKGROUND", False)
    monkeypatch.setattr(jobs, "PAUSED", tmp_path / "watch.paused")
    refs = {"sdlab": MAIN, "feature": FEATURE, MAIN: MAIN, FEATURE: FEATURE, "HEAD": MAIN}
    monkeypatch.setattr(gitcode, "resolve", lambda ref: refs.get(ref))
    monkeypatch.setattr(gitcode, "main_head", lambda: MAIN)
    monkeypatch.setattr(gitcode, "checkout_head", lambda: MAIN)
    monkeypatch.setattr(gitcode, "dirty", lambda strategies, harness: [])
    accept._index.clear()
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


H = {"X-Pool-Token": TOKEN}


class FakeWorker:
    """A worker as docs/pool.md describes it: heartbeat, claim, run (here: make up a row), post."""

    def __init__(self, client: TestClient, name="node2-pool", machine="node2", free_mb=30000.0, heavy_free=2):
        self.c, self.name, self.machine, self.free_mb, self.heavy_free = client, name, machine, free_mb, heavy_free
        self.held: dict[str, dict] = {}

    def heartbeat(self) -> dict:
        r = self.c.post("/api/pool/heartbeat", headers=H, json={
            "worker": self.name, "machine": self.machine, "slots": 4, "busy": len(self.held), "cpus": 24, "load": 3.0,
            "mem_total_mb": 63000, "mem_free_mb": self.free_mb, "heavy_slots": 2, "leases": list(self.held)})
        assert r.status_code == 200, r.text
        return r.json()

    def claim(self, slots=4) -> list[dict]:
        r = self.c.post("/api/pool/claim", headers=H, json={"worker": self.name, "machine": self.machine, "slots": slots,
                                                            "free_mb": self.free_mb, "heavy_free": self.heavy_free})
        assert r.status_code == 200, r.text
        items = r.json()["items"]
        self.held.update({i["lease_id"]: i for i in items})
        return items

    def post(self, item: dict, status="pass", hashes=None, outcome="result", peak=900.0, free=None):
        hashes = hashes or {k: item[k] for k in ("case_hash", "strategy_hash", "score_hash")}
        row = {"case": item["case"], "variant": item["variant"], "strategy": item["strategy"], **hashes, "status": status,
               "seconds": 0.5, "wall_seconds": 0.9, "scores": {"status": status}, "found": [{"from": "x", "to": None}], "code_commit": item["commit"]}
        r = self.c.post("/api/pool/results", headers=H, json={
            "worker": self.name, "machine": self.machine, "slot": 1, "item_id": item["item_id"], "lease_id": item["lease_id"],
            "commit": item["commit"], "outcome": outcome, "hashes": hashes, "peak_rss_mb": peak, "free_mb": free or self.free_mb,
            "row": row, "error": "BrokenProcessPool: A process in the process pool was terminated abruptly" if outcome == "crashed" else None})
        self.held.pop(item["lease_id"], None)
        return r

    def run_all(self) -> int:
        n = 0
        while True:
            items = self.claim()
            if not items:
                return n
            for it in items:
                assert self.post(it).status_code == 200
                n += 1


def submit(client, **body) -> dict:
    r = client.post("/api/pool/jobs", headers=H, json={"by": "agent-test", **body})
    assert r.status_code == 202, r.text
    jobs.plan_pending()
    return client.get(f"/api/pool/jobs/{r.json()['job']['id']}").json()["job"]


def test_writing_endpoints_need_the_token(pool):
    body = {"worker": "w", "machine": "m", "slots": 1, "free_mb": 1000}
    assert pool.post("/api/pool/claim", json=body).status_code == 401
    assert pool.post("/api/pool/claim", json=body, headers={"X-Pool-Token": "wrong"}).status_code == 401
    assert pool.post("/api/pool/claim", json=body, headers={"Authorization": f"Bearer {TOKEN}"}).status_code == 200
    assert pool.post("/api/pool/jobs", json={}).status_code == 401
    assert pool.post("/api/pool/results", json={}).status_code == 401
    assert pool.post("/api/pool/heartbeat", json={}).status_code == 401
    assert pool.delete("/api/pool/jobs/1").status_code == 401
    assert pool.get("/api/pool/code/head").status_code == 401
    assert pool.get("/api/pool/code/bundle?want=" + MAIN).status_code == 401
    assert pool.get("/api/pool/status").status_code == 200          # read-only: no token
    assert pool.get("/api/pool/jobs").status_code == 200


def test_submit_plans_the_items_at_the_commit(pool):
    j = submit(pool, strategies="s1,s2", cases="c1")
    assert j["state"] == "queued" and j["commit"] == MAIN and j["total"] == 4       # 2 strategies x 2 variants
    j2 = submit(pool, strategies="s1", cases="c1", variants="counts")
    assert j2["total"] == 1
    assert pool.post("/api/pool/jobs", headers=H, json={"ref": "nope"}).status_code == 404
    assert pool.post("/api/pool/jobs", headers=H, json={"priority": 0}).status_code == 400


def test_a_dirty_checkout_is_refused(pool, monkeypatch):
    monkeypatch.setattr(gitcode, "dirty", lambda strategies, harness: ["sdlab/sdlab/discovery/strategies/s1.py"])
    r = pool.post("/api/pool/jobs", headers=H, json={"strategies": "s1"})
    assert r.status_code == 409 and r.json()["files"] == ["sdlab/sdlab/discovery/strategies/s1.py"]
    assert pool.post("/api/pool/jobs", headers=H, json={"strategies": "s1", "ref": "feature"}).status_code == 202   # another commit: not the tree


def test_fake_worker_runs_a_job_and_posts_are_idempotent(pool):
    j = submit(pool, strategies="s1", cases="c1")
    w = FakeWorker(pool)
    w.heartbeat()
    items = w.claim()
    assert len(items) == 2 and {i["variant"] for i in items} == {"none", "counts-long"}
    assert items[0]["variant"] == "counts-long"                        # slow first
    assert w.claim() == []                                              # nothing is handed out twice
    first = w.post(items[0]).json()
    assert first["accepted"] and first["result_id"]
    again = pool.post("/api/pool/results", headers=H, json={"worker": w.name, "machine": "node2", "item_id": items[0]["item_id"],
                                                            "lease_id": items[0]["lease_id"], "commit": MAIN, "hashes": {}, "row": {}})
    assert again.status_code == 200 and again.json()["duplicate"] and again.json()["result_id"] == first["result_id"]
    w.post(items[1])
    done = pool.get(f"/api/pool/jobs/{j['id']}").json()["job"]
    assert done["state"] == "done" and done["counts"]["done"] == 2 and done["statuses"] == {"pass": 2}
    res = pool.get(f"/api/pool/jobs/{j['id']}/results?full=1").json()["results"]
    assert len(res) == 2 and all(r["machine"] == "node2" and r["slot"] == "1" and r["commit"] == MAIN for r in res)
    with db.connect(readonly=True) as con:
        assert con.execute("SELECT COUNT(*) FROM pool_results").fetchone()[0] == 2


def test_agent_jobs_come_before_the_main_line(pool):
    FakeWorker(pool).heartbeat()
    assert jobs.refresh_mainline(force=True)["queued"] > 0
    j = submit(pool, strategies="s2", cases="c1", priority=100)
    w = FakeWorker(pool, name="other")
    got = w.claim(slots=2)
    assert [g["job_id"] for g in got] == [j["id"], j["id"]]
    rest = w.claim(slots=50)
    assert rest and all(g["job_id"] != j["id"] for g in rest)


def test_a_result_whose_hashes_differ_is_rejected(pool):
    submit(pool, strategies="s1", cases="c1", variants="none")
    w = FakeWorker(pool)
    it = w.claim()[0]
    r = w.post(it, hashes={"case_hash": "ch1", "strategy_hash": "other", "score_hash": "sc1"})
    assert r.status_code == 409 and "strategy_hash" in r.json()["rejected"]
    it2 = w.claim()[0]
    assert it2["item_id"] == it["item_id"]                              # back in the queue
    assert w.post(it2, hashes={"case_hash": "ch1", "strategy_hash": "other", "score_hash": "sc1"}).status_code == 409
    with db.connect(readonly=True) as con:
        st = con.execute("SELECT state, error FROM pool_items WHERE id = ?", (it["item_id"],)).fetchone()
        assert st["state"] == "error" and "rejected 2 times" in st["error"]
        assert con.execute("SELECT COUNT(*) FROM pool_results").fetchone()[0] == 0     # a wrong result is never stored
    wrong_commit = pool.post("/api/pool/results", headers=H, json={"worker": "x", "machine": "m", "item_id": it["item_id"], "commit": FEATURE,
                                                                   "outcome": "result", "hashes": {}, "row": {}})
    assert wrong_commit.status_code == 200                              # already an error: nothing more is taken


def test_an_expired_lease_goes_back_and_the_first_valid_result_wins(pool, monkeypatch):
    submit(pool, strategies="s1", cases="c1", variants="none")
    a, b = FakeWorker(pool, name="a"), FakeWorker(pool, name="b")
    it = a.claim()[0]
    with db.connect() as con:
        con.execute("UPDATE pool_items SET lease_expires = ? WHERE id = ?", (time.time() - 1, it["item_id"]))
    it_b = b.claim()[0]
    assert it_b["item_id"] == it["item_id"] and it_b["lease_id"] != it["lease_id"]
    hb = a.heartbeat()
    assert it["lease_id"] in hb["lost"]                                 # a must stop it
    assert b.heartbeat()["renewed"] == [it_b["lease_id"]]
    assert a.post(it).json()["accepted"]                                # a valid result, though late, is the first
    assert b.post(it_b).json()["duplicate"]


def test_a_lease_lost_three_times_is_an_error(pool):
    submit(pool, strategies="s1", cases="c1", variants="none")
    w = FakeWorker(pool)
    for _ in range(leases.LOST_LIMIT):
        got = w.claim()
        assert got
        with db.connect() as con:
            con.execute("UPDATE pool_items SET lease_expires = ? WHERE state = 'leased'", (time.time() - 1,))
    assert w.claim() == []
    with db.connect(readonly=True) as con:
        assert con.execute("SELECT state FROM pool_items").fetchone()[0] == "error"


def test_a_crash_is_retried_once_with_more_memory_then_recorded(pool):
    submit(pool, strategies="s1", cases="c1", variants="none")
    small, large = FakeWorker(pool, name="small", free_mb=8000), FakeWorker(pool, name="large", free_mb=40000)
    small.heartbeat()
    large.heartbeat()
    it = small.claim()[0]
    r = small.post(it, outcome="crashed", free=8000)
    assert r.json() == {"accepted": True, "retry": True}
    assert small.claim() == []                                          # not again where it crashed
    it2 = large.claim()[0]
    assert it2["item_id"] == it["item_id"]
    final = large.post(it2, outcome="crashed", free=40000).json()
    assert final["accepted"] and final["result_id"]
    res = pool.get("/api/pool/jobs/1/results?full=1").json()["results"]
    assert res[0]["status"] == "error" and "died twice" in res[0]["error"]
    assert "BrokenProcessPool" not in res[0]["error"]                   # the main line does not take it for a crash to run again


def test_a_retry_never_needs_more_than_the_biggest_worker_can_promise(pool):
    submit(pool, strategies="s1", cases="c1", variants="none")
    w = FakeWorker(pool, name="mac-pool", machine="mac", free_mb=60000)    # mem_total 63000, no budget_mb sent: 85% of it
    w.heartbeat()
    it = w.claim()[0]
    assert w.post(it, outcome="crashed", free=60000, peak=33000).json()["retry"]
    with db.connect(readonly=True) as con:
        need = con.execute("SELECT min_free_mb FROM pool_items WHERE id = ?", (it["item_id"],)).fetchone()[0]
    assert need == pytest.approx(0.9 * 0.85 * 63000)                     # not 1.25 x 60000, which no worker could promise
    w.free_mb = need + 2000
    again = w.claim()[0]
    assert again["item_id"] == it["item_id"] and again["expected_peak_mb"] >= need / 1.25   # its hard limit rises with it


def test_memory_admission_and_heavy_slots(pool):
    submit(pool, strategies="s1", cases="big")
    w = FakeWorker(pool, free_mb=12000, heavy_free=2)
    assert w.claim() == []                                              # a heavy case's default peak is 16 GB
    w.free_mb, w.heavy_free = 40000, 0
    assert w.claim() == []                                              # no heavy slot free
    w.heavy_free = 1
    it = w.claim()[0]
    assert it["heavy"] and it["expected_peak_mb"] == 16000
    w.post(it, peak=2000.0)
    submit(pool, strategies="s2", cases="big")
    w.free_mb = 4000
    got = w.claim()
    assert got and got[0]["expected_peak_mb"] == pytest.approx(2400.0)  # 1.2 x the peak measured on the case


def test_an_expected_peak_past_every_budget_is_capped_not_queued_for_ever(pool):
    submit(pool, strategies="s1", cases="big")
    w = FakeWorker(pool, free_mb=60000, heavy_free=2)                     # mem_total 63000: biggest budget 53550
    w.heartbeat()
    it = w.claim()[0]
    assert w.post(it, outcome="crashed", free=60000, peak=132000.0).json()["retry"] is True
    it = w.claim()[0]
    final = w.post(it, outcome="crashed", free=60000, peak=132000.0).json()
    assert final["result_id"]                                             # a 132 GB peak is now on record for the case
    submit(pool, strategies="s2", cases="big")
    got = w.claim()
    assert got and got[0]["expected_peak_mb"] == pytest.approx(0.9 * 0.85 * 63000)   # not 1.2 x 132 GB, which nobody admits


def test_only_main_line_hashes_become_latest(pool):
    jobs.mainline_plan(wait=True)
    main_job = submit(pool, strategies="s1", cases="c1", variants="none")
    w = FakeWorker(pool, name="mac-pool", machine="mac-pool")
    got = w.post(w.claim()[0]).json()
    assert got["promoted_id"]
    latest = store.latest("c1", "none", "s1")
    assert latest[0]["id"] == got["promoted_id"] and latest[0]["machine"] == "mac-pool" and latest[0]["strategy_hash"] == "h1"
    feat = submit(pool, ref="feature", strategies="s1", cases="c1", variants="none", fresh=True)
    it = w.claim()[0]
    assert it["strategy_hash"] == "h1-feature" and it["commit"] == FEATURE
    got2 = w.post(it, status="fail").json()
    assert got2["accepted"] and got2["promoted_id"] is None             # stored, queryable by job, never the main line's latest
    assert store.latest("c1", "none", "s1")[0]["id"] == got["promoted_id"]
    assert pool.get(f"/api/pool/jobs/{feat['id']}/results").json()["results"][0]["status"] == "fail"
    assert main_job["commit"] == MAIN


def test_a_job_reuses_a_result_with_exactly_its_hashes(pool):
    store.record({"case": "c1", "variant": "none", "strategy": "s1", "case_hash": "ch1", "strategy_hash": "h1", "score_hash": "sc1",
                  "status": "pass", "found": []})
    store.record({"case": "c1", "variant": "counts-long", "strategy": "s1", "case_hash": "ch1", "strategy_hash": "h1", "score_hash": "old",
                  "status": "fail", "found": [{"from": "a"}]})
    j = submit(pool, strategies="s1", cases="c1")
    assert j["counts"]["reused"] == 1 and j["counts"]["queued"] == 1
    it = FakeWorker(pool).claim()[0]
    assert it["mode"] == "rescore" and it["prev"]["found"] == [{"from": "a"}]
    res = pool.get(f"/api/pool/jobs/{j['id']}/results").json()["results"]
    assert any(r.get("state") == "reused" and r["status"] == "pass" for r in res)


def test_the_standing_job_queues_what_is_stale_on_the_main_line(pool):
    assert jobs.refresh_mainline()["skipped"] == "no live worker"
    w = FakeWorker(pool, name="mac-pool", machine="mac")
    w.heartbeat()
    got = jobs.refresh_mainline(force=True)
    with db.connect(readonly=True) as con:
        cells = {(r[0], r[1], r[2]) for r in con.execute("SELECT case_id, variant, strategy FROM pool_items WHERE job_id = ?", (got["job"],))}
    assert ("k8s", "none", "s1") not in cells                           # tag:kubernetes is left out
    assert ("big", "none", "s1") in cells                               # but tag:heavy is the main line's
    assert not any(s == "slow" for _, _, s in cells)                    # parked strategies are skipped
    assert len(cells) == 6                                              # c1 x 2 variants + big, for s1 and s2
    w.free_mb = 60000
    w.run_all()
    assert jobs.refresh_mainline(force=True) == {"queued": 0, "head": MAIN}     # everything current now
    assert all(r["machine"] == "mac" for r in store.latest())


def test_the_watchers_pause_file_pauses_the_main_line(pool):
    FakeWorker(pool, name="mac-pool", machine="mac").heartbeat()
    jobs.PAUSED.touch()
    assert jobs.refresh_mainline(force=True)["skipped"].startswith("paused")
    jobs.PAUSED.unlink()
    assert jobs.refresh_mainline(force=True)["queued"] > 0


def test_a_cancelled_job_tells_its_worker(pool):
    j = submit(pool, strategies="s1", cases="c1")
    w = FakeWorker(pool)
    it = w.claim(slots=1)[0]
    assert pool.delete(f"/api/pool/jobs/{j['id']}", headers=H).json()["job"]["state"] == "cancelled"
    assert it["lease_id"] in w.heartbeat()["cancel"]
    assert w.post(it).json()["cancelled"]
    assert w.claim() == []


def test_status_lists_workers_queue_and_throughput(pool):
    submit(pool, strategies="s1", cases="c1")
    w = FakeWorker(pool)
    w.heartbeat()
    w.post(w.claim(slots=1)[0])
    s = pool.get("/api/pool/status").json()
    assert s["workers"][0]["name"] == "node2-pool" and s["workers"][0]["live"]
    assert s["jobs"][0]["counts"]["done"] == 1 and s["totals"]["queued"] == 1
    assert s["throughput"]["last_hour"][0] == {"machine": "node2", "results": 1, "busy_seconds": 1}
    assert pool.get("/api/pool/workers").json()["workers"][0]["mem_total_mb"] == 63000


def test_bundle_of_the_real_repository(tmp_path, monkeypatch):
    monkeypatch.setenv("SDLAB_POOL_HOME", str(tmp_path / "pool"))
    head = gitcode.resolve("HEAD")
    prev = gitcode.resolve("HEAD~1")
    data = gitcode.bundle(head, [prev])
    assert data.startswith(b"# v2 git bundle") or data.startswith(b"# v3 git bundle")
    assert b" refs/pool/want" in data.split(b"\n\n", 1)[0]                # in the header (after the prerequisites, whose subjects can be long)
    with pytest.raises(ValueError):
        gitcode.bundle("not-a-sha", [])
    assert isinstance(gitcode.dirty(["matrix"], harness=True), list)


def test_a_stopping_worker_releases_its_leases(pool):
    submit(pool, strategies="s1", cases="c1", variants="none")
    w = FakeWorker(pool)
    it = w.claim()[0]
    other = pool.post("/api/pool/release", headers=H, json={"worker": "someone-else", "leases": [it["lease_id"]]}).json()
    assert other["released"] == []                                      # only the holder can give it back
    assert pool.post("/api/pool/release", json={"worker": w.name, "leases": [it["lease_id"]]}).status_code == 401
    got = pool.post("/api/pool/release", headers=H, json={"worker": w.name, "leases": [it["lease_id"]]}).json()
    assert got["released"] == [it["lease_id"]]
    with db.connect(readonly=True) as con:
        st = con.execute("SELECT state, lost, lease_id FROM pool_items WHERE id = ?", (it["item_id"],)).fetchone()
        assert st["state"] == "queued" and st["lost"] == 0 and st["lease_id"] is None   # not counted as a lost lease
    assert FakeWorker(pool, name="next").claim()[0]["item_id"] == it["item_id"]


# ---- adversarial review (2026-10-20): a resent or stale crash post never ends an item, a result names the
# commit and slot that ran it, a row whose own provenance says other code ran is refused, and a result
# promises the main line nothing once HEAD has moved on ----


def _item(item_id: int):
    with db.connect(readonly=True) as con:
        return con.execute("SELECT * FROM pool_items WHERE id = ?", (item_id,)).fetchone()


def _n_results() -> int:
    with db.connect(readonly=True) as con:
        return con.execute("SELECT COUNT(*) FROM pool_results").fetchone()[0]


def _body(w: FakeWorker, it: dict, **over) -> dict:
    hashes = {k: it[k] for k in ("case_hash", "strategy_hash", "score_hash")}
    row = {"case": it["case"], "variant": it["variant"], "strategy": it["strategy"], **hashes, "status": "pass", "seconds": 0.5,
           "scores": {}, "found": [], "code_commit": it["commit"]}
    body = {"worker": w.name, "machine": w.machine, "slot": 3, "item_id": it["item_id"], "lease_id": it["lease_id"],
            "commit": it["commit"], "outcome": "result", "hashes": hashes, "peak_rss_mb": 500.0, "row": row}
    body.update(over)
    return body


def test_a_resent_crash_post_does_not_make_the_retry_an_error(pool):
    """The outbox resends a post whose answer it did not get: the first crash must stay the only one."""
    submit(pool, strategies="s1", cases="c1", variants="none")
    w = FakeWorker(pool, free_mb=8000)
    w.heartbeat()
    it = w.claim()[0]
    body = _body(w, it, outcome="crashed", row={}, error="BrokenProcessPool")
    assert pool.post("/api/pool/results", headers=H, json=body).json()["retry"]
    again = pool.post("/api/pool/results", headers=H, json=body)
    assert again.status_code == 200
    st = _item(it["item_id"])
    assert st["state"] == "queued" and st["crashes"] == 1          # still waiting for its one retry
    assert _n_results() == 0


def test_a_stale_crash_post_does_not_end_another_workers_run(pool):
    submit(pool, strategies="s1", cases="c1", variants="none")
    small, large = FakeWorker(pool, name="small", free_mb=8000), FakeWorker(pool, name="large", free_mb=40000)
    small.heartbeat()
    large.heartbeat()
    it = small.claim()[0]
    body = _body(small, it, outcome="crashed", row={}, error="killed")
    assert pool.post("/api/pool/results", headers=H, json=body).json()["retry"]
    it2 = large.claim()[0]
    assert it2["item_id"] == it["item_id"]
    pool.post("/api/pool/results", headers=H, json=body)            # small's post, resent while large runs the retry
    st = _item(it["item_id"])
    assert st["state"] == "leased" and st["lease_id"] == it2["lease_id"]
    assert _n_results() == 0
    assert large.heartbeat()["renewed"] == [it2["lease_id"]]
    assert large.post(it2).json()["accepted"]


def test_a_result_must_name_its_commit_and_slot(pool):
    submit(pool, strategies="s1", cases="c1", variants="none")
    w = FakeWorker(pool)
    it = w.claim()[0]
    body = _body(w, it)
    del body["commit"]
    assert pool.post("/api/pool/results", headers=H, json=body).status_code in (400, 409)
    body = _body(w, it)
    del body["slot"]
    assert pool.post("/api/pool/results", headers=H, json=body).status_code in (400, 409)
    assert _n_results() == 0
    ok = pool.post("/api/pool/results", headers=H, json=_body(w, it)).json()
    assert ok["accepted"]
    with db.connect(readonly=True) as con:
        r = con.execute("SELECT * FROM pool_results WHERE id = ?", (ok["result_id"],)).fetchone()
    assert (r["commit_sha"], r["machine"], r["worker"], r["slot"], r["job_id"]) == (MAIN, "node2", w.name, "3", it["job_id"])


@pytest.mark.parametrize("row_over", [{"code_commit": FEATURE}, {"code_dirty": "deadbeef"}])
def test_a_run_whose_row_says_other_code_ran_is_refused(pool, row_over):
    """runner.run_item records the code it imported (provenance.loaded): another commit, or a patch on top
    of the job's, is not the job's code, whatever the hashes say."""
    submit(pool, strategies="s1", cases="c1", variants="none")
    w = FakeWorker(pool)
    it = w.claim()[0]
    body = _body(w, it)
    body["row"].update(row_over)
    r = pool.post("/api/pool/results", headers=H, json=body)
    assert r.status_code == 409
    assert _n_results() == 0
    with db.connect(readonly=True) as con:
        assert con.execute("SELECT COUNT(*) FROM results").fetchone()[0] == 0


def test_a_result_is_not_promoted_once_head_has_moved_to_other_hashes(pool, monkeypatch):
    submit(pool, strategies="s1", cases="c1", variants="none")
    w = FakeWorker(pool)
    it = w.claim()[0]
    moved = "c" * 40                                                 # s1's code changed on the main line meanwhile
    monkeypatch.setattr(gitcode, "main_head", lambda: moved)
    jobs.mainline_plan(wait=True)
    got = w.post(it).json()
    assert got["accepted"] and got["promoted_id"] is None
    assert list(store.latest("c1", "none", "s1")) == []
    with db.connect(readonly=True) as con:
        assert con.execute("SELECT promote FROM pool_results").fetchone()[0] == "not-main-line"
    assert accept.recheck_on_new_head() == 1 and accept.promote_pending() == 0   # rechecked, still not the main line's


def test_an_agent_job_past_the_cap_fails_and_the_coordinator_is_not_capped(pool, monkeypatch):
    monkeypatch.setattr(jobs, "MAX_AGENT_ITEMS", 2)              # the user, 2026-10-21: one agent's job must not block the others
    j = submit(pool, strategies="s1,s2", cases="c1")             # 4 items
    assert j["state"] == "failed" and "too big" in (j["error"] or "")
    assert submit(pool, strategies="s1,s2", cases="c1", by="coordinator")["state"] == "queued"


def test_a_raised_limit_reruns_its_timeouts_once():
    """(2026-10-23, the user) a timeout recorded under a shorter limit than the item's limit now is stale; at the same
    limit (or with no limit given) it stays current, so it is not run again and again."""
    from sdlab.ladder import store
    row = {"case_hash": "c", "strategy_hash": "s", "score_hash": "h", "status": "timeout", "error": "took longer than 300 s"}
    assert store.staleness(row, "c", "s", "h") is None
    assert store.staleness(row, "c", "s", "h", limit=300) is None
    assert store.staleness(row, "c", "s", "h", limit=1800) == "timed out under 300 s, limit now 1800 s"
    guard = {**row, "error": "stopped by the worker after 2700.4 s (its own timeout covers discovery, not scoring)"}
    assert store.timed_out_under(guard["error"]) == 900.2 and store.staleness(guard, "c", "s", "h", limit=900) is None
    assert store.staleness({**row, "status": "fail"}, "c", "s", "h", limit=1800) is None
