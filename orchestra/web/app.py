"""Read-only FastAPI app: state snapshot, ticket detail, transcripts, events. SPEC.md section 11."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse

from ..config import Project
from ..events import Events
from ..model import State
from ..pi.client import read_transcript
from ..store import LocalStore, StoreError

STATIC = Path(__file__).parent / "static"


def _stats(store: LocalStore, snap: dict) -> dict:
    tickets = snap["tickets"]
    done = [t for t in tickets if t["state"] == State.DONE.value]
    durations = []
    for t in done:
        try:
            from datetime import datetime
            a = datetime.fromisoformat(t["created_at"])
            b = datetime.fromisoformat(t["state_since"])
            durations.append((b - a).total_seconds())
        except Exception:
            pass
    runs = snap["gate_runs"]
    landed = sum(1 for r in runs if r.get("status") == "landed")
    running = [s for s in snap["sessions"] if s.get("status") == "running"]
    cfg = store.project.config
    return {
        "workers": {"used": sum(1 for s in running if s.get("kind") == "worker"), "total": cfg.workers},
        "reviewers": {"used": sum(1 for s in running if s.get("kind") == "reviewer"), "total": cfg.reviewers},
        "gate_busy": any(r.get("status") == "running" for r in runs),
        "done": len(done),
        "mean_open_to_done_s": round(sum(durations) / len(durations)) if durations else None,
        "gate_runs": len(runs),
        "gate_pass_rate": round(landed / len(runs), 2) if runs else None,
    }


def create_app(project: Project) -> FastAPI:
    app = FastAPI(title="Orchestra")
    events = Events(project.events_file)
    store = LocalStore(project, events)

    @app.get("/", response_class=HTMLResponse)
    async def index() -> str:
        return (STATIC / "index.html").read_text(encoding="utf-8")

    @app.get("/api/state")
    async def state() -> dict:
        project.reload_config()
        snap = store.snapshot()
        snap["stats"] = _stats(store, snap)
        snap["now"] = time.time()
        return snap

    @app.get("/api/tickets/{ticket_id}")
    async def ticket(ticket_id: str) -> dict:
        try:
            t = store.get_ticket(ticket_id)
        except StoreError:
            raise HTTPException(404)
        return {**t.to_dict(), "notes": store.notes(ticket_id), "worktree": store.worktree(ticket_id)}

    @app.get("/api/sessions/{session_id}/transcript")
    async def transcript(session_id: str) -> dict:
        s = next((s for s in store.sessions() if s["id"] == session_id), None)
        if not s:
            raise HTTPException(404)
        msgs = read_transcript(s["pi_session_file"]) if s.get("pi_session_file") else []
        return {"session": s, "messages": msgs[-200:]}

    @app.get("/api/gate/runs/{run_id}")
    async def gate_run(run_id: str) -> dict:
        for r in store.gate_runs():
            if r["id"] == run_id:
                return r
        raise HTTPException(404)

    @app.get("/api/events")
    async def get_events(since: int = 0) -> dict:
        evs, nxt = events.read(since)
        return {"events": evs, "next": nxt}

    @app.websocket("/api/events")
    async def ws_events(ws: WebSocket) -> None:
        await ws.accept()
        _, offset = events.read(0, limit=1)
        try:
            while True:
                evs, offset = events.read(offset)
                for e in evs:
                    await ws.send_json(e)
                await asyncio.sleep(1)
        except WebSocketDisconnect:
            return

    return app
