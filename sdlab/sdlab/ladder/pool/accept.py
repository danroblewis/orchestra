"""Posted results: the acceptance rules (docs/pool.md, POST /api/pool/results) and promotion to the main
line's latest.

Every accepted result is stored in pool_results, queryable by job. It becomes the main line's latest (a
row in `results`, latest = 1) only when its case, strategy and score hashes equal the main line's current
ones for the cell (the plan of the `sdlab` branch's HEAD) and the cell's latest is stale against them
(store.staleness): a feature branch's or an older commit's result whose code differs never shows on the
leaderboard, and staleness stays keyed by the hashes whoever ran the item.
"""

from __future__ import annotations

import json

from .. import store
from . import db, jobs, leases, memory

CRASH_LIMIT = 2                           # the second crash is recorded as an error
REJECT_LIMIT = 2                          # the second hash/commit mismatch makes the item an error
RETRY_FACTOR = memory.RETRY_FACTOR        # a crashed item's retry needs this much more memory than where it crashed
KEEP = ("status", "seconds", "error", "scores", "found", "code_commit", "code_dirty", "score_seconds", "wall_seconds", "wait_seconds")
HASHES = ("case_hash", "strategy_hash", "score_hash")


def post(body: dict) -> tuple[int, dict]:
    """(HTTP status, answer) for one posted item."""
    if not isinstance(body, dict):
        raise jobs.Refused(400, "a JSON object")
    worker, machine = leases._name(body, "worker"), leases._name(body, "machine")
    try:
        item_id = int(body.get("item_id"))
    except (TypeError, ValueError):
        raise jobs.Refused(400, "item_id: an integer") from None
    outcome = body.get("outcome", "result")
    if outcome not in ("result", "crashed"):
        raise jobs.Refused(400, "outcome: result or crashed")
    slot = body.get("slot")
    slot = None if slot is None else str(slot)[:40]
    peak = leases._num(body, "peak_rss_mb")
    free = leases._num(body, "free_mb")
    row = body.get("row") or {}
    if not isinstance(row, dict):
        raise jobs.Refused(400, "row: an object")
    with db.LOCK:
        with db.connect() as con:
            it = con.execute("SELECT i.*, j.commit_sha AS job_commit FROM pool_items i JOIN pool_jobs j ON j.id = i.job_id WHERE i.id = ?",
                             (item_id,)).fetchone()
            if it is None:
                return 404, {"accepted": False, "error": f"no item {item_id}"}
            done = con.execute("SELECT id FROM pool_results WHERE item_id = ?", (item_id,)).fetchone()
            if done is not None:
                return 200, {"accepted": False, "duplicate": True, "result_id": done[0]}
            if it["state"] == "cancelled":
                return 200, {"accepted": False, "cancelled": True}
            if it["state"] in ("error", "reused"):
                return 200, {"accepted": False, "duplicate": True, "state": it["state"]}
            if not isinstance(body.get("commit"), str) or slot is None:
                raise jobs.Refused(400, "commit and slot: the commit and slot that ran the item (its provenance)")
            mine = it["state"] == "leased" and it["lease_id"] == body.get("lease_id")
            if outcome == "crashed" and not mine:
                # a resent post (its answer was lost) or a lease that is no longer this worker's: the crash was
                # counted when it came under its lease, or the item has moved on; never a second crash
                return 200, {"accepted": False, "stale": True, "state": it["state"]}
            why = _mismatch(it, body, row) if outcome == "result" else (
                f"commit {str(body.get('commit'))[:12]} is not the job's {it['job_commit'][:12]}" if body.get("commit") and body.get("commit") != it["job_commit"] else None)
            if why:
                _reject(con, it, mine, why)
                return 409, {"accepted": False, "rejected": why}
            if outcome == "crashed":
                pid = _crashed(con, it, mine, body, worker, machine, slot, peak, free)
                if pid is None:
                    return 200, {"accepted": True, "retry": True}
            else:
                pid = _store(con, it, worker, machine, slot, peak, body.get("commit") or it["job_commit"], {k: row.get(k) for k in KEEP})
        promoted = promote(pid)                               # after the write above is committed (store.record has its own connection)
    return 200, {"accepted": True, "result_id": pid, "promoted_id": promoted}


