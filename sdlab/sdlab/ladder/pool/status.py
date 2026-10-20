"""What the pool page shows (GET /api/pool/status): the workers, the queue by job, the main line and
throughput. Nothing secret: no token, no addresses."""

from __future__ import annotations

import json
import time

from . import db, gitcode, jobs


def status() -> dict:
    now = time.time()
    since = jobs._iso(now - 3600)
    with db.connect(readonly=True) as con:
        busy = dict(con.execute("SELECT worker, COUNT(*) FROM pool_items WHERE state = 'leased' GROUP BY worker").fetchall())
        heavy = dict(con.execute("SELECT worker, COUNT(*) FROM pool_items WHERE state = 'leased' AND heavy = 1 GROUP BY worker").fetchall())
        workers = []
        for r in con.execute("SELECT * FROM pool_workers ORDER BY machine, name"):
            info = json.loads(r["info"] or "{}")
            workers.append({"name": r["name"], "machine": r["machine"], "live": now - r["seen"] < jobs.LIVE, "last_seen": r["last_seen"],
                            "ago": round(now - r["seen"]), "leased": busy.get(r["name"], 0), "heavy_leased": heavy.get(r["name"], 0),
                            **{k: info.get(k) for k in ("slots", "busy", "cpus", "load", "mem_total_mb", "mem_free_mb", "heavy_slots", "nice")}})
        per_machine = [{"machine": m, "results": n, "busy_seconds": round(b or 0)} for m, n, b in con.execute(
            "SELECT machine, COUNT(*), SUM(wall_seconds) FROM pool_results WHERE at > ? GROUP BY machine ORDER BY machine", (since,))]
        buckets = [{"at": r[0], "results": r[1]} for r in con.execute(
            "SELECT substr(at, 1, 15) || '0' AS b, COUNT(*) FROM pool_results WHERE at > ? GROUP BY b ORDER BY b", (jobs._iso(now - 6 * 3600),))]
        totals = dict(con.execute("SELECT i.state, COUNT(*) FROM pool_items i JOIN pool_jobs j ON j.id = i.job_id"
                                  " WHERE j.state IN ('planning', 'queued', 'running') GROUP BY i.state").fetchall())
        stored = con.execute("SELECT COUNT(*), SUM(promote = 'done') FROM pool_results").fetchone()
    active = jobs.jobs(limit=200, active=True)
    recent = [j for j in jobs.jobs(limit=20) if j["state"] not in ("planning", "queued", "running")][:10]
    main = next((j for j in active if j["kind"] == "mainline"), None)
    return {"at": jobs._iso(now), "workers": workers, "jobs": active, "recent": recent,
            "mainline": {"branch": gitcode.branch(), "head": gitcode.main_head(), "job": main["id"] if main else None,
                         "queued": main["counts"]["queued"] if main else 0, "leased": main["counts"]["leased"] if main else 0},
            "throughput": {"last_hour": per_machine, "per_10_min": buckets},
            "totals": {"queued": totals.get("queued", 0), "leased": totals.get("leased", 0), "results": stored[0] or 0, "promoted": stored[1] or 0}}
