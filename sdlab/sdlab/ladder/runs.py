"""The runs panel (the Now page) and the watcher's pace: what the watcher is doing, how fast it goes, how
much is stale, and when it will be done.

    pace(window)      the watcher's pace over its batches in the last `window` hours: {per_hour (results per hour
                      over the span from the first batch's start to now, planning gaps included), batches, done,
                      hours, jobs (the newest batch's workers), efficiency (busy seconds / (elapsed x workers) over
                      the batches that recorded busy seconds: how much of its workers' time went to items)}
    backlog(sm)       what is stale in the summary now (api.summary): {items, run, rescore, seconds (the estimated
                      busy seconds to clear it, timing.Estimator), by_set {set: [items, seconds]}, how {how: items}}
    panel()           {now, watcher: {batch, alive, pace, backlog, eta}, runs: [the newest runs]}; made in the
                      background (at most every REFRESH seconds) and served from memory; {pending: true} until
                      the first one is made
    eta(backlog, pace)  {by_pace: hours (items / per_hour), by_cost: hours (seconds / (jobs x efficiency)), at}

A run (store.runs) is one `sdlab-ladder run`, `sync` or one watch batch. Runs made before 2026-10-19 have
no worker count, backlog or counts; their done count reads as their total once finished.
"""

from __future__ import annotations

import os
import threading
import time
from datetime import datetime, timezone

from . import store, timing

WINDOW = 6.0           # hours of watch batches the pace is measured over
REFRESH = 20.0         # seconds between two panels


