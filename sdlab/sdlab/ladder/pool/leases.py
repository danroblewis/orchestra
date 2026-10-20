"""Handing out work: claims (by job priority, memory admission, heavy slots), heartbeats (the worker
registry and lease renewal), released leases (a worker that stops) and expired leases. docs/pool.md, "Work".

An item is leased to one worker at a time, for LEASE_SECONDS, renewed by heartbeats; an expired lease puts
the item back in the queue, and an item whose lease is lost LOST_LIMIT times becomes an error.
"""

from __future__ import annotations

import json
import secrets
import time

from .. import store
from . import db, jobs, memory

LEASE_SECONDS = 120
LOST_LIMIT = 3
SCAN = 3000                              # waiting items looked at per claim (admission may pass many by)
MAX_SLOTS = 64


def _num(body: dict, key: str, default=None, kind=float):
    v = body.get(key, default)
    if v is None:
        return None
    try:
        return kind(v)
    except (TypeError, ValueError):
        raise jobs.Refused(400, f"{key}: a number") from None


def _name(body: dict, key: str) -> str:
    v = body.get(key)
    if not isinstance(v, str) or not v or len(v) > 100:
        raise jobs.Refused(400, f"{key}: a name")
    return v


def expire(con) -> int:
    """Leases past their expiry: their items back in the queue (or an error after LOST_LIMIT losses)."""
    now = time.time()
    rows = con.execute("SELECT id, job_id, lost FROM pool_items WHERE state = 'leased' AND lease_expires < ?", (now,)).fetchall()
    for r in rows:
        if r["lost"] + 1 >= LOST_LIMIT:
            con.execute("UPDATE pool_items SET state = 'error', lost = lost + 1, lease_id = NULL, worker = NULL, finished = ?,"
                        " error = ? WHERE id = ?", (jobs._iso(), f"its lease was lost {LOST_LIMIT} times (the worker stopped heartbeating)", r["id"]))
        else:
            con.execute("UPDATE pool_items SET state = 'queued', lost = lost + 1, lease_id = NULL, worker = NULL WHERE id = ?", (r["id"],))
    for job_id in {r["job_id"] for r in rows}:
        jobs.settle(con, job_id)
    return len(rows)


def _prev(prev_id: int | None) -> dict | None:
    if not prev_id:
        return None
    r = store.get(prev_id, found=True)
    if r is None:
        return None
    return {"found": r.get("found") or [], "seconds": r.get("seconds"), "code_commit": r.get("code_commit"), "code_dirty": r.get("code_dirty")}


def claim(body: dict) -> dict:
    """Up to `slots` items the worker can take now (docs/pool.md, POST /api/pool/claim)."""
    worker, machine = _name(body, "worker"), _name(body, "machine")
    slots = _num(body, "slots", 1, int)
    free = _num(body, "free_mb")
    if free is None:
        raise jobs.Refused(400, "free_mb: the memory the worker can still promise (MB)")
    heavy_free = _num(body, "heavy_free", 0, int) or 0
    have = [c for c in (body.get("commits") or []) if isinstance(c, str)][:50]
    slots = max(0, min(slots or 0, MAX_SLOTS))
    out = []
    with db.LOCK, db.connect() as con:
        expire(con)
        if not slots:
            return {"lease_seconds": LEASE_SECONDS, "items": []}
        peaks = memory.Peaks(con)
        prefer = f" (j.commit_sha IN ({','.join('?' * len(have))})) DESC," if have else ""
        rows = con.execute("SELECT i.*, j.commit_sha AS commit_sha, j.priority AS priority FROM pool_items i JOIN pool_jobs j ON j.id = i.job_id"
                           " WHERE i.state = 'queued' AND j.state IN ('queued', 'running')"
                           f" ORDER BY j.priority DESC,{prefer} j.id, i.rank DESC, i.id LIMIT ?", (*have, SCAN)).fetchall()
        left = free
        taken = []
        for r in rows:
            if len(taken) >= slots:
                break
            tags = json.loads(r["tags"] or "[]")
            exp = peaks.expected(r["case_id"], r["strategy"], tags)
            if r["min_free_mb"] and free < r["min_free_mb"]:
                continue                                       # a crashed item: only where there is more memory than where it crashed
            if exp + memory.MARGIN_MB > left:
                continue
            if r["heavy"] and heavy_free <= 0:
                continue
            left -= exp
            heavy_free -= int(bool(r["heavy"]))
            taken.append((r, exp))
        now = time.time()
        for r, exp in taken:
            lease = secrets.token_hex(16)
            con.execute("UPDATE pool_items SET state = 'leased', lease_id = ?, worker = ?, leased_at = ?, lease_expires = ? WHERE id = ? AND state = 'queued'",
                        (lease, worker, jobs._iso(now), now + LEASE_SECONDS, r["id"]))
            out.append({"item_id": r["id"], "lease_id": lease, "lease_expires": jobs._iso(now + LEASE_SECONDS), "job_id": r["job_id"],
                        "commit": r["commit_sha"], "case": r["case_id"], "variant": r["variant"], "strategy": r["strategy"],
                        "case_hash": r["case_hash"], "strategy_hash": r["strategy_hash"], "score_hash": r["score_hash"], "mode": r["mode"],
                        "prev_id": r["prev_id"], "timeout": r["timeout"], "heavy": bool(r["heavy"]), "expected_peak_mb": exp, "tags": tags})
        for job_id in {r["job_id"] for r, _ in taken}:
            jobs.settle(con, job_id)
        _seen(con, worker, machine, None)
    for it in out:                                             # the stored flows a re-score scores again (read outside the write)
        it["prev"] = _prev(it.pop("prev_id"))
    return {"lease_seconds": LEASE_SECONDS, "items": out}


