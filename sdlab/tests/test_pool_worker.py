"""The CPU pool's worker (pool/worker.py, docs/pool.md "Workers"): its outbox, memory promise, load yielding,
hard limit and self-update decision as units; and end to end, a real worker process with two slots against
a test server (the pool's routes in a uvicorn thread, a temporary store, the real planner at the sdlab
branch's commit): it fetches the code by bundle, makes a checkout per slot, runs the items at the job's
commit, and its results are accepted with their peak RSS. Nothing here touches the real store."""

from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from sdlab.ladder.pool import gitcode, host, slot, worker
from sdlab.ladder.pool.client import Down
from sdlab.ladder.pool.outbox import Outbox

ROOT = Path(__file__).resolve().parents[1]


class FlakyClient:
    """Down until up is set; then answers like the server."""

    def __init__(self):
        self.up = False
        self.posts: list[dict] = []
        self.answer = (200, {"accepted": True, "result_id": 1})

    def call(self, method, path, body=None, timeout=60):
        if not self.up:
            raise Down("connection refused")
        self.posts.append(body)
        return self.answer


def test_the_outbox_keeps_results_until_the_server_takes_them(tmp_path):
    c = FlakyClient()
    box = Outbox(tmp_path / "outbox", c)
    f = box.put({"item_id": 7, "lease_id": "abc", "row": {"status": "pass"}})
    assert not box.send(f) and f.exists()                              # down: kept
    box.put({"item_id": 8, "lease_id": "def", "row": {}})
    assert box.flush() == 2
    c.up = True
    assert box.flush() == 0 and [p["item_id"] for p in c.posts] == [7, 8]
    c.answer = (409, {"accepted": False, "rejected": "strategy_hash differs"})
    f = box.put({"item_id": 9, "lease_id": "x", "row": {}})
    assert box.send(f) and not f.exists()                              # refused for good: kept aside with the answer
    kept = json.loads((tmp_path / "outbox" / "refused" / f.name).read_text())
    assert kept["code"] == 409 and kept["body"]["item_id"] == 9


def _bare_worker(**kw) -> worker.Worker:
    w = object.__new__(worker.Worker)
    w.slots_n, w.yield_load, w.min_slots = 14, None, 0
    w.total_mb, w.budget_mb, w.reserve_mb = 64000.0, 54000.0, 3000.0
    w.slots = []
    for k, v in kw.items():
        setattr(w, k, v)
    return w


def test_load_yielding():
    w = _bare_worker()
    assert w.effective_slots(load=100) == 14                           # no --yield-load: never yields
    w.yield_load = 24
    assert w.effective_slots(load=20) == 14
    assert w.effective_slots(load=30.5) == 7
    assert w.effective_slots(load=80) == 0
    w.min_slots = 2
    assert w.effective_slots(load=80) == 2


def test_the_memory_promise(monkeypatch):
    def fake_slot(expected, rss):
        run = SimpleNamespace(expected=expected, item={}) if expected is not None else None
        return SimpleNamespace(run=run, rss=lambda: rss, busy=run is not None)
    monkeypatch.setattr(host, "mem_available_mb", lambda: 40000.0)
    w = _bare_worker(slots=[fake_slot(10000, 2000), fake_slot(None, 300), fake_slot(1000, 1500)])
    # budget: 54000 - (10000 + 300 + 1500) = 42200; the OS: 40000 - (8000 growth) - 3000 reserve = 29000
    assert w.promise_mb() == 29000.0
    w.budget_mb = 20000.0
    assert w.promise_mb() == 20000.0 - 11800.0
    monkeypatch.setattr(host, "mem_available_mb", lambda: 5000.0)
    assert w.promise_mb() == 0.0


def test_the_hard_limit_and_the_watchdog():
    assert slot.hard_limit(1000, 64000) == 4096                        # at least 4 GB
    assert slot.hard_limit(10000, 64000) == 20000                      # twice the expected peak
    assert slot.hard_limit(40000, 64000) == 32000                      # at most half the machine
    assert slot.hard_limit(80000, 262144, 98304) == 98304              # and never past the worker's budget
    s = object.__new__(slot.Slot)
    r = slot.Running({"item_id": 1}, 1000, 4096, 30000)
    assert s._watch(r, 4000, 600) is None
    assert s._watch(r, 5000, 600) == "memory"
    r.started -= 700
    assert s._watch(r, 100, 600) == "guard"
    r.abort = "lost"
    assert s._watch(r, 100, 600) == "lost"


