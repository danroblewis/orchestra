"""The web UI: Dashboard, Machines, Dynamics and Core. Read-only for humans: nothing here
changes the system (AGENTS.md rule 9)."""

from __future__ import annotations

import asyncio
import threading
import time
from pathlib import Path

import psutil
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from .. import runtime
from ..config import Project
from ..events import Events
from .background import Refresher
from .core import CoreProbe
from .core_explore import Explorer
from .dynamics import model_view
from .traffic import merge as merge_counted

STATIC = Path(__file__).parent / "static"


def render(file: Path, stylesheets: list[str]) -> str:
    """An HTML page as served: ``{{v}}`` is the newest asset's mtime, so a browser never keeps a
    stale stylesheet or script after an upgrade, and the plugins' stylesheets are linked at the
    end of its head (after Orchestra's own) unless the page links them already."""
    v = str(int(max(p.stat().st_mtime for p in STATIC.glob("*"))))
    html = file.read_text(encoding="utf-8").replace("{{v}}", v)
    links = "".join(f'<link rel="stylesheet" href="{s}">\n' for s in stylesheets if s not in html)
    at = html.find("</head>")
    return html[:at] + links + html[at:] if at >= 0 else links + html


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

    stylesheets: list[str] = []   # the plugins', filled in by mount_plugins

    def page(name: str) -> str:
        return render(STATIC / name, stylesheets)

    @app.get("/", response_class=HTMLResponse)
    async def index() -> str:
        return page("index.html")

    @app.get("/machines", response_class=HTMLResponse)
    async def machines_page() -> str:
        return page("machines.html")

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
        return model_view(project, version, bg.levels, bg.levels_error)

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

    @app.get("/api/dynamics/simulate")
    def dynamics_simulate(horizon_min: float = 30.0) -> dict:
        """The model's equations run forward: from the start of the era to now, and from now
        ``horizon_min`` ahead (sd/simulate.py). Cheap: a few hundred steps over the cached history."""
        from ..sd.strategies import sd_installed
        if not sd_installed():
            return {"ok": False, "error": "simulating needs orchestra[sd] installed"}
        if not bg.ready("history") or not bg.history:
            return {"ok": False, "error": "reading the history for the first time…"}
        from ..sd.simulate import simulate
        model, h = bg.model(), bg.history
        start = max(h["start"], float((model.discovery or {}).get("fit_start") or h["start"]))
        try:
            return {"ok": True, **simulate(model, h, now=h["at"], start=start, horizon_s=max(1.0, min(horizon_min, 24 * 60)) * 60)}
        except Exception as e:  # noqa: BLE001 - shown in the drawer
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}

    @app.get("/api/machines")
    def machines() -> dict:
        """The machines seen on the bus and who publishes and listens for what, and the machines,
        channels and counted edges known from counted traffic: from the web server's background
        reads, never a read of the bus or a source on request."""
        if not bg.ready("index"):
            return {"ok": False, "error": "reading the event bus for the first time…", "warming": True}
        out = {"ok": True, **bg.index.view(bg.series, written=bg.written)}
        merge_counted(out, bg.counted, time.time())
        if bg.counted and bg.counted.get("failed"):
            out["counted_failed"] = bg.counted["failed"]
        declare(out["machines"])
        # the host publishes only when it starts and stops; whether it runs is in the runtime record
        up = bool(runtime.hosts(runtime.read(project)))
        for m in out["machines"]:
            if m["bootstrap"]:
                m["active"] = up
        if bg.errors:
            out["errors"] = dict(bg.errors)
        return out

    @app.get("/api/machines/{machine}/events")
    def machine_events(machine: str) -> dict:
        """A machine's last events, newest first: envelopes only."""
        return {"ok": True, "machine": machine, "events": bg.index.events_of(machine)}

    @app.get("/api/machines/{machine}/metrics")
    def machine_metrics(machine: str) -> dict:
        """The latest value of each series labelled with this machine."""
        out = []
        for name, labels in bg.series:
            if labels.get("machine") != machine:
                continue
            try:
                last = core.metrics.latest(name, labels) if core.metrics is not None else None
            except Exception:  # noqa: BLE001 - one bad series does not hide the rest
                last = None
            out.append({"name": name, "labels": {k: v for k, v in labels.items() if k not in ("project", "machine")},
                        "t": last[0] if last else None, "v": last[1] if last else None})
        return {"ok": True, "machine": machine, "series": sorted(out, key=lambda x: (x["name"], sorted(x["labels"].items())))}

    @app.get("/api/machines/{machine}/log")
    def machine_log(machine: str, instance: str | None = None, lines: int = 200) -> dict:
        """The tail of the log the machine (or one instance) announced; only a file within the
        project is read (machine_logs.py). Orchestra's own host: its log in the state directory."""
        from ..events import HOST
        from .machine_logs import readable, tail
        lines = max(10, min(lines, 2000))
        if machine == HOST:
            return {"ok": True, **core.logs("host", lines)}
        inst = None if instance is None else ("" if instance == machine else instance)
        path, why = readable(bg.index.log_path(machine, inst), [project.repo_root, project.state_dir])
        if path is None:
            return {"ok": False, "error": why}
        return {"ok": True, "path": str(path), "lines": tail(path, lines)}

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
            raw = subprocess.run(["ioreg", "-r", "-d", "1", "-c", "IOAccelerator", "-a"], capture_output=True, timeout=3, check=False).stdout
            items = plistlib.loads(raw) if raw else []
        except Exception:  # noqa: BLE001 - a host without this tool has no GPU reading
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

    declare = mount_plugins(app, project, stylesheets)
    return app


