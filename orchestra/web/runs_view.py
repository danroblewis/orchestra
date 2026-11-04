"""The discovery job's runs for the Dynamics page's drawer and the Core page's process section:
the recent run records (``sd/runs.py``), the run going now with its phase, and the job's health
(``sd/runhealth.py``) with each source's daily count against its cap as it is now, and the
explorer's experiments (``sd/explorer.py``), which the drawer interleaves with the runs."""

from __future__ import annotations

import time

from ..sd.runhealth import health
from ..sd.store import ModelStore

RECENT = 200          # records served for the history table; the trend lines take the last day of them


def caps(project) -> dict[str, dict]:
    """Each source's requests today against its daily cap, read without taking a token."""
    from ..sources.limits import for_store
    from ..sources.spec import for_project
    out = {}
    for spec in for_project(project).sources:
        try:
            p = for_store(spec).peek()
            out[spec.name] = {"today": p.get("today"), "per_day": p.get("per_day")}
        except Exception:  # noqa: BLE001, S112 - a bucket that cannot be read is not counted
            continue
    return out


def runs_view(project, n: int = RECENT, now: float | None = None, cap_counts: dict | None = None) -> dict:
    now = time.time() if now is None else now
    store = ModelStore.for_state(project.state_dir)
    log = store.runs()
    recs = log.recent(max(1, min(int(n or RECENT), 2000)))
    going = log.current()
    if going is not None:
        going = {**going, "elapsed_s": round(now - float(going.get("started") or now), 1),
                 "phase_s": round(now - float(going.get("phase_started") or now), 1)}
        going.pop("process", None)
    cc = caps(project) if cap_counts is None else cap_counts
    every = project.config.discovery_every
    return {"ok": True, "now": now, "every_s": every, "running": going, "runs": recs, "caps": cc,
            "health": health(recs, every, now, cc, going), "experiments": store.explorer().recent(RECENT)}


def health_view(project, now: float | None = None) -> dict:
    """The health alone, with the last run and the one going now (the Core page)."""
    v = runs_view(project, 60, now)
    disc = [r for r in v["runs"] if r.get("kind") == "discovery"]
    return {"ok": True, "health": v["health"], "running": v["running"], "last": disc[-1] if disc else None, "every_s": v["every_s"]}