INFO = ("slots", "busy", "cpus", "load", "mem_total_mb", "mem_free_mb", "heavy_slots", "version", "nice")


def _seen(con, worker: str, machine: str, info: dict | None) -> None:
    now = time.time()
    got = con.execute("SELECT info FROM pool_workers WHERE name = ?", (worker,)).fetchone()
    if got is None:
        con.execute("INSERT INTO pool_workers (name, machine, first_seen, last_seen, seen, info) VALUES (?, ?, ?, ?, ?, ?)",
                    (worker, machine, jobs._iso(now), jobs._iso(now), now, json.dumps(info or {})))
    else:
        con.execute("UPDATE pool_workers SET machine = ?, last_seen = ?, seen = ?, info = COALESCE(?, info) WHERE name = ?",
                    (machine, jobs._iso(now), now, json.dumps(info) if info is not None else None, worker))


def heartbeat(body: dict) -> dict:
    """Register the worker and renew its leases (docs/pool.md, POST /api/pool/heartbeat)."""
    worker, machine = _name(body, "worker"), _name(body, "machine")
    info = {}
    for k in INFO:
        if body.get(k) is not None:
            v = body[k]
            if not isinstance(v, (int, float, str)) or isinstance(v, bool):
                raise jobs.Refused(400, f"{k}: a number")
            info[k] = v
    leases = [x for x in (body.get("leases") or []) if isinstance(x, str)][:MAX_SLOTS * 4]
    renewed, lost, cancel = [], [], []
    with db.LOCK, db.connect() as con:
        expire(con)
        now = time.time()
        for lease in leases:
            r = con.execute("SELECT id, state, worker FROM pool_items WHERE lease_id = ?", (lease,)).fetchone()
            if r is None:
                lost.append(lease)
            elif r["state"] == "leased" and r["worker"] == worker:
                con.execute("UPDATE pool_items SET lease_expires = ? WHERE id = ?", (now + LEASE_SECONDS, r["id"]))
                renewed.append(lease)
            elif r["state"] == "cancelled":
                cancel.append(lease)
            else:
                lost.append(lease)
        _seen(con, worker, machine, info)
    return {"renewed": renewed, "lost": lost, "cancel": cancel, "lease_seconds": LEASE_SECONDS}


def release(body: dict) -> dict:
    """A worker gives leases back (it is stopping): their items wait again at once, without counting as a
    lost lease (docs/pool.md, POST /api/pool/release)."""
    worker = _name(body, "worker")
    leases = [x for x in (body.get("leases") or []) if isinstance(x, str)][:MAX_SLOTS * 4]
    released = []
    with db.LOCK, db.connect() as con:
        jobs_hit = set()
        for lease in leases:
            r = con.execute("SELECT id, job_id FROM pool_items WHERE lease_id = ? AND state = 'leased' AND worker = ?", (lease, worker)).fetchone()
            if r is None:
                continue
            con.execute("UPDATE pool_items SET state = 'queued', lease_id = NULL, worker = NULL, lease_expires = NULL WHERE id = ?", (r["id"],))
            released.append(lease)
            jobs_hit.add(r["job_id"])
        for job_id in jobs_hit:
            jobs.settle(con, job_id)
    return {"released": released}