def mount_plugins(app: FastAPI, project: Project, stylesheets: list[str]):
    """Pages, static files and API routes of the installed plugins (orchestra/plugins.py).
    Adds their every-page stylesheets to ``stylesheets``; returns what adds their declared
    machines to the observed ones."""
    from .. import plugins as plug
    loaded = plug.load(project)
    taken = {getattr(r, "path", None) for r in app.routes}
    pages, scripts, errors = [], [], list(loaded.errors)
    for p in loaded.plugins:
        if p.static:
            scripts += [f"/plugins/{p.name}/static/{s}" for s in p.scripts if (p.static / s).is_file()]
            stylesheets.extend(f"/plugins/{p.name}/static/{s}" for s in p.stylesheets if (p.static / s).is_file())
            app.mount(f"/plugins/{p.name}/static", StaticFiles(directory=str(p.static)), name=f"plugin-{p.name}")
        if p.router is not None:
            app.include_router(p.router, prefix=f"/api/plugins/{p.name}")
        for pg in p.pages:
            if pg.path in taken:
                errors.append({"plugin": p.name, "error": f"page {pg.path} is already served"})
                continue
            taken.add(pg.path)
            pages.append({"plugin": p.name, "path": pg.path, "title": pg.title})

            def serve(f=pg.file) -> str:
                return render(Path(f), stylesheets)
            app.add_api_route(pg.path, serve, methods=["GET"], response_class=HTMLResponse, include_in_schema=False)

    @app.get("/api/plugins")
    def plugin_list() -> dict:
        """The installed plugins' pages (for the navigation) and any that failed to load."""
        return {"ok": True, "pages": pages, "scripts": scripts, "errors": errors}

    declared = [(p.name, d) for p in loaded.plugins for d in p.machines]

    def declare(machines: list[dict]) -> None:
        """Observed machines keep what was observed; a declaration names the package and the kind
        of a machine that announced neither, and adds a machine not seen yet (marked so)."""
        seen = {m["id"]: m for m in machines}
        for pkg, d in declared:
            m = seen.get(d.id)
            if m is not None:
                m["package"] = m.get("package") or pkg
                m["kind"] = m.get("kind") or d.kind
                continue
            machines.append({"id": d.id, "bootstrap": False, "mode": d.mode, "kind": d.kind, "package": pkg, "about": {},
                             "unseen": True, "publishes": [], "subscribes": list(d.listens_for), "metrics": [], "logs": [],
                             "instances": [], "first_seen": None, "last_seen": None, "active": False})
    return declare