def test_host_probes():
    assert host.mem_total_mb() > 1000 and 0 < host.mem_available_mb() <= host.mem_total_mb()
    got = host.rss_mb([os.getpid()])
    assert got[os.getpid()] > 10


def test_self_update_follows_only_the_workers_own_code(tmp_path, monkeypatch):
    """The supervisor restarts when sdlab/ladder/pool (or the lock) differs at the new HEAD, not for other commits."""
    monkeypatch.setenv("SDLAB_POOL_HOME", str(tmp_path / "server"))
    from sdlab.ladder.pool.repo import Repo

    class BundleClient:
        def bundle(self, want, have, timeout=600):
            return gitcode.bundle(want, have)

    r = Repo(tmp_path / "w", BundleClient())
    log = subprocess.run(["git", "log", "--format=%H", "-n", "400", "sdlab", "--"], cwd=ROOT, capture_output=True, text=True).stdout.split()
    pool_at = {c: subprocess.run(["git", "rev-parse", "--verify", "--quiet", f"{c}:sdlab/sdlab/ladder/pool"], cwd=ROOT,
                                 capture_output=True, text=True).stdout.strip() for c in log[:60]}
    w = _bare_worker(repo=r)
    pairs = list(zip(log[1:], log[:-1]))[:59]                          # (older, newer) neighbours
    same = next(((a, b) for a, b in pairs if pool_at[a] == pool_at[b]), None)
    changed = next(((a, b) for a, b in pairs if pool_at[a] != pool_at[b]), None)
    assert same and changed
    for (old, new), want in ((same, False), (changed, True)):
        r.ensure(old)
        w.self_commit = old
        assert w.own_changed(new) is want
    w.self_commit = None
    assert w.own_changed(changed[1]) is False                          # not running from DIR/self: never


class ScriptedChild:
    """An item process that answers from a script (events, with None: it died) and whose RSS the sampler reads."""

    def __init__(self, events, rss=100.0):
        self.events, self.rss, self.pid, self.items, self.fresh, self.killed = list(events), rss, 4242, 0, True, False

    def send(self, msg):
        self.items += 1

    def next(self, timeout):
        if self.killed:
            return None
        if not self.events:
            time.sleep(0.01)
            return False
        ev = self.events.pop(0)
        if callable(ev):
            return ev(self)
        return ev

    def alive(self):
        return not self.killed

    def exit_how(self):
        return "killed by SIGKILL (the OOM killer, or a kill -9)"

    def kill(self):
        self.killed = True

    def stop(self):
        self.killed = True


class SlotHost:
    """What a slot needs of its worker."""

    def __init__(self, tmp):
        self.home, self.total_mb, self.budget_mb, self.name, self.machine = tmp, 64000.0, 54400.0, "w", "m"
        self.posts, self.released = [], []
        self.child = None
        self.sampler = SimpleNamespace(get=lambda pid: (self.child.rss, self.child.rss), reset_high=lambda pid: None,
                                       forget=lambda pid: None, watch=lambda pid: None)
        self.repo = SimpleNamespace(head=lambda p: None)

    def deliver(self, body):
        self.posts.append(body)

    def release(self, leases):
        self.released += leases


ITEM = {"item_id": 5, "lease_id": "L5", "commit": "c" * 40, "job_id": 1, "case": "001", "variant": "none", "strategy": "matrix",
        "case_hash": "ch", "strategy_hash": "sh", "score_hash": "sc", "mode": "run", "timeout": 300, "expected_peak_mb": 1000}
H3 = {"case_hash": "ch", "strategy_hash": "sh", "score_hash": "sc"}


