"""Read-only FastAPI app: state snapshot, ticket detail, transcripts, system stats, events.
SPEC.md section 11."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

import psutil
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from ..config import Project
from ..events import Events
from ..pi.client import read_transcript
from ..store import LocalStore, StoreError

STATIC = Path(__file__).parent / "static"


def create_app(project: Project) -> FastAPI:
    app = FastAPI(title="Orchestra")
    events = Events(project.events_file)
    store = LocalStore(project, events)
    app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")

    @app.get("/", response_class=HTMLResponse)
    async def index() -> str:
        return (STATIC / "index.html").read_text(encoding="utf-8")

    @app.get("/tickets", response_class=HTMLResponse)
    async def tickets_page() -> str:
        return (STATIC / "tickets.html").read_text(encoding="utf-8")

    @app.get("/api/state")
    async def state() -> dict:
        project.reload_config()
        snap = store.snapshot()
        snap["now"] = time.time()
        snap["gate_runs"] = store.gate_runs()[-30:]
        return snap

    @app.get("/api/system")
    def system() -> dict:
        """Host utilization. Sync so the CPU sampling interval runs in a worker thread."""
        vm = psutil.virtual_memory()
        try:
            disk = psutil.disk_usage(str(project.repo_root))
        except OSError:
            disk = psutil.disk_usage("/")
        load = psutil.getloadavg() if hasattr(psutil, "getloadavg") else (0, 0, 0)
        return {
            "cpu_percent": psutil.cpu_percent(percpu=True, interval=0.25),
            "load": [round(x, 2) for x in load],
            "memory": {"percent": vm.percent, "used": vm.used, "total": vm.total},
            "disk": {"percent": disk.percent, "used": disk.used, "total": disk.total, "path": str(project.repo_root)},
            "now": time.time(),
        }

    @app.get("/api/staging")
    async def staging() -> dict:
        log = project.state_dir / "staging" / "staging.log"
        configured = "staging" in project.config.raw
        text = ""
        if log.exists():
            text = log.read_text(encoding="utf-8", errors="replace")[-20000:]
        return {"configured": configured, "log": text, "status": "not implemented" if configured else "not configured"}

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
