"""The Machines panel: every machine in the factory model, AI agent or program, with what it is
doing now and the fitted equations of the flows it is attributed to.

Machines come from the project's model (``orchestra sd declare``; the declared factory if none is
stored). What each is doing comes from the live sessions and the loop's runtime record: a
machine's jobs are the running sessions that belong to it."""

from __future__ import annotations

import psutil

from ..sd.factory import ticket_factory
from ..sd.store import ModelStore

# which sessions belong to which machine: by exact id, or by id prefix
SESSION_OWNER = {"supervisor": "supervisor", "coordinator": "coordinator", "pipeline-manager": "pipeline-manager"}
SESSION_PREFIX = {"worker-": "worker", "reviewer-": "reviewer"}


def _alive(pid) -> bool:
    try:
        return bool(pid) and psutil.Process(int(pid)).status() != psutil.STATUS_ZOMBIE
    except (psutil.NoSuchProcess, psutil.AccessDenied, ValueError):
        return False


def _owner(session_id: str) -> str | None:
    if session_id in SESSION_OWNER:
        return SESSION_OWNER[session_id]
    return next((m for p, m in SESSION_PREFIX.items() if session_id.startswith(p)), None)


def machines_view(project, store, snapshot: dict) -> dict:
    model = ModelStore(project.state_dir / "models").load("tickets") or ticket_factory(project.key)
    flows = {f.id: f for f in model.flows}
    sessions = snapshot.get("sessions", [])
    jobs: dict[str, list[dict]] = {}
    resident_alive: dict[str, bool] = {}
    for s in sessions:
        owner = _owner(s["id"])
        if not owner:
            continue
        if s["id"] in SESSION_OWNER:
            resident_alive[owner] = _alive(s.get("pid"))
        if s.get("status") == "running":
            jobs.setdefault(owner, []).append({"session": s["id"], "ticket": s.get("ticket"),
                                               "text": (s.get("partial_text") or s.get("last_text") or "")[-160:]})
    loop = store.runtime().get("control") or {}
    loop_alive = _alive(loop.get("pid"))
    gate_running = any(r.get("status") == "running" for r in snapshot.get("gate_runs", []) or [])

    out = []
    for m in model.machines:
        if m.id == "orchestra-host":
            status = "running" if loop_alive else "stopped"
        elif m.id == "gate":
            status = "working" if gate_running else ("idle" if loop_alive else "stopped")
        elif m.id in ("supervisor", "coordinator", "pipeline-manager"):
            status = "working" if jobs.get(m.id) else ("waiting" if resident_alive.get(m.id) else "not running")
        elif m.engagement:
            status = "working" if jobs.get(m.id) else ("idle" if loop_alive else "stopped")
        else:
            status = "observed"
        fl = []
        for fid in m.attributed:
            f = flows.get(fid)
            eq = f.current() if f else None
            fl.append({"id": fid, "form": eq.form if eq else None,
                       "rate": next(iter(eq.params.values())) if eq else None,
                       "se": eq.quality.get("se") if eq else None,
                       "events": eq.quality.get("events") if eq else None,
                       "src": f.src if f else None, "origin": eq.origin if eq else None})
        out.append({"id": m.id, "name": m.name, "kind": m.kind, "description": m.description, "bootstrap": m.bootstrap,
                    "engagement": [{"mode": e.mode, "driver": e.driver} for e in m.engagement],
                    "status": status, "jobs": jobs.get(m.id, []), "flows": fl})
    return {"model": model.id, "fitted": any(f.current() for f in model.flows), "machines": out}
