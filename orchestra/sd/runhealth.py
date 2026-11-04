"""How healthy the discovery job is, from its run records (``runs.py``), in words.

- **red** when the last two discovery runs failed, or a source's store spent its daily request cap
  (no reads until 00:00 UTC);
- **amber** when a scheduled run is overdue (none ended within twice ``[discovery] every``, and
  none is going), the last run took more than ``SLOW`` times the median of the runs before it,
  was partial (a source missing or read in part), failed once, or its strategy stopped at its
  deadline;
- **green** when the last scheduled run succeeded within twice its interval and nothing above holds;
- **none** when no discovery run is recorded yet.

Every reason is said; the level is the worst of them."""

from __future__ import annotations

from statistics import median

SLOW = 3.0                  # times the median duration: a slow run
MEDIAN_OF = 50              # the runs before the last that the median is taken over
MEDIAN_MIN = 3              # ... at least this many, or no median is taken
SCHEDULED = ("schedule", "config change")
LEVELS = ("none", "green", "amber", "red")


def dur(s: float) -> str:
    s = max(0.0, float(s))
    if s < 60:
        return f"{s:.0f} s" if s >= 10 else f"{s:.1f} s"
    if s < 3600:
        return f"{int(s // 60)} m {int(s % 60)} s"
    if s < 86400:
        return f"{int(s // 3600)} h {int(s % 3600 // 60)} m"
    return f"{s / 86400:.1f} d"


def failed(r: dict) -> bool:
    return str(r.get("outcome") or "").startswith("failed")


def health(records: list[dict], every_s: float, now: float, caps: dict[str, dict] | None = None,
           running: dict | None = None) -> dict:
    """``records``: oldest first (``RunLog.recent``); ``caps``: each source's ``{today, per_day}``
    now; ``running``: the run going now (``RunLog.current``)."""
    disc = [r for r in records if r.get("kind") == "discovery"]
    found: list[tuple[str, str]] = []
    for name, c in sorted((caps or {}).items()):
        if c.get("per_day") and (c.get("today") or 0) >= c["per_day"]:
            found.append(("red", f"{name} spent its daily cap ({c['today']} of {c['per_day']} requests): no reads of it until 00:00 UTC"))
    if len(disc) >= 2 and failed(disc[-1]) and failed(disc[-2]):
        found.append(("red", f"the last two runs failed ({disc[-1]['outcome'][len('failed: '):] or 'no reason'})"))
    elif disc and failed(disc[-1]):
        found.append(("amber", f"the last run failed ({disc[-1]['outcome'][len('failed: '):] or 'no reason'})"))
    sched = [r for r in disc if r.get("trigger") in SCHEDULED]
    going = running is not None and running.get("kind") == "discovery"
    if disc or going:
        if sched:
            since = now - float(sched[-1].get("ended") or sched[-1].get("started") or 0)
            if since > 2 * every_s and not going:
                found.append(("amber", f"overdue: the last scheduled run ended {dur(since)} ago, and the host runs one every {dur(every_s)}"))
        elif not going:
            found.append(("amber", "no scheduled run recorded: is the host running? (only runs asked for by hand are)"))
    if disc:
        last = disc[-1]
        before = [float(r["duration_s"]) for r in disc[-1 - MEDIAN_OF:-1] if r.get("duration_s") is not None and not failed(r)]
        if len(before) >= MEDIAN_MIN and (med := median(before)) > 0 and float(last.get("duration_s") or 0) > SLOW * med:
            found.append(("amber", f"the last run took {dur(last['duration_s'])}, more than {SLOW:g}× the median of {dur(med)}"))
        if last.get("partial"):
            found.append(("amber", f"the last run was partial: {last['partial']}"))
        if last.get("outcome") == "timed out":
            found.append(("amber", "the last run's strategy stopped at its deadline: conservation's fits were kept"))
    if not disc:
        level = max((lv for lv, _ in found), key=LEVELS.index, default="none")
        reasons = [w for _, w in found] or (["a discovery is running: its first record is written when it ends"] if going
                                            else ["no discovery run recorded yet"])
        return {"level": level, "reasons": reasons}
    if not found:
        ok = next((r for r in reversed(sched) if not failed(r)), None)
        words = (f"the last scheduled run {ok['outcome']} {dur(now - float(ok.get('ended') or 0))} ago, within twice its interval "
                 f"of {dur(every_s)}") if ok else "the last run succeeded"
        return {"level": "green", "reasons": [words]}
    return {"level": max((lv for lv, _ in found), key=LEVELS.index), "reasons": [w for _, w in found]}