def _run_slot(tmp_path, monkeypatch, events, rss=100.0, abort=None):
    w = SlotHost(tmp_path)
    w.child = ScriptedChild(events, rss)
    def prepare(self, commit):
        self.child = w.child
        return w.child
    monkeypatch.setattr(slot.Slot, "_prepare", prepare)
    s = slot.Slot(1, w)
    s.give(dict(ITEM), 30000.0)
    if abort:
        time.sleep(0.05)
        s.abort(abort)
    for _ in range(400):
        if not s.busy:
            break
        time.sleep(0.01)
    s.close()
    assert not s.busy
    return w


def test_a_slot_posts_a_result_with_its_hashes_and_peak(tmp_path, monkeypatch):
    w = _run_slot(tmp_path, monkeypatch, [{"event": "start", "hashes": H3, "match": True},
                                          {"event": "done", "hashes": H3, "row": {"status": "pass"}, "hwm_mb": 812.5, "rss_mb": 300}])
    (b,) = w.posts
    assert b["outcome"] == "result" and b["hashes"] == H3 and b["peak_rss_mb"] == 812.5 and b["free_mb"] == 30000.0
    assert b["slot"] == 1 and b["lease_id"] == "L5" and b["commit"] == ITEM["commit"]


def test_a_slot_kills_an_item_over_its_hard_limit(tmp_path, monkeypatch):
    def grow(child):
        child.rss = 5000.0                                             # past the 4096 MB limit of a 1000 MB item
        return False
    w = _run_slot(tmp_path, monkeypatch, [{"event": "start", "hashes": H3, "match": True}, grow])
    (b,) = w.posts
    assert b["outcome"] == "crashed" and "hard limit 4096 MB" in b["error"] and b["peak_rss_mb"] == 5000.0
    assert w.child.killed


def test_a_dead_item_process_is_posted_as_crashed(tmp_path, monkeypatch):
    w = _run_slot(tmp_path, monkeypatch, [{"event": "start", "hashes": H3, "match": True}, None])
    (b,) = w.posts
    assert b["outcome"] == "crashed" and "SIGKILL" in b["error"]


def test_a_lost_lease_is_stopped_and_not_posted_and_shutdown_releases(tmp_path, monkeypatch):
    w = _run_slot(tmp_path, monkeypatch, [{"event": "start", "hashes": H3, "match": True}], abort="lost")
    assert w.posts == [] and w.released == [] and w.child.killed
    w = _run_slot(tmp_path, monkeypatch, [{"event": "start", "hashes": H3, "match": True}], abort="shutdown")
    assert w.posts == [] and w.released == ["L5"]


def test_an_item_that_cannot_be_planned_is_posted_without_hashes(tmp_path, monkeypatch):
    w = _run_slot(tmp_path, monkeypatch, [{"event": "error", "error": "RuntimeError: strategy matrix is not available"}])
    (b,) = w.posts
    assert b["hashes"] == {} and b["row"]["status"] == "error"         # the server rejects it (409) and says why


# ---- end to end ----

def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def server(tmp_path, monkeypatch):
    """The pool's routes served over HTTP in this process, on a temporary store and pool home."""
    import uvicorn
    from fastapi import FastAPI

    from sdlab.ladder.pool import accept, db, jobs
    from sdlab.ladder.pool.routes import router
    monkeypatch.setenv("SDLAB_LADDER_CACHE", str(tmp_path / "server-cache"))
    monkeypatch.setenv("SDLAB_POOL_HOME", str(tmp_path / "server-pool"))
    tok = tmp_path / "pool.token"
    tok.write_text("e2e-token\n")
    tok.chmod(0o600)
    monkeypatch.setenv("SDLAB_POOL_TOKEN_FILE", str(tok))
    monkeypatch.setattr(jobs, "BACKGROUND", False)                    # planned by the test; the main line is never planned
    accept._index.clear()
    db.reset_cache()
    app = FastAPI()
    app.include_router(router)
    port = _free_port()
    srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    t = threading.Thread(target=srv.run, daemon=True)
    t.start()
    for _ in range(100):
        if srv.started:
            break
        time.sleep(0.05)
    yield SimpleNamespace(url=f"http://127.0.0.1:{port}", token=tok, tmp=tmp_path, jobs=jobs)
    srv.should_exit = True
    t.join(10)


