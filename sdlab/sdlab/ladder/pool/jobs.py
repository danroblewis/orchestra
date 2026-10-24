"""Jobs: submitting one (refused when the checkout has uncommitted changes in the code it uses), planning
its items at its commit (planner.py), cancelling it, the standing main-line job, and what a job's
status says. docs/pool.md, "Jobs".

The standing main-line job (kind mainline, priority 0) is what the watcher does: it holds the cells of
the main line's plan (the `sdlab` branch's HEAD) whose latest result is stale (store.staleness). Each time
it is refreshed with new stale cells it is a new job row (a generation, "main line @ <commit>"); the
previous generation's waiting items are dropped, its leased ones finish.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .. import store
from . import confirm, db, gitcode, planner

AGENT_PRIORITY = 100
MAX_PRIORITY = 1000
MAX_AGENT_ITEMS = 1500                     # an agent job may run at most this many items (the user, 2026-10-21)
UNCAPPED = {"coordinator", "ui"}           # the coordinator's and the UI's jobs are not capped
MAINLINE_SPEC = {"strategies": "everything", "cases": "*"}
MAINLINE_REPLAN = 600                     # seconds: how often an idle main line is planned again at the same HEAD
LIVE = 90                                 # seconds since a worker's last heartbeat for it to count as live
CHECK_TREE = ("all", "strategies", "none")
STATUSES = ("pass", "equivalent", "fits", "fail", "error", "timeout", "agrees", "differs")   # agrees / differs: a real-data case (real/score.py); without them 5,643 real results were refused (2026-10-23)
REUSABLE = ("pass", "equivalent", "fits", "fail")
PAUSED = Path.home() / ".sdlab" / "watch.paused"   # the watcher's pause file: while it exists the main line queues nothing
BACKGROUND = True                         # plan in a thread (tests plan with plan_pending())


class Refused(Exception):
    def __init__(self, code: int, message: str, detail: dict | None = None):
        super().__init__(message)
        self.code, self.detail = code, {"error": message, **(detail or {})}


def _iso(t: float | None = None) -> str:
    return (datetime.fromtimestamp(t, timezone.utc) if t else datetime.now(timezone.utc)).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _spec_names(spec: str | None) -> list[str] | None:
    """The strategies a spec names (None: a selection, all, everything, roster:...)."""
    if not spec or spec in ("all", "everything") or spec.startswith("roster:"):
        return None
    return [n.strip() for n in spec.split(",") if n.strip()]


def _text(body: dict, key: str, limit: int = 2000) -> str | None:
    v = body.get(key)
    if v is None or v == "":
        return None
    if not isinstance(v, str) or len(v) > limit:
        raise Refused(400, f"{key}: a string of at most {limit} characters")
    return v


# ---- submitting ----

def submit(body: dict) -> dict:
    """A new agent job (state planning), or Refused."""
    if not isinstance(body, dict):
        raise Refused(400, "a JSON object")
    ref = _text(body, "ref", 200) or gitcode.branch()
    spec = {"strategies": _text(body, "strategies") or "all", "cases": _text(body, "cases"),
            "exclude_cases": _text(body, "exclude_cases"), "variants": _text(body, "variants")}
    if spec["cases"] == "*":
        raise Refused(400, "cases: '*' is the main line's own spec")
    try:
        priority = int(body.get("priority", AGENT_PRIORITY))
        timeout = float(body.get("timeout") or 7200)   # the default: very high (the user, 2026-10-24); the cap is 7200
    except (TypeError, ValueError):
        raise Refused(400, "priority: an integer; timeout: seconds") from None
    if not 1 <= priority <= MAX_PRIORITY:
        raise Refused(400, f"priority: 1..{MAX_PRIORITY} (0 is the main line's)")
    if not 1 <= timeout <= 7200:
        raise Refused(400, "timeout: 1..7200 seconds")
    spec["timeout"] = timeout
    spec["fresh"] = bool(body.get("fresh"))
    spec["every_variant"] = bool(body.get("every_variant"))     # keep none-long where none-short has not passed (confirm.py)
    check = body.get("check_tree", "all")
    if check not in CHECK_TREE:
        raise Refused(400, f"check_tree: one of {', '.join(CHECK_TREE)}")
    spec["check_tree"] = check
    commit = gitcode.resolve(ref)
    if commit is None:
        raise Refused(404, f"no commit {ref!r} in the repository")
    if check != "none" and commit == gitcode.checkout_head():
        bad = gitcode.dirty(_spec_names(spec["strategies"]), harness=check == "all")
        if bad:
            raise Refused(409, "the checkout has uncommitted changes in the code this job uses: commit them first"
                          " (a job runs its commit, not the working tree)", {"files": bad[:200]})
    with db.LOCK, db.connect() as con:
        cur = con.execute("INSERT INTO pool_jobs (kind, by, note, priority, ref, commit_sha, spec, state, created)"
                          " VALUES ('agent', ?, ?, ?, ?, ?, ?, 'planning', ?)",
                          (_text(body, "by", 200), _text(body, "note"), priority, ref, commit, json.dumps(spec), _iso()))
        job_id = int(cur.lastrowid)
    kick()
    return job(job_id)


_thread = None


def kick() -> None:
    """Plan the jobs waiting for it, in the background."""
    global _thread
    if not BACKGROUND:
        return
    import threading
    if _thread is not None and _thread.is_alive():
        return
    _thread = threading.Thread(target=plan_pending, daemon=True, name="pool-planner")
    _thread.start()


def plan_pending() -> int:
    """Plan every job in state planning (oldest first); returns how many were planned."""
    n = 0
    while True:
        with db.connect(readonly=True) as con:
            r = con.execute("SELECT id FROM pool_jobs WHERE state = 'planning' ORDER BY id LIMIT 1").fetchone()
        if r is None:
            return n
        expand(r[0])
        n += 1


def _stored(strategies: list[str]) -> dict:
    """{(case, variant, strategy): [(source, id, case_hash, strategy_hash, score_hash, status)]}: stored results
    of these strategies, newest first: results first, then pool_results."""
    out: dict = {}
    with db.connect(readonly=True) as con:
        for i in range(0, len(strategies), 400):
            chunk = strategies[i:i + 400]
            marks = ",".join("?" * len(chunk))
            for r in con.execute(f"SELECT id, case_id, variant, strategy, case_hash, strategy_hash, score_hash, status, found IS NOT NULL"
                                 f" FROM results WHERE strategy IN ({marks}) ORDER BY id DESC", chunk):
                out.setdefault((r[1], r[2], r[3]), []).append(("results", r[0], r[4], r[5], r[6], r[7], bool(r[8])))
            for r in con.execute(f"SELECT id, case_id, variant, strategy, case_hash, strategy_hash, score_hash, status"
                                 f" FROM pool_results WHERE strategy IN ({marks}) ORDER BY id DESC", chunk):
                out.setdefault((r[1], r[2], r[3]), []).append(("pool", r[0], r[4], r[5], r[6], r[7], False))
    return out


def _rank(c: dict, v: dict) -> float:
    """Slow first (runner.execute's order): realistic and heavy cases, then long variants."""
    tags = set(c.get("tags") or [])
    return (1e9 if "heavy" in tags else 0) + (1e7 if "realistic" in tags else 0) + float(v.get("steps") or 0)


def expand(job_id: int) -> None:
    """Plan an agent job: its items at its commit, reusing stored results with exactly their hashes."""
    with db.connect(readonly=True) as con:
        j = con.execute("SELECT * FROM pool_jobs WHERE id = ?", (job_id,)).fetchone()
    if j is None or j["state"] != "planning":
        return
    spec = json.loads(j["spec"])
    try:
        p = planner.plan(j["commit_sha"], spec)
    except Exception as e:                                       # noqa: BLE001  (said on the job)
        with db.LOCK, db.connect() as con:
            con.execute("UPDATE pool_jobs SET state = 'failed', error = ?, finished = ? WHERE id = ?", (str(e)[:2000], _iso(), job_id))
        return
    variants = [v.strip() for v in (spec.get("variants") or "").split(",") if v.strip()] or None
    stored = _stored(list(p["strategies"]))
    rows, by_key, links = [], {}, []
    for cid, v, s, sh, c in planner.cells(p, variants):
        ch, sc = c["hash"], v["score_hash"]
        mode, prev, reused, reused_pool, status = "run", None, None, None, None
        for src, rid, rch, rsh, rsc, st, has_found in ([] if spec.get("fresh") else stored.get((cid, v["name"], s), [])):
            if (rch, rsh, rsc) == (ch, sh, sc) and st in REUSABLE:
                reused, reused_pool, status = (rid, None, st) if src == "results" else (None, rid, st)
                break
        if reused is None and reused_pool is None and not spec.get("fresh"):
            for src, rid, rch, rsh, rsc, st, has_found in stored.get((cid, v["name"], s), []):
                if src == "results" and (rch, rsh) == (ch, sh) and st in REUSABLE and has_found:
                    mode, prev = "rescore", rid
                    break
        state = "reused" if (reused or reused_pool) else "queued"
        row = [job_id, cid, v["name"], s, ch, sh, sc, mode, prev, state, _rank(c, v), int("heavy" in (c.get("tags") or [])),
               c.get("timeout"), json.dumps(c.get("tags") or []), reused, reused_pool, _iso() if state == "reused" else None, None]
        rows.append(row)
        by_key[(cid, v["name"], s)] = (row, status, c, v, sh)
    work = sum(1 for r in rows if r[9] == "queued")
    if j["kind"] == "agent" and work > MAX_AGENT_ITEMS and (j["by"] or "") not in UNCAPPED:
        msg = (f"too big: {work} items to run (agents' jobs are capped at {MAX_AGENT_ITEMS}, the user, 2026-10-21: one agent's"
               " job must not block the others); submit a sample, split it, or ask the coordinator")
        with db.LOCK, db.connect() as con:
            con.execute("UPDATE pool_jobs SET state = 'failed', error = ?, total = 0, finished = ? WHERE id = ?", (msg, _iso(), job_id))
        return
    for (cid, vname, s), (row, _st, c, v, sh) in by_key.items():   # none-long confirms a none-short pass (confirm.py)
        short = confirm.confirm_of(c, v)
        if short is None or row[9] != "queued" or confirm.exempt(spec, vname):
            continue
        mine = by_key.get((cid, short["name"], s))
        if mine is not None and mine[0][9] == "queued":
            row[9] = confirm.HELD
            links.append(((cid, vname, s), (cid, short["name"], s)))
            continue
        st = mine[1] if mine is not None else confirm.stored_status(stored.get((cid, short["name"], s), []), (c["hash"], sh, short["score_hash"]))
        if st != "pass":
            row[9], row[16], row[17] = confirm.SKIPPED, _iso(), confirm.why_skipped(short["name"], st)
    with db.LOCK, db.connect() as con:
        con.executemany("INSERT OR IGNORE INTO pool_items (job_id, case_id, variant, strategy, case_hash, strategy_hash, score_hash, mode, prev_id,"
                        " state, rank, heavy, timeout, tags, reused_id, reused_pool_id, finished, error) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
        confirm.link(con, job_id, links)
        skipped = {k: v for k, v in (p.get("skipped") or {}).items()}
        err = ("skipped strategies: " + "; ".join(f"{k}: {v}" for k, v in skipped.items()))[:2000] if skipped else None
        con.execute("UPDATE pool_jobs SET state = 'queued', total = ?, planned_at = ?, error = ? WHERE id = ?", (len(rows), _iso(), err, job_id))
        settle(con, job_id)


def settle(con, job_id: int) -> None:
    """A job's state from its items: done once nothing waits, runs or is held. Held none-long items whose
    none-short has finished (in this job or another) are decided first (confirm.release)."""
    for other in confirm.release(con, _iso()) - {job_id}:
        _settle(con, other)
    _settle(con, job_id)


def _settle(con, job_id: int) -> None:
    j = con.execute("SELECT state, started FROM pool_jobs WHERE id = ?", (job_id,)).fetchone()
    if j is None or j["state"] in ("planning", "cancelled", "failed", "done"):
        return
    n = dict(con.execute("SELECT state, COUNT(*) FROM pool_items WHERE job_id = ? GROUP BY state", (job_id,)).fetchall())
    if not n.get("queued") and not n.get("leased") and not n.get(confirm.HELD):
        con.execute("UPDATE pool_jobs SET state = 'done', finished = ? WHERE id = ?", (_iso(), job_id))
    elif n.get("leased") or n.get("done") or n.get("error"):
        con.execute("UPDATE pool_jobs SET state = 'running', started = COALESCE(started, ?) WHERE id = ?", (_iso(), job_id))


def cancel(job_id: int) -> dict:
    with db.LOCK, db.connect() as con:
        j = con.execute("SELECT kind, state FROM pool_jobs WHERE id = ?", (job_id,)).fetchone()
        if j is None:
            raise Refused(404, f"no job {job_id}")
        if j["kind"] == "mainline":
            raise Refused(409, "the standing main-line job cannot be cancelled")
        if j["state"] in ("done", "cancelled", "failed"):
            return job(job_id)
        con.execute("UPDATE pool_items SET state = 'cancelled', finished = ? WHERE job_id = ? AND state IN ('queued', 'leased', 'held')", (_iso(), job_id))
        con.execute("UPDATE pool_jobs SET state = 'cancelled', finished = ? WHERE id = ?", (_iso(), job_id))
    return job(job_id)


# ---- the main line ----

def live_workers(con) -> int:
    return con.execute("SELECT COUNT(*) FROM pool_workers WHERE seen > ?", (time.time() - LIVE,)).fetchone()[0]


def mainline_plan(wait: bool = False) -> tuple[str, dict] | None:
    """(HEAD of the main line, its plan) when the plan is known (cached), else None (planned in the
    background unless wait)."""
    head = gitcode.main_head()
    if head is None:
        return None
    f = gitcode.home() / "plans" / (planner._key(head, MAINLINE_SPEC) + ".json")
    if wait or f.exists():
        return head, planner.plan(head, MAINLINE_SPEC)
    if BACKGROUND and head not in _planning:
        import threading
        _planning.add(head)

        def make():
            try:
                planner.plan(head, MAINLINE_SPEC)
            finally:
                _planning.discard(head)
        threading.Thread(target=make, daemon=True, name="pool-mainline-plan").start()
    return None


_planning: set = set()


def standing(p: dict, cid: str, strategy: str) -> bool:
    """Is a cell of the main line's plan one the standing job keeps current? Every active strategy (not
    parked, not retired); every case but tag:kubernetes, plus tag:heavy (what the watchers run today)."""
    if strategy in p.get("parked", ()) or strategy in p.get("retired", ()):
        return False
    tags = set(p["cases"][cid].get("tags") or [])
    return "kubernetes" not in tags or "heavy" in tags


def _latest_rows(con) -> dict:
    out = {}
    for r in con.execute("SELECT case_id, variant, strategy, case_hash, strategy_hash, score_hash, status, error, id FROM results WHERE latest = 1"):
        out[(r[0], r[1], r[2])] = {"case_hash": r[3], "strategy_hash": r[4], "score_hash": r[5], "status": r[6], "error": r[7], "id": r[8]}
    return out


def refresh_mainline(force: bool = False) -> dict:
    """Queue the main line's stale cells as a new generation when there are new ones (only while a worker
    is live, unless force; never while PAUSED exists). Returns what it did."""
    if PAUSED.exists():
        return {"skipped": f"paused ({PAUSED} exists)"}
    with db.connect(readonly=True) as con:
        if not force and not live_workers(con):
            return {"skipped": "no live worker"}
        cur = con.execute("SELECT * FROM pool_jobs WHERE kind = 'mainline' AND state IN ('queued', 'running') ORDER BY id DESC LIMIT 1").fetchone()
        waiting = con.execute("SELECT COUNT(*) FROM pool_items WHERE job_id = ? AND state IN ('queued', 'held')", (cur["id"],)).fetchone()[0] if cur else 0
    head = gitcode.main_head()
    if head is None:
        return {"skipped": "no main-line branch"}
    if cur is not None and cur["commit_sha"] == head:
        if waiting:
            return {"skipped": "the main line's job still has waiting items", "job": cur["id"]}
        planned = datetime.fromisoformat((cur["planned_at"] or cur["created"]).replace("Z", "+00:00"))
        if not force and datetime.now(timezone.utc) - planned < timedelta(seconds=MAINLINE_REPLAN):
            return {"skipped": "planned recently", "job": cur["id"]}
    got = mainline_plan(wait=True)                                # called from the pool's service thread: it may wait
    if got is None or got[0] != head:
        return {"skipped": "the main line's plan is being made"}
    p = got[1]
    with db.connect(readonly=True) as con:
        latest = _latest_rows(con)
        busy = {(r[0], r[1], r[2]): r[3] for r in con.execute("SELECT i.case_id, i.variant, i.strategy, i.id FROM pool_items i JOIN pool_jobs j"
                                                               " ON j.id = i.job_id WHERE j.kind = 'mainline' AND i.state = 'leased'")}  # running now: not twice
    rows, by_key, links = [], {}, []
    for cid, v, s, sh, c in planner.cells(p):
        if not standing(p, cid, s) or (cid, v["name"], s) in busy:
            continue
        row = latest.get((cid, v["name"], s))
        why = store.staleness(row, c["hash"], sh, v["score_hash"], limit=c.get("timeout"))   # a raised limit re-runs its timeouts
        if not why:
            continue
        mode = "rescore" if why == "score_only" else "run"
        rows.append([cid, v["name"], s, c["hash"], sh, v["score_hash"], mode, row["id"] if mode == "rescore" else None,
                     _rank(c, v), int("heavy" in (c.get("tags") or [])), c.get("timeout"), json.dumps(c.get("tags") or []), "queued", None, None])
        by_key[(cid, v["name"], s)] = (rows[-1], c, v, sh)
    for (cid, vname, s), (row, c, v, sh) in by_key.items():      # none-long confirms a none-short pass (confirm.py)
        short = confirm.confirm_of(c, v)
        if short is None:
            continue
        key = (cid, short["name"], s)
        if key in by_key or key in busy:
            row[12] = confirm.HELD                                 # its none-short is queued with it, or running in an earlier generation
            links.append(((cid, vname, s), busy.get(key, key)))
            continue
        sr = latest.get(key)                                       # current (else it would be queued above)
        if (sr or {}).get("status") != "pass":
            row[12], row[13], row[14] = confirm.SKIPPED, _iso(), confirm.why_skipped(short["name"], (sr or {}).get("status"))
    with db.LOCK, db.connect() as con:
        if cur is not None:
            con.execute("UPDATE pool_items SET state = 'cancelled', finished = ? WHERE job_id = ? AND state IN ('queued', 'held')", (_iso(), cur["id"]))
            con.execute("UPDATE pool_jobs SET state = 'done', finished = ?, note = COALESCE(note, '') || ' (superseded)' WHERE id = ?"
                        " AND NOT EXISTS (SELECT 1 FROM pool_items WHERE job_id = ? AND state = 'leased')", (_iso(), cur["id"], cur["id"]))
        if not any(r[12] != confirm.SKIPPED for r in rows):        # nothing to run (skipped none-long cells alone make no job)
            return {"queued": 0, "head": head, **({"skipped_long": len(rows)} if rows else {})}
        cur2 = con.execute("INSERT INTO pool_jobs (kind, by, note, priority, ref, commit_sha, spec, state, created, planned_at, total)"
                           " VALUES ('mainline', 'pool', ?, 0, ?, ?, ?, 'queued', ?, ?, ?)",
                           (f"main line @ {head[:10]}", gitcode.branch(), head, json.dumps(MAINLINE_SPEC), _iso(), _iso(), len(rows)))
        job_id = int(cur2.lastrowid)
        con.executemany("INSERT OR IGNORE INTO pool_items (job_id, case_id, variant, strategy, case_hash, strategy_hash, score_hash, mode, prev_id,"
                        " rank, heavy, timeout, tags, state, finished, error) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", [[job_id, *r] for r in rows])
        confirm.link(con, job_id, links)
        settle(con, job_id)                                         # a held item whose running none-short has just finished
    n = {k: sum(r[12] == k for r in rows) for k in ("queued", confirm.HELD, confirm.SKIPPED)}
    return {"queued": n["queued"], "held": n[confirm.HELD], "skipped_long": n[confirm.SKIPPED], "job": job_id, "head": head}


# ---- status ----

def _counts(con, job_id: int) -> dict:
    n = {k: 0 for k in ("queued", "leased", "done", "reused", "error", "cancelled", confirm.HELD, confirm.SKIPPED)}
    n.update(dict(con.execute("SELECT state, COUNT(*) FROM pool_items WHERE job_id = ? GROUP BY state", (job_id,)).fetchall()))
    return n


def _info(con, j) -> dict:
    counts = _counts(con, j["id"])
    statuses = dict(con.execute("SELECT status, COUNT(*) FROM pool_results WHERE job_id = ? GROUP BY status", (j["id"],)).fetchall())
    since = _iso(time.time() - 1800)
    recent = con.execute("SELECT COUNT(*) FROM pool_results WHERE job_id = ? AND at > ?", (j["id"], since)).fetchone()[0]
    per_hour = recent * 2.0
    left = counts["queued"] + counts["leased"] + counts[confirm.HELD]
    return {"id": j["id"], "kind": j["kind"], "by": j["by"], "note": j["note"], "priority": j["priority"], "ref": j["ref"],
            "commit": j["commit_sha"], "spec": json.loads(j["spec"] or "{}"), "state": j["state"], "created": j["created"],
            "started": j["started"], "finished": j["finished"], "error": j["error"], "total": j["total"], "counts": counts,
            "statuses": statuses, "per_hour": per_hour, "eta_seconds": round(left / per_hour * 3600) if per_hour and left else None}


def job(job_id: int) -> dict:
    with db.connect(readonly=True) as con:
        j = con.execute("SELECT * FROM pool_jobs WHERE id = ?", (job_id,)).fetchone()
        if j is None:
            raise Refused(404, f"no job {job_id}")
        return _info(con, j)


def jobs(limit: int = 50, active: bool = False) -> list[dict]:
    with db.connect(readonly=True) as con:
        q = "SELECT * FROM pool_jobs" + (" WHERE state IN ('planning', 'queued', 'running')" if active else "") + " ORDER BY id DESC LIMIT ?"
        return [_info(con, j) for j in con.execute(q, (int(limit),)).fetchall()]


def results(job_id: int, full: bool = False) -> list[dict]:
    """A job's results, one per item that has one (reused items point at the stored result)."""
    out = []
    with db.connect(readonly=True) as con:
        if con.execute("SELECT 1 FROM pool_jobs WHERE id = ?", (job_id,)).fetchone() is None:
            raise Refused(404, f"no job {job_id}")
        for r in con.execute("SELECT * FROM pool_results WHERE job_id = ? ORDER BY id", (job_id,)):
            row = json.loads(r["row"])
            x = {"item_id": r["item_id"], "case": r["case_id"], "variant": r["variant"], "strategy": r["strategy"], "status": r["status"],
                 "seconds": r["seconds"], "wall_seconds": r["wall_seconds"], "peak_rss_mb": r["peak_rss_mb"], "machine": r["machine"],
                 "worker": r["worker"], "slot": r["slot"], "commit": r["commit_sha"], "promoted_id": r["promoted_id"], "promote": r["promote"],
                 "at": r["at"], "pool_result_id": r["id"]}
            if full:
                x.update(scores=row.get("scores"), found=row.get("found"), error=row.get("error"))
            out.append(x)
        for r in con.execute("SELECT * FROM pool_items WHERE job_id = ? AND state IN ('reused', 'error') AND result_id IS NULL ORDER BY id", (job_id,)):
            x = {"item_id": r["id"], "case": r["case_id"], "variant": r["variant"], "strategy": r["strategy"], "state": r["state"]}
            if r["state"] == "reused":
                src = store.get(r["reused_id"], found=full) if r["reused_id"] else None
                if src is None and r["reused_pool_id"]:
                    pr = con.execute("SELECT row, status FROM pool_results WHERE id = ?", (r["reused_pool_id"],)).fetchone()
                    src = {**json.loads(pr["row"]), "status": pr["status"]} if pr else None
                x.update(result_id=r["reused_id"], pool_result_id=r["reused_pool_id"], status=(src or {}).get("status"))
                if full and src:
                    x.update(scores=src.get("scores"), found=src.get("found"), error=src.get("error"))
            else:
                x.update(status=None, error=r["error"])
            out.append(x)
    return out
