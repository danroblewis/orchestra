"""The web UI: Dashboard, Machines, Dynamics and Core. Read-only for humans: nothing here
changes the system (AGENTS.md rule 7)."""

from __future__ import annotations

import asyncio
import threading
import time
from pathlib import Path

import psutil
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from .. import runtime
from ..config import Project
from ..events import Events
from .background import Refresher
from .core import CoreProbe
from .core_explore import Explorer
from .dynamics import model_view

STATIC = Path(__file__).parent / "static"


def _alive(pid) -> bool:
    try:
        return bool(pid) and psutil.Process(int(pid)).status() != psutil.STATUS_ZOMBIE
    except (psutil.NoSuchProcess, psutil.AccessDenied, ValueError):
        return False


def create_app(project: Project) -> FastAPI:
    app = FastAPI(title="Orchestra")
    events = Events.for_project(project)
    core = CoreProbe(project, events)
    explore = Explorer(core)
    bg = Refresher(project, events, core.metrics)
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
        return model_view(project, version, bg.levels, bg.errors.get("levels"))

    rediscovery: dict = {"running": False}

    @app.get("/api/dynamics/strategies")
    def dynamics_strategies() -> dict:
        """The discovery strategies there are, and what orchestra.toml configures."""
        from ..sd.rediscover import configured_strategy
        from ..sd.strategies import available
        cfg = project.config
        return {"ok": True, **available(), "configured": {"strategy": configured_strategy(project), "window_s": cfg.discovery_window,
                                                           "step_s": cfg.discovery_step, "every_s": cfg.discovery_every,
                                                           "options": cfg.discovery_options}}

    @app.post("/api/dynamics/rediscover")
    async def dynamics_rediscover(request: Request) -> dict:
        """Rediscover the model now, in the background. An observation, not a change to the
        system: it re-reads the metrics store, as the host does every few minutes."""
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001 - no body: the configured strategy
            body = {}
        if rediscovery["running"]:
            return {"ok": True, "started": False, "running": True}
        if core.metrics is None:
            return {"ok": False, "error": "the metrics store could not be opened"}

        def go():
            from ..sd.rediscover import rediscover
            try:
                r = rediscover(project, core.metrics, strategy=body.get("strategy") or None, options=body.get("options"),
                               window_s=body.get("window_s") or None, step_s=body.get("step_s") or None,
                               note="discovered on request: the structure changed")
                rediscovery.update(result={"at": r.at, "stocks": len(r.model.stocks), "flows": len(r.model.flows), "version": r.version,
                                           "strategy": r.strategy, "compute_ms": r.model.discovery.get("compute_ms")}, error=None)
            except Exception as e:  # noqa: BLE001 - reported to the page
                rediscovery.update(error=f"{type(e).__name__}: {e}")
            finally:
                rediscovery["running"] = False
        rediscovery["running"] = True
        threading.Thread(target=go, name="rediscover", daemon=True).start()
        return {"ok": True, "started": True, "running": True}

    @app.get("/api/dynamics/rediscover")
    def dynamics_rediscover_status() -> dict:
        return {"ok": True, **rediscovery}

    @app.get("/api/dynamics/history")
    def dynamics_history() -> dict:
        """The model's recent history (stock levels, flow rates), from the background cache."""
        if not bg.ready("history"):
            return {"ok": False, "error": "reading the history for the first time…"}
        return {"ok": True, **bg.history, "error": bg.errors.get("history")}

    @app.get("/api/machines")
    def machines() -> dict:
        """The machines seen on the bus and who publishes and listens for what: from the web
        server's background index, never a read of the bus on request."""
        if not bg.ready("index"):
            return {"ok": False, "error": "reading the event bus for the first time…", "warming": True}
        out = {"ok": True, **bg.index.view(bg.series)}
        # the host publishes only when it starts and stops; whether it runs is in the runtime record
        rec = runtime.read(project).get("host") or {}
        for m in out["machines"]:
            if m["bootstrap"]:
                m["active"] = _alive(rec.get("pid"))
        if bg.errors:
            out["errors"] = bg.errors
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
