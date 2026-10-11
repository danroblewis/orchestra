"""Read-only FastAPI app: state snapshot, ticket detail, transcripts, system stats, events.
SPEC.md section 11."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

import psutil
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi import Request
from fastapi.responses import HTMLResponse, StreamingResponse
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

    @app.middleware("http")
    async def no_cache(request, call_next):
        resp = await call_next(request)
        resp.headers["Cache-Control"] = "no-store"
        return resp

    def page(name: str) -> str:
        # Cache-bust static assets with the newest asset mtime so browsers never
        # keep a stale stylesheet or script after an upgrade.
        v = str(int(max(p.stat().st_mtime for p in STATIC.glob("*"))))
        return (STATIC / name).read_text(encoding="utf-8").replace("{{v}}", v)

    @app.get("/", response_class=HTMLResponse)
    async def index() -> str:
        return page("index.html")

    @app.get("/tickets", response_class=HTMLResponse)
    async def tickets_page() -> str:
        return page("tickets.html")

    @app.get("/api/state")
    async def state() -> dict:
        project.reload_config()
        snap = store.snapshot()
        snap["now"] = time.time()
        snap["gate_runs"] = store.gate_runs()[-30:]
        snap["batch_size"] = 1  # the gate takes one ticket per run until batching lands
        for s in snap["sessions"]:
            s["alive"] = bool(s.get("pid")) and psutil.pid_exists(int(s["pid"]))
        snap["loop"] = store.runtime().get("control") or {}
        return snap

    gpu_history: list[dict] = []

    def gpu_sample() -> dict | None:
        """Apple GPU utilization from the IOAccelerator performance counters (no sudo).
        Returns None on non-Apple hosts or when ioreg is unavailable."""
        import plistlib
        import shutil
        import subprocess
        if not shutil.which("ioreg"):
            return None
        try:
            raw = subprocess.run(["ioreg", "-r", "-d", "1", "-c", "IOAccelerator", "-a"], capture_output=True, timeout=3).stdout
            items = plistlib.loads(raw) if raw else []
        except Exception:
            return None
        for it in items:
            ps = it.get("PerformanceStatistics") or {}
            if "Device Utilization %" in ps:
                return {"name": it.get("IOClass", "GPU"), "utilization": int(ps.get("Device Utilization %", 0)),
                        "renderer": int(ps.get("Renderer Utilization %", 0)), "tiler": int(ps.get("Tiler Utilization %", 0)),
                        "memory_used": int(ps.get("In use system memory", 0)), "memory_alloc": int(ps.get("Alloc system memory", 0))}
        return None

    @app.get("/api/system")
    def system() -> dict:
        """Host utilization. Sync so the CPU sampling interval runs in a worker thread."""
        gpu = gpu_sample()
        if gpu is not None:
            gpu_history.append({"t": time.time(), "u": gpu["utilization"]})
            del gpu_history[:-120]
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
            "gpu": gpu,
            "gpu_history": list(gpu_history),
            "now": time.time(),
        }

    @app.get("/api/landings")
    async def landings(hours: int = 24) -> dict:
        """Tickets landed on the base branch per hour, from gate run records."""
        from datetime import datetime, timezone
        hours = max(1, min(hours, 24 * 14))
        now_ts = time.time()
        start = int(now_ts // 3600) * 3600 - (hours - 1) * 3600
        buckets = [{"t": start + i * 3600, "landed": 0, "runs": 0, "failed": 0} for i in range(hours)]
        for r in store.gate_runs():
            if not r.get("finished_at"):
                continue
            try:
                ts = datetime.fromisoformat(r["finished_at"]).replace(tzinfo=timezone.utc).timestamp()
            except Exception:
                continue
            i = int((ts - start) // 3600)
            if 0 <= i < hours:
                buckets[i]["runs"] += 1
                if r.get("status") == "landed":
                    buckets[i]["landed"] += len(r.get("merged") or [])
                elif r.get("status") in ("rejected", "base_broken", "error", "conflict"):
                    buckets[i]["failed"] += 1
        total = sum(b["landed"] for b in buckets)
        return {"hours": hours, "buckets": buckets, "total": total, "per_hour": round(total / hours, 2)}

    @app.get("/api/burndown")
    async def burndown(hours: int = 24) -> dict:
        """Remaining (not DONE/CANCELLED) and total tickets over time, from the event log."""
        from datetime import datetime, timezone
        hours = max(1, min(hours, 24 * 30))
        since = time.time() - hours * 3600
        evs, _ = events.read(0, limit=200000)
        total = remaining = 0
        series: list[dict] = []
        for e in evs:
            t = e.get("type")
            if t not in ("ticket_created", "ticket_transition"):
                continue
            try:
                ts = datetime.fromisoformat(e["ts"]).replace(tzinfo=timezone.utc).timestamp()
            except Exception:
                continue
            if t == "ticket_created":
                total += 1; remaining += 1
            else:
                to, frm = e.get("to"), e.get("from")
                if to in ("DONE", "CANCELLED") and frm not in ("DONE", "CANCELLED"):
                    remaining -= 1
            if ts >= since:
                if not series:  # anchor the left edge at the window start with the value then
                    series.append({"t": since, "remaining": remaining, "total": total})
                series.append({"t": ts, "remaining": remaining, "total": total})
        # Carry the current value to now so the chart reaches the right edge.
        if not series:
            series.append({"t": since, "remaining": remaining, "total": total})
        series.append({"t": time.time(), "remaining": remaining, "total": total})
        return {"hours": hours, "series": series[-2000:], "remaining": remaining, "total": total}

    @app.get("/api/staging")
    async def staging() -> dict:
        from ..staging import Staging
        project.reload_config()
        st = Staging(project, store, events)
        state = st.state()
        build = store.runtime().get("builds", {}).get(state.get("current_build_id") or "")
        return {**state, "build": build, "log": st.logs(), "health_path": project.config.staging_health}

    @app.post("/api/supervisor")
    async def supervisor_message(request: Request):
        """The one write path in the UI: a human message to the resident Supervisor.
        Proxied to the control endpoint that `orchestra run` serves; streams its NDJSON."""
        import urllib.request

        body = await request.json()
        ctl = store.runtime().get("control") or {}
        if not ctl.get("port"):
            raise HTTPException(503, "orchestra run is not running; the Supervisor is only reachable while it is")
        req = urllib.request.Request(f"http://127.0.0.1:{ctl['port']}/supervisor", method="POST",
                                     data=__import__("json").dumps({"message": body.get("message", "")}).encode(),
                                     headers={"Content-Type": "application/json"})
        try:
            resp = await asyncio.to_thread(lambda: urllib.request.urlopen(req, timeout=project.config.turn_timeout + 30))
        except Exception as e:
            raise HTTPException(503, f"cannot reach orchestra run: {e}")

        async def gen():
            while True:
                line = await asyncio.to_thread(resp.readline)
                if not line:
                    break
                yield line

        return StreamingResponse(gen(), media_type="application/x-ndjson")

    @app.get("/api/context")
    async def context() -> dict:
        from .. import agents
        return {"text": agents.read_context(project)}

    @app.get("/api/tickets/{ticket_id}")
    async def ticket(ticket_id: str) -> dict:
        try:
            t = store.get_ticket(ticket_id)
        except StoreError:
            raise HTTPException(404)
        return {**t.to_dict(), "notes": store.notes(ticket_id), "worktree": store.worktree(ticket_id)}

    @app.get("/api/sessions/{session_id}/transcript")
    async def transcript(session_id: str) -> dict:
        s = store.find_session(session_id)
        if not s:
            raise HTTPException(404)
        f = s.get("pi_session_file")
        exists = bool(f) and Path(f).exists()
        msgs = read_transcript(f) if exists else []
        s = {**s, "alive": bool(s.get("pid")) and psutil.pid_exists(int(s["pid"])), "file_exists": exists}
        return {"session": s, "messages": msgs[-200:], "turns": sum(1 for m in msgs if m["role"] == "user")}

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