def _t(iso: str | None) -> float | None:
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp() if iso else None


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def alive(pid: int | None) -> bool | None:
    """Is the process running (None: not known)?"""
    if not pid:
        return None
    try:
        os.kill(int(pid), 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return None
    return True


def done_of(r: dict) -> int | None:
    if r.get("done") is not None:
        return int(r["done"])
    return int(r["total"]) if r.get("finished") else None


def state_of(r: dict, now: float | None = None) -> str:
    """running, finished or stopped (a run whose process is gone before it finished, or that went quiet
    for store.STALL seconds while its process cannot be checked)."""
    if r.get("finished"):
        d = done_of(r)
        return "stopped" if d is not None and d < r["total"] and r.get("done") is not None else "finished"
    a = alive(r.get("pid"))
    if a is False:
        return "stopped"
    if a is None and (now or time.time()) - (_t(r["started"]) or 0) > 24 * 3600:
        return "stopped"
    return "running"


def pace(window: float = WINDOW, now: float | None = None, runs: list[dict] | None = None) -> dict:
    now = now or time.time()
    runs = runs if runs is not None else store.runs(500, "watch")
    since = now - window * 3600
    got = [r for r in runs if (_t(r["started"]) or 0) >= since]
    out = {"per_hour": None, "batches": len(got), "done": 0, "hours": None, "jobs": runs[0].get("jobs") if runs else None, "efficiency": None}
    if not got or all(done_of(r) is None for r in got):
        return out
    first = min(_t(r["started"]) for r in got)
    newest = max(got, key=lambda r: r["id"])
    end = now if state_of(newest, now) == "running" else (_t(newest["finished"]) or now)
    span = max(end - first, 1.0)
    n = sum(done_of(r) or 0 for r in got)          # a running batch made before 2026-10-19 counts nothing done yet
    busy = [(r["busy"], (_t(r["finished"]) or now) - _t(r["started"]), r["jobs"]) for r in got if r.get("busy") and r.get("jobs")]
    work = sum(b for b, _, _ in busy)
    room = sum(max(e, 1.0) * j for _, e, j in busy)
    out.update(per_hour=round(n / span * 3600, 1), done=n, hours=round(span / 3600, 2),
               efficiency=round(work / room, 3) if room and work else None)
    return out


def backlog(sm: dict, est: timing.Estimator | None = None) -> dict:
    """See the module docstring. A real case's cell whose download is missing is not counted (the planner
    skips it too)."""
    from . import cases as casemod
    from .real import data as _real_data
    est = est or timing.estimator()
    real = {c["id"] for c in sm["cases"] if c.get("real")}
    missing: dict = {}
    out = {"items": 0, "run": 0, "rescore": 0, "seconds": 0.0, "by_set": {}, "how": {}}
    for c in sm["cells"]:
        why = c.get("stale")
        if not why:
            continue
        if c["case"] in real:
            k = (c["case"], c["variant"])
            if k not in missing:
                try:
                    missing[k] = bool(_real_data.available(casemod.load(c["case"]), c["variant"]))
                except Exception:                           # noqa: BLE001  (a case being edited: counted)
                    missing[k] = False
            if missing[k]:
                continue
        mode = "rescore" if why == "score_only" else "run"
        secs, how = est.estimate(c["case"], c["variant"], c["strategy"], mode)
        out["items"] += 1
        out[mode] += 1
        out["seconds"] += secs
        s = est.sets.get(c["case"], "tests")
        b = out["by_set"].setdefault(s, [0, 0.0])
        b[0] += 1
        b[1] += secs
        out["how"][how] = out["how"].get(how, 0) + 1
    out["seconds"] = round(out["seconds"], 1)
    out["by_set"] = {k: [v[0], round(v[1], 1)] for k, v in out["by_set"].items()}
    return out


def eta(bl: dict, pc: dict, now: float | None = None) -> dict:
    now = now or time.time()
    by_pace = bl["items"] / pc["per_hour"] if pc.get("per_hour") else None
    jobs = pc.get("jobs") or 4
    by_cost = bl["seconds"] / (jobs * pc["efficiency"]) / 3600 if pc.get("efficiency") else None
    best = by_cost if by_cost is not None else by_pace
    return {"by_pace": None if by_pace is None else round(by_pace, 2), "by_cost": None if by_cost is None else round(by_cost, 2),
            "ideal": round(bl["seconds"] / jobs / 3600, 2), "at": _iso(now + best * 3600) if best is not None else None}


def _brief(r: dict, now: float) -> dict:
    st = _t(r["started"])
    end = _t(r["finished"]) if r.get("finished") else now
    return {"id": r["id"], "command": r["command"], "started": r["started"], "finished": r.get("finished"), "state": state_of(r, now),
            "total": r["total"], "done": done_of(r), "errors": r.get("errors"), "timeouts": r.get("timeouts"), "jobs": r.get("jobs"),
            "backlog": r.get("backlog"), "busy": None if r.get("busy") is None else round(r["busy"], 1),
            "seconds": None if st is None or end is None else round(end - st, 1)}


def make(sm: dict | None = None, now: float | None = None) -> dict:
    """The panel (see the module docstring), made now."""
    now = now or time.time()
    if sm is None:
        from . import leaderboard
        sm = leaderboard.summary_now()[0]
    recent = store.runs(30)
    watch = store.runs(500, "watch")
    batch = _brief(watch[0], now) if watch else None
    if batch and batch["done"] is not None and batch["seconds"]:
        batch["per_hour"] = round(batch["done"] / max(batch["seconds"], 1.0) * 3600, 1)
    pc = pace(WINDOW, now, watch)
    bl = backlog(sm)
    return {"now": _iso(now), "watcher": {"batch": batch, "alive": alive(watch[0].get("pid")) if watch else None,
                                          "pace": pc, "backlog": bl, "eta": eta(bl, pc, now)},
            "runs": [_brief(r, now) for r in recent]}


_panel: dict = {}
_busy = threading.Lock()


def panel() -> dict:
    """The last panel made, never made in line: {pending: true} until the first is made in the background; a
    newer one is made in the background once the last is REFRESH seconds old."""
    got = _panel.get(str(store.path()))
    if (got is None or time.time() - got[0] >= REFRESH) and _busy.acquire(blocking=False):
        def remake(where=str(store.path())):
            try:
                _panel[where] = (time.time(), make())
            finally:
                _busy.release()
        threading.Thread(target=remake, daemon=True).start()
    return got[1] if got else {"pending": True}


def warm() -> None:
    """Start making the first panel (and so the timing table) in the background (the server calls this at start)."""
    panel()


def hours(x: float | None) -> str:
    """Hours as a person reads them: 40 s, 12 min, 3.4 h."""
    if x is None:
        return "–"
    s = x * 3600
    if s < 90:
        return f"{s:.0f} s"
    if s < 90 * 60:
        return f"{s / 60:.0f} min"
    return f"{x:.1f} h"

