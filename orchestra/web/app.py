"""The web UI: Dashboard, Machines, Instruments, Dynamics and Core. Read-only for humans: nothing here
changes the system (AGENTS.md rule 9). Every route, a plugin's too, is behind the project's web token
(web/auth.py), which the app's outermost middleware checks."""

from __future__ import annotations

import asyncio
import os
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
from .auth import AuthMiddleware, enabled
from .background import Refresher
from .core import CoreProbe
from .core_explore import Explorer
from .dynamics import era_eras, model_view
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


def create_app(project: Project, host: str = "127.0.0.1") -> FastAPI:
    """The app, as served on ``host``: whether it asks for the token follows ``[web] auth`` and
    whether ``host`` is a loopback address (web/auth.py)."""
    app = FastAPI(title="Orchestra")
    auth_on = enabled(project, host)
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

    @app.get("/health")
    def health() -> dict:
        """Whether the web server is up: the one route open without the token."""
        return {"ok": True}

    stylesheets: list[str] = []   # the plugins', filled in by mount_plugins

    def page(name: str) -> str:
        return render(STATIC / name, stylesheets)

    @app.get("/", response_class=HTMLResponse)
    async def index() -> str:
        return page("index.html")

    @app.get("/machines", response_class=HTMLResponse)
    async def machines_page() -> str:
        return page("machines.html")

    @app.get("/instruments", response_class=HTMLResponse)
    async def instruments_page() -> str:
        return page("instruments.html")

    @app.get("/api/instruments")
    def instruments() -> dict:
        """What measures the system (``[[collect]]``, ``[[scrape]]``, ``[[sources]]``): instruments,
        not machines. Read from the runtime record and orchestra.toml (web/instruments.py)."""
        from .instruments import instruments_view
        cached = bg.models.latest_discovery()
        return instruments_view(project, cached[1].discovery if cached else None)

    @app.get("/api/instruments/{name}/log")
    def instrument_log(name: str, lines: int = 200) -> dict:
        """The tail of an instrument's log; only a file within the project is read (machine_logs.py)."""
        from .machine_logs import readable, tail
        rec = (runtime.read(project).get("instruments") or {}).get(name) or {}
        path, why = readable(rec.get("log") or str(project.logs_dir / "instruments" / f"{name}.log"),
                             [project.repo_root, project.state_dir])
        if path is None:
            return {"ok": False, "error": why}
        return {"ok": True, "path": str(path), "lines": tail(path, max(10, min(lines, 2000)))}

    @app.get("/api/project")
    def project_info() -> dict:
        """The project and its configuration: the files it is read from (orchestra.toml and the
        private overlay) and each key with where it came from, read now. A value the overlay
        marks secret is left out; its key and origin are still shown (orchestra/overlay.py)."""
        from ..config import OVERLAY_ENV
        from ..overlay import describe
        files = [{"role": "repo", "path": str(project.config_file), "exists": project.config_file.exists()},
                 {"role": "overlay", "path": str(project.overlay_file), "exists": project.overlay_file.exists(),
                  "named_by": OVERLAY_ENV if os.environ.get(OVERLAY_ENV) else "state directory"}]
        out = {"key": project.key, "repo": str(project.repo_root), "config": {"files": files}}
        try:
            cfg = project.read_config()
        except Exception as e:  # noqa: BLE001 - shown, not fatal
            out["config"]["error"] = f"{type(e).__name__}: {e}"
            return out
        out["config"]["keys"] = describe(cfg.raw, cfg.layers)
        out["config"]["removed"] = cfg.layers.removed if cfg.layers else []
        return out

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
    def dynamics_model(version: int | None = None, era: str | None = None) -> dict:
        return model_view(project, version, bg.levels, bg.levels_error, era=era)

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

    @app.get("/api/dynamics/observability")
    def dynamics_observability() -> dict:
        """Which stocks what is measured determines, and which would need another instrument
        (sd/observability.py), at the mean levels of the cached history. Read-only."""
        from ..sd.strategies import sd_installed
        if not sd_installed():
            return {"ok": False, "error": "the observability report needs orchestra[sd] installed"}
        model = bg.model()
        if model is None or not model.stocks:
            return {"ok": False, "error": "there is no model yet"}
        from ..sd.observability import operating_point, report
        levels, inputs, point = operating_point(bg.history if bg.ready("history") else None)
        try:
            return report(model, levels, inputs, point=point)
        except Exception as e:  # noqa: BLE001 - reported to the caller
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}

    @app.post("/api/dynamics/whatif")
    async def dynamics_whatif(request: Request) -> dict:
        """What the model says a change would do, against no change, with a band and what is not
        trusted (sd/whatif.py), from the cached history. An observation, not a change (AGENTS.md
        rule 9): a POST only because the question is a JSON body; it changes no machine, saves no
        model version and writes no metric. The body: ``interventions`` (a list), and optionally
        ``stocks``, ``horizon_s``, ``step_s``, ``members``, ``seed``, ``bounds`` ({stock: [lo, hi]})
        and ``version`` (a saved version; default: the latest discovery)."""
        from ..sd.strategies import sd_installed
        if not sd_installed():
            return {"ok": False, "error": "simulating needs orchestra[sd] installed"}
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001 - no body or not JSON
            return {"ok": False, "error": "the body must be a JSON object with interventions"}
        if not isinstance(body, dict):
            return {"ok": False, "error": "the body must be a JSON object with interventions"}
        if not bg.ready("history") or not bg.history:
            return {"ok": False, "error": "reading the history for the first time…"}
        from ..sd.whatif import load, what_if
        try:
            model, label = load(bg.models, None if body.get("version") is None else int(body["version"]))
        except (ValueError, TypeError):
            return {"ok": False, "error": "version must be a saved version's number"}
        if model is None:
            return {"ok": False, "error": "no model yet"}
        h = bg.history
        try:
            bounds = {k: tuple(v) for k, v in (body.get("bounds") or {}).items()}
            r = await asyncio.to_thread(what_if, model, h, list(body.get("interventions") or []), stocks=body.get("stocks"),
                                        horizon_s=float(body.get("horizon_s") or 3600.0), step_s=body.get("step_s"),
                                        members=int(body.get("members", 24)), seed=int(body.get("seed", 0)), bounds=bounds, label=label)
        except (ValueError, TypeError) as e:
            return {"ok": False, "error": str(e)}
        return {"ok": True, **r}

    @app.get("/api/machines")
    def machines(era: str | None = None) -> dict:
        """The machines seen on the bus and who publishes and listens for what, and the machines,
        channels and counted edges known from counted traffic: from the web server's background
        reads, never a read of the bus or a source on request, except a past era's first (then
        kept). ``era``: the current era by default (sd/eras.py), an era's id, ``none`` (before
        any era) or ``all``."""
        if not bg.ready("index"):
            return {"ok": False, "error": "reading the event bus for the first time…", "warming": True}
        idx = bg.era_index(era)
        if idx is None:
            return {"ok": False, "error": f"there is no era {era}"}
        out = {"ok": True, **idx.view(flows=bg.flows), "era": era or bg.era, "current_era": bg.era,
               "eras": [vars(e) for e in era_eras(project)]}
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
    app.add_middleware(AuthMiddleware, project=project, on=auth_on)   # added last: the outermost, in front of every route
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
        for what, files, into in (("script", p.scripts, scripts), ("stylesheet", p.stylesheets, stylesheets)):
            for f in files:
                if p.static and (p.static / f).is_file():
                    into.append(f"/plugins/{p.name}/static/{f}")
                else:
                    errors.append({"plugin": p.name, "error": f"{what} {f} is not a file in its static directory; left out"})
        if p.static:
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
                             "unseen": True, "publishes": [], "subscribes": list(d.listens_for), "flows": [], "logs": [],
                             "instances": [], "first_seen": None, "last_seen": None, "active": False})
    return declare