def _api(url, method, path, body=None):
    from sdlab.ladder.pool.client import Client
    return Client(url, "e2e-token").call(method, path, body)


@pytest.mark.skipif(not os.environ.get("SDLAB_POOL_E2E"), reason="a real worker (checkouts, venvs, a planner run): SDLAB_POOL_E2E=1")
def test_a_real_worker_runs_a_job_end_to_end(server):
    code, got = _api(server.url, "POST", "/api/pool/jobs", {"ref": "sdlab", "strategies": "matrix", "cases": "001,002",
                                                            "variants": "none", "check_tree": "none", "by": "e2e"})
    assert code == 202, got
    job = got["job"]["id"]
    server.jobs.plan_pending()                                         # the real planner, at the sdlab branch's commit
    code, got = _api(server.url, "GET", f"/api/pool/jobs/{job}")
    total = got["job"]["total"]
    assert got["job"]["state"] == "queued" and 2 <= total <= 8, got
    home = server.tmp / "worker"
    env = {k: v for k, v in os.environ.items() if k not in ("VIRTUAL_ENV",)}
    env.update(SDLAB_POOL_TOKEN_FILE=str(server.token))
    logf = open(server.tmp / "worker.log", "wb")
    proc = subprocess.Popen([sys.executable, "-m", "sdlab.ladder", "worker", "--server", server.url, "--slots", "2", "--home", str(home),
                             "--cache", str(server.tmp / "shared"), "--heartbeat", "2", "--poll", "0.5",
                             "--machine", "testbox", "--name", "test-worker", "--nice", "0"],
                            cwd=ROOT, env=env, stdout=logf, stderr=subprocess.STDOUT)
    try:
        deadline = time.time() + 900
        while time.time() < deadline:
            _, got = _api(server.url, "GET", f"/api/pool/jobs/{job}")
            if got["job"]["state"] == "done":
                break
            assert proc.poll() is None, (server.tmp / "worker.log").read_text()[-3000:]
            time.sleep(2)
        assert got["job"]["state"] == "done", (server.tmp / "worker.log").read_text()[-3000:]
        assert got["job"]["counts"]["done"] == total and got["job"]["counts"]["error"] == 0, got
        _, res = _api(server.url, "GET", f"/api/pool/jobs/{job}/results?full=1")
        rows = res["results"]
        assert {r["machine"] for r in rows} == {"testbox"} and all(r["peak_rss_mb"] and r["peak_rss_mb"] > 20 for r in rows), rows
        assert all(r["status"] in ("pass", "equivalent", "fail") for r in rows), rows
        commit = gitcode.resolve("sdlab")
        assert {r["commit"] for r in rows} == {commit}
        for n in (1, 2):                                                # every slot that ran has its own checkout at the commit
            co = home / f"slot-{n}"
            if co.exists():
                head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=co, capture_output=True, text=True).stdout.strip()
                assert head == commit
        _, st = _api(server.url, "GET", "/api/pool/workers")
        assert any(w["name"] == "test-worker" and w["live"] for w in st["workers"])
        assert not list((home / "outbox").glob("*.json"))              # everything sent
        said = (server.tmp / "worker.log").read_text()
        commit_has_worker = subprocess.run(["git", "cat-file", "-e", f"{commit}:sdlab/sdlab/ladder/pool/worker.py"], cwd=ROOT).returncode == 0
        if commit_has_worker:                                           # it moved to DIR/self at the main line's HEAD first
            assert f"restarting from {home / 'self'} at {commit[:12]}" in said, said[-2000:]
            assert subprocess.run(["git", "rev-parse", "HEAD"], cwd=home / "self", capture_output=True, text=True).stdout.strip() == commit
        else:
            assert "has no worker yet: running from this checkout" in said
    finally:
        proc.send_signal(signal.SIGTERM)                               # idle: it stops at once
        try:
            assert proc.wait(60) == 0
        finally:
            if proc.poll() is None:
                proc.kill()
            logf.close()
    left = subprocess.run(["pgrep", "-f", str(home)], capture_output=True, text=True).stdout.split()
    assert not left, f"item processes left running: {left}"
