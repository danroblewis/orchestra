"""none-long only confirms a none-short pass, on the pool as in the local planner (runner.confirm_of; the
user, 2026-10-20: the noise-free long run agreed with the short one on 97.7% of results and cost 42% of all
test time). docs/pool.md, "none-long confirms none-short".

A none-long item of a job is
- queued at once when a current none-short result of its case and strategy (exactly the short's hashes)
  is stored and passes, and skipped when that stored result does not pass;
- held (state `held`, never handed out) while the same job, or a running main-line item, will give that
  result (`confirm_id` names the none-short item); released to the queue when it passes, skipped otherwise
  (an error, a timeout, a cancelled or errored item: not a pass);
- skipped when no current none-short result is stored or coming.
A skipped item is never run, never stored as a result and never counted as a fail: job status counts it
under `skipped`. A job whose spec names the long variant itself (`--variants none-long`) or asks for
`every_variant` keeps every none-long item.
"""

from __future__ import annotations

HELD, SKIPPED = "held", "skipped"
WAITING = ("queued", "leased", HELD)


def confirm_of(case: dict, variant: dict) -> dict | None:
    """The none-short variant entry a plan's none-long variant confirms (None for any other variant)."""
    if variant.get("noise") != "none" or variant.get("length") != "long":
        return None
    return next((v for v in case["variants"] if v.get("noise") == "none" and v.get("length") == "short"), None)


def exempt(spec: dict, variant_name: str) -> bool:
    """Does the job keep every none-long item: --every-variant, or the long variant named itself?"""
    if spec.get("every_variant"):
        return True
    named = [v.strip() for v in (spec.get("variants") or "").split(",") if v.strip()]
    return variant_name in named


def why_skipped(short: str, status: str | None) -> str:
    return f"skipped: {short} did not pass" + (f" ({status})" if status else " (no current result)")


def _status(con, s) -> str | None:
    """The status a finished none-short item gave (None when it gave none: error, cancelled, skipped)."""
    if s["state"] == "done" and s["result_id"]:
        r = con.execute("SELECT status FROM pool_results WHERE id = ?", (s["result_id"],)).fetchone()
        return r[0] if r else None
    if s["state"] == "reused":
        if s["reused_id"]:
            r = con.execute("SELECT status FROM results WHERE id = ?", (s["reused_id"],)).fetchone()
            if r:
                return r[0]
        if s["reused_pool_id"]:
            r = con.execute("SELECT status FROM pool_results WHERE id = ?", (s["reused_pool_id"],)).fetchone()
            return r[0] if r else None
    return None


def release(con, now: str) -> set:
    """Decide the held items whose none-short item has finished: queued on a pass, skipped otherwise.
    Returns the jobs whose items changed."""
    rows = con.execute("SELECT h.id AS hid, h.job_id AS hjob, s.* FROM pool_items h JOIN pool_items s ON s.id = h.confirm_id"
                       " WHERE h.state = ? AND s.state NOT IN (?, ?, ?)", (HELD, *WAITING)).fetchall()
    hit = set()
    for s in rows:
        status = _status(con, s)
        if status == "pass":
            con.execute("UPDATE pool_items SET state = 'queued' WHERE id = ? AND state = ?", (s["hid"], HELD))
        else:
            con.execute("UPDATE pool_items SET state = ?, finished = ?, error = ? WHERE id = ? AND state = ?",
                        (SKIPPED, now, why_skipped(s["variant"], status or s["state"]), s["hid"], HELD))
        hit.add(s["hjob"])
    return hit


def link(con, job_id: int, pairs: list[tuple]) -> None:
    """Point a job's held items at the none-short items they wait for: pairs of ((case, long, strategy),
    the none-short item's id or its (case, short, strategy) in the same job)."""
    ids = {(r[0], r[1], r[2]): r[3] for r in con.execute("SELECT case_id, variant, strategy, id FROM pool_items WHERE job_id = ?", (job_id,))}
    for key, short in pairs:
        sid = short if isinstance(short, int) else ids.get(short)
        hid = ids.get(key)
        if hid is None:
            continue
        if sid is None:                                       # cannot happen (the short was planned with it): never hold for ever
            con.execute("UPDATE pool_items SET state = 'queued' WHERE id = ? AND state = ?", (hid, HELD))
        else:
            con.execute("UPDATE pool_items SET confirm_id = ? WHERE id = ?", (sid, hid))


def stored_status(stored: list[tuple], hashes: tuple) -> str | None:
    """The newest stored result's status with exactly these (case, strategy, score) hashes (jobs._stored's
    tuples), None when there is none."""
    for _src, _rid, rch, rsh, rsc, status, _found in stored:
        if (rch, rsh, rsc) == hashes:
            return status
    return None