def _mismatch(it, body: dict, row: dict) -> str | None:
    if body.get("commit") and body["commit"] != it["job_commit"]:
        return f"commit {str(body['commit'])[:12]} is not the job's {it['job_commit'][:12]}"
    if it["mode"] == "run":                                   # what runner.run_item imported (provenance.loaded); a re-score keeps its flows'
        if row.get("code_commit") is not None and row["code_commit"] != it["job_commit"]:
            return f"the row's code_commit {str(row['code_commit'])[:12]} is not the job's {it['job_commit'][:12]} (other code ran)"
        if row.get("code_dirty"):
            return f"the row's code_dirty {str(row['code_dirty'])[:16]}: the code that ran was not the job's commit"
    said = body.get("hashes")
    if not isinstance(said, dict):
        return "hashes: the worker's own case, strategy and score hashes are required"
    for k in HASHES:
        if said.get(k) != it[k]:
            return f"{k} {said.get(k)} is not the promised {it[k]} (the worker's checkout computed another)"
        if row.get(k) is not None and row[k] != it[k]:
            return f"the row's {k} {row[k]} is not the promised {it[k]} (the code that ran is not the job's)"
    if row.get("status") not in jobs.STATUSES:
        return f"row.status: one of {', '.join(jobs.STATUSES)}"
    for k in ("case", "variant", "strategy"):
        if row.get(k) is not None and row[k] != it[{"case": "case_id"}.get(k, k)]:
            return f"the row's {k} is not the item's"
    return None


def _reject(con, it, mine: bool, why: str) -> None:
    if not mine:
        return                                                # someone else's lease (or none): leave the item as it is
    if it["rejections"] + 1 >= REJECT_LIMIT:
        con.execute("UPDATE pool_items SET state = 'error', rejections = rejections + 1, lease_id = NULL, finished = ?, error = ? WHERE id = ?",
                    (jobs._iso(), f"rejected {REJECT_LIMIT} times: {why}"[:2000], it["id"]))
    else:
        con.execute("UPDATE pool_items SET state = 'queued', rejections = rejections + 1, lease_id = NULL, worker = NULL WHERE id = ?", (it["id"],))
    jobs.settle(con, it["job_id"])


def _crashed(con, it, mine: bool, body, worker, machine, slot, peak, free) -> int | None:
    """The first crash: the item back in the queue for more memory (None). The second: an error result (its id)."""
    err = str(body.get("error") or "the worker process died")[:1500]
    if it["crashes"] + 1 < CRASH_LIMIT:
        if mine:
            need = max(it["min_free_mb"] or 0, (free or 0) * RETRY_FACTOR, (peak or 0) * RETRY_FACTOR)
            cap = con.execute("SELECT MAX(CAST(COALESCE(json_extract(info, '$.budget_mb'), 0.85 * json_extract(info, '$.mem_total_mb')) AS REAL))"
                              " FROM pool_workers").fetchone()[0]
            if cap:
                need = min(need, 0.9 * cap)                    # never more than the biggest worker can promise (its budget)
            con.execute("UPDATE pool_items SET state = 'queued', crashes = crashes + 1, lease_id = NULL, worker = NULL, min_free_mb = ?,"
                        " error = ? WHERE id = ?", (need or None, err, it["id"]))
            jobs.settle(con, it["job_id"])
        return None
    # said without store._crashed's words, so the main line does not take it for a crash to run again: the pool has retried it
    err = err.replace("BrokenProcessPool", "broken process pool").replace("terminated abruptly", "terminated")
    row = {"status": "error", "error": f"pool: the worker process died twice ({err})", "code_commit": body.get("commit") or it["job_commit"]}
    return _store(con, it, worker, machine, slot, peak, body.get("commit") or it["job_commit"], row)


