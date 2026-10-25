"""The web UI: Dashboard, Machines, Dynamics and Core. Read-only for humans: nothing here
changes the system (AGENTS.md rule 7)."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

import psutil
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from ..config import Project
from ..events import Events
from .core import CoreProbe
from .core_explore import Explorer
from .dynamics import model_view
from .machines import machines_view

STATIC = Path(__file__).parent / "static"
MACHINES_CACHE_S = 5.0


def create_app(project: Project) -> FastAPI:
    app = FastAPI(title="Orchestra")
    events = Events.for_project(project)
    core = CoreProbe(project, events)
    explore = Explorer(core)
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

    @app.get("/machines", response_class=HTMLResponse)
    async def machines_page() -> str:
        return page("machines.html")

    @app.get("/agents")
    async def agents_redirect():
        return RedirectResponse("/machines", status_code=308)

    @app.get("/api/project")
    def project_info() -> dict:
        return {"key": project.key, "repo": str(project.repo_root)}

    # ---- Core: the fundamental services. Kept independent of the model and the machines, so
    # the page works when they do not (see web/core.py).
    @app.get("/core", response_class=HTMLResponse)
    async def core_page() -> str:
        return page("core.html")

    @app.get("/api/core")
    def core_status() -> dict:
        """The bootstrap host, the event bus and the metrics store, probed against their real backends."""
        return core.status()

    @app.post("/api/core/probe")
    def core_probe() -> dict:
        """Append a probe event to the event bus and read it back by offset."""
        return core.write_probe()

    @app.get("/api/core/metrics/catalog")
    def core_metrics_catalog() -> dict:
        return explore.catalog()

    @app.get("/api/core/metrics/query")
    def core_metrics_query(q: str, hours: float = 24) -> dict:
        return explore.query(q, hours)

    @app.get("/api/core/events")
    def core_events(hours: float = 24) -> dict:
        return explore.events(hours)

    @app.get("/api/core/logs/sources")
    def core_log_sources() -> dict:
        return {"sources": core.log_sources()}

    @app.get("/api/core/logs")
    def core_logs(source: str = "host", lines: int = 200) -> dict:
        return core.logs(source, lines)

    @app.get("/dynamics", response_class=HTMLResponse)
    async def dynamics_page() -> str:
        return page("dynamics.html")

    @app.get("/api/dynamics/model")
    def dynamics_model(version: int | None = None) -> dict:
        return model_view(project, version)

    machines_cache: dict = {}

    @app.get("/api/machines")
    def machines() -> dict:
        """The machines seen on the bus and the publish/subscribe graph; read in Core's pool
        under its time limit, cached briefly."""
        hit = machines_cache.get("v")
        if hit and time.time() - hit[0] < MACHINES_CACHE_S:
            return hit[1]

        def go():
            evs, _ = events.read(0, limit=10_000_000)
            series = core.metrics.series("") if core.metrics else []
            mine = [(n, lab) for n, lab in series if lab.get("project") == project.key]
            return {"ok": True, **machines_view(evs, mine)}
        try:
            out = core._pool.submit(go).result(timeout=8)
        except Exception as e:  # noqa: BLE001 - shown on the page
            out = {"ok": False, "error": f"{type(e).__name__}: {e}"}
        machines_cache["v"] = (time.time(), out)
        return out

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
    def system(gpu_window: int = 240) -> dict:
        """Host utilization. Sync so the CPU sampling interval runs in a worker thread.
        gpu_window is the seconds of GPU history to return (kept for up to one hour)."""
        gpu = gpu_sample()
        if gpu is not None:
            gpu_history.append({"t": time.time(), "u": gpu["utilization"]})
            del gpu_history[:-1800]
        cutoff = time.time() - max(30, min(gpu_window, 3600))
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
            "gpu_history": [p for p in gpu_history if p["t"] >= cutoff],
            "gpu_window": max(30, min(gpu_window, 3600)),
            "now": time.time(),
        }

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