def _store(con, it, worker, machine, slot, peak, commit, row: dict) -> int:
    full = {"case": it["case_id"], "variant": it["variant"], "strategy": it["strategy"], **{k: it[k] for k in HASHES}, **row}
    cur = con.execute("INSERT INTO pool_results (item_id, job_id, case_id, variant, strategy, case_hash, strategy_hash, score_hash, commit_sha,"
                      " machine, worker, slot, status, seconds, wall_seconds, peak_rss_mb, at, row) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                      (it["id"], it["job_id"], it["case_id"], it["variant"], it["strategy"], it["case_hash"], it["strategy_hash"], it["score_hash"],
                       commit, machine, worker, slot, row["status"], row.get("seconds"), row.get("wall_seconds"), peak, jobs._iso(), json.dumps(full)))
    pid = int(cur.lastrowid)
    con.execute("UPDATE pool_items SET state = ?, result_id = ?, finished = ?, lease_id = NULL WHERE id = ?",
                ("done", pid, jobs._iso(), it["id"]))
    jobs.settle(con, it["job_id"])
    return pid


# ---- promotion ----

def _main_index(p: dict) -> dict:
    return {(cid, v["name"]): (c["hash"], v["score_hash"]) for cid, c in p["cases"].items() for v in c["variants"]}


_index: dict = {}


def main_hashes(case: str, variant: str, strategy: str) -> tuple | None | bool:
    """The main line's (case, strategy, score) hashes for a cell; None: the cell is not in its plan; False: the
    plan is not known yet (made in the background)."""
    got = jobs.mainline_plan(wait=False)
    if got is None:
        return False
    head, p = got
    if _index.get("head") != head:
        _index.update(head=head, cells=_main_index(p), strategies=p["strategies"])
    c = _index["cells"].get((case, variant))
    sh = _index["strategies"].get(strategy)
    if c is None or sh is None:
        return None
    return (c[0], sh, c[1])


def promote(pool_result_id: int) -> int | None:
    """Make a pool result the main line's latest if the rule allows (see the module doc); returns the results id."""
    with db.LOCK:
        with db.connect(readonly=True) as con:
            r = con.execute("SELECT * FROM pool_results WHERE id = ?", (pool_result_id,)).fetchone()
        if r is None or r["promote"] != "pending":
            return r["promoted_id"] if r is not None else None
        main = main_hashes(r["case_id"], r["variant"], r["strategy"])
        if main is False:
            return None                                       # pending: tried again when the plan is known
        mine = (r["case_hash"], r["strategy_hash"], r["score_hash"])
        if main is None or main != mine:
            _mark(pool_result_id, "not-main-line", None)
            return None
        latest = next(iter(store.latest(r["case_id"], r["variant"], r["strategy"])), None)
        if latest is not None and not store.staleness(latest, *main):
            _mark(pool_result_id, "current", None)            # the main line already has a current result for the cell
            return None
        row = json.loads(r["row"])
        rec = {"case": r["case_id"], "variant": r["variant"], "strategy": r["strategy"], "case_hash": r["case_hash"],
               "strategy_hash": r["strategy_hash"], "score_hash": r["score_hash"], "machine": r["machine"], "at": r["at"],
               **{k: row.get(k) for k in KEEP}}
        rid = store.record(rec)
        _mark(pool_result_id, "done", rid)
        return rid


def _mark(pool_result_id: int, state: str, rid: int | None) -> None:
    with db.connect() as con:
        con.execute("UPDATE pool_results SET promote = ?, promoted_id = ? WHERE id = ?", (state, rid, pool_result_id))


def promote_pending(limit: int = 5000) -> int:
    """Promote the results still pending (the main line's plan was not known when they came)."""
    with db.connect(readonly=True) as con:
        ids = [r[0] for r in con.execute("SELECT id FROM pool_results WHERE promote = 'pending' ORDER BY id LIMIT ?", (limit,))]
    return sum(1 for i in ids if promote(i))


def recheck_on_new_head() -> int:
    """When HEAD moves, results that were not the main line's are checked again against the new hashes."""
    with db.connect() as con:
        return con.execute("UPDATE pool_results SET promote = 'pending' WHERE promote = 'not-main-line'").rowcount
