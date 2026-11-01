"""The web UI: Dashboard, Machines, Instruments, Dynamics and Core. Read-only for humans: nothing here
changes the system (AGENTS.md rule 9) beyond observations (rediscovering, and the intended model's
closed list of page controls, web/intended.py). Every route, a plugin's too, is behind the project's web token
(web/auth.py), which the app's outermost middleware checks."""

from __future__ import annotations

import contextlib
import os
import threading
import time

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from .. import runtime
from ..config import Project
from ..events import Events
from ..sd.extra import message as needs_sd
from .auth import AuthMiddleware, enabled
from .background import Refresher
from .core import CoreProbe
from .core_explore import Explorer
from .dynamics import era_eras, model_view, predictions_view
from .intended import attach_dynamics, attach_machines
from .intended import install as install_intended
from .machines import model_parts
from .pages import STATIC, render
from .plugins_mount import mount_plugins
from .sd_extra import install as install_sd_extra
from .sd_extra import unavailable
from .system import install as install_system
from .traffic import merge as merge_counted

EVENTS_PAGE = 1000              # /api/events' default page
EVENTS_PAGE_MAX = 10_000


@contextlib.asynccontextmanager
async def _lifespan(app: FastAPI):
    """At shutdown, kill a rediscovery's strategy child (``sd.bounded``): it runs in a session of
    its own, so stopping the server would otherwise leave it running."""
    yield
    from ..sd.bounded import kill_running
    kill_running()


def create_app(project: Project, host: str = "127.0.0.1") -> FastAPI:
    """The app, as served on ``host``: whether it asks for the token follows ``[web] auth`` and
    whether ``host`` is a loopback address (web/auth.py)."""
    app = FastAPI(title="Orchestra", lifespan=_lifespan)
    auth_on = enabled(project, host)
    events = Events.for_project(project)
    core = CoreProbe(project, events)
    explore = Explorer(core)
    bg = Refresher(project, events, core.metrics)
    app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")
    install_sd_extra(app)

    def observed_machines() -> set[str] | None:
        """The machine ids the Machines page has observed in the current era (the bus and counted
        traffic), what ``design()`` says is heard by; None until the bus is first read."""
        from ..sd.intended.machines_view import observed_ids
        bg.want("counted")
        idx = bg.era_index(None) if bg.ready("index") else None
        if idx is None:
            return None
        out = {"machines": idx.view(flows=bg.flows)["machines"]}
        merge_counted(out, bg.counted, time.time())
        return observed_ids(out["machines"])
    install_intended(app, project, events, core.metrics, observed=observed_machines)

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
        from .measured import hung_on
        cached = bg.models.latest_discovery()
        out = instruments_view(project, cached[1].discovery if cached else None)
        try:                                        # which declared machines each one is attached to (web/measured.py)
            hung_on(out["instruments"], project, bg.models.intended().read()["layer"], bg.measured)
        except Exception as e:  # noqa: BLE001 - the instruments are shown without their attachments
            out["hung_on_error"] = f"{type(e).__name__}: {e}"
        return out

    @app.get("/api/instruments/{name}/series")
    def instrument_series_(name: str) -> dict:
        """The series an instrument wrote in the last hour, each with its latest value
        (web/instrument_series.py): read from the metrics store, never by running the instrument."""
        from ..collect.views import declared
        from .instrument_series import instrument_series
        try:
            views = declared(project).get(name, ())
        except Exception:  # noqa: BLE001 - the series are listed by their labels
            views = ()
        return instrument_series(core.metrics, name, time.time(), views=views)

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

    # Core: the fundamental services. Kept independent of the model and the machines, so
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

    @app.get("/api/core/processes/{name}/log")
    def core_process_log(name: str, lines: int = 200) -> dict:
        """A launched process's log tail: lines (oldest first), more, size, path, error, note."""
        return core.process_log(name, lines)

    @app.get("/dynamics", response_class=HTMLResponse)
    async def dynamics_page() -> str:
        return page("dynamics.html")

    @app.get("/api/dynamics/model")
    def dynamics_model(version: int | None = None, era: str | None = None, since: str | None = None) -> dict:
        """The model, and beside it the declared layer compared with it (``model.intended``,
        web/intended.py): ``since`` the base version (the previous by default, ``off`` for no marks)."""
        from ..sd.strategies import sd_installed
        bg.want("remote")                           # a page shows the levels: read remote ones while it does
        out = model_view(project, version, bg.levels, bg.levels_error, era=era)
        if out.get("ok"):
            attach_dynamics(project, out, since, core.metrics)
            attach_askers(out)
        elif bg.ready("index"):                     # no model: the earliest event's time as its source stamped it (the bus keeps no receive time), so the page can say how much data there is
            out["bus_since"] = bg.index.bus_since()
        if not sd_installed():                      # conservation only: say what is missing, and how to have it
            out["sd_missing"] = needs_sd("behaviour trust, simulation and SD Lab's strategies")
        return out

    def attach_askers(out: dict) -> None:
        """Who the owner's requests reach (``model.intended.askers``), so the Dynamics page names
        them as the Machines page does; left out while the bus is unread (the page then names nobody)."""
        from ..sd.intended.requests import askers
        block = out["model"].get("intended")
        if not isinstance(block, dict) or "error" in block or not bg.ready("index") or (idx := bg.era_index(None)) is None:
            return
        machines = idx.view(flows=bg.flows)["machines"]
        declare(machines)
        block["askers"] = askers(machines)

    @app.get("/api/dynamics/predictions")
    def dynamics_predictions(era: str | None = None) -> dict:
        """The predictions machines made of their changes and their verdicts (sd/predictions.py,
        sd/judge.py), each with the era its change began; ``era`` keeps one era's ("none": those
        whose change has not begun one)."""
        return predictions_view(project, era)

    rediscovery: dict = {"running": False}
    plugin_collectors: dict = {"stamp": None, "list": []}   # the loaded plugins' (mount_plugins): which instruments are simulated

    def collectors_now() -> list:
        """The plugins' collectors, loaded again, with the configuration, when orchestra.toml or the
        private overlay changed since they were loaded: a plugin writes its entries while the web
        server runs, and only the host reloads otherwise."""
        stamp = project.config_stamp()
        if stamp != plugin_collectors["stamp"]:
            from ..config import fresh_config
            from ..sd.simulated import PluginsUnknown
            from ..sd.simulated import plugin_collectors as load_collectors
            fresh_config(project)
            try:
                loaded = load_collectors(project)
            except PluginsUnknown as e:              # the failed plugins are on /api/plugins; the rest count
                loaded = e.collectors
            plugin_collectors.update(stamp=stamp, list=loaded)
        return plugin_collectors["list"]

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
            from ..sources.catalogue import reading_only
            try:
                with reading_only():                # another store's definitions are the host's to infer
                    r = rediscover(project, core.metrics, strategy=body.get("strategy") or None, options=body.get("options"),
                                   window_s=body.get("window_s") or None, step_s=body.get("step_s") or None,
                                   note="discovered on request: the structure changed", collectors=collectors_now())
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
        bg.want("remote")
        if not bg.ready("history"):
            return {"ok": False, "error": "reading the history for the first time…"}
        return {"ok": True, **bg.history, "error": bg.errors.get("history")}

    @app.get("/api/dynamics/simulate")
    def dynamics_simulate(horizon_min: float = 30.0) -> dict:
        """The model's equations run forward: from the start of the era to now, and from now
        ``horizon_min`` ahead (sd/simulate.py). Cheap: a few hundred steps over the cached history."""
        from ..sd.strategies import sd_installed
        if not sd_installed():
            return unavailable("simulating")
        bg.want("remote")
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
            return unavailable("the observability report")
        model = bg.model()
        if model is None or not model.stocks:
            return {"ok": False, "error": "there is no model yet"}
        from ..sd.observability import operating_point, report
        bg.want("remote")
        levels, inputs, point = operating_point(bg.history if bg.ready("history") else None)
        try:
            return report(model, levels, inputs, point=point)
        except Exception as e:  # noqa: BLE001 - reported to the caller
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}

    @app.get("/api/dynamics/eras")
    def dynamics_eras() -> dict:
        """The eras, each era's versions, and what changed at the last boundary (sd/compare.py)."""
        from ..sd.reads import eras
        return eras(bg.models)

    @app.get("/api/machines")
    def machines(era: str | None = None) -> dict:
        """The machines seen on the bus and who publishes and listens for what, and the machines,
        channels and counted edges known from counted traffic: from the web server's background
        reads, never a read of the bus or a source on request, except a past era's first (then
        kept). ``era``: the current era by default (sd/eras.py), an era's id, ``none`` (before
        any era) or ``all``."""
        bg.want("counted")                          # counted traffic is read from other stores while a page shows it
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
        attach_machines(project, out, bg.model(), bg.measured)   # the declared machines and what measures them (web/intended.py)
        # the host publishes only when it starts and stops; whether it runs is in the runtime record
        # (``active_by``: what the flag was judged by, so no page says "in rhythm" of it)
        up = bool(runtime.hosts(runtime.read(project)))
        for m in out["machines"]:
            if m["bootstrap"]:
                m["active"], m["active_by"] = up, "runtime"
        out["model_parts"] = model_parts(bg.model())   # what the cards' flow chips are named by (sd-graph.js), as on Dynamics
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

    install_system(app, project)

    @app.get("/api/events")
    def get_events(since: int = 0, limit: int = EVENTS_PAGE) -> dict:
        """The events after ``since``, in order, at most ``limit`` (capped at ``EVENTS_PAGE_MAX``),
        and ``next``: where the next call resumes. Following ``next`` from 0 reads every event once
        (``Events.page``: offsets are cursors, so a skipped line never repeats one); an empty page
        means nothing more now. A plain ``def``, so a hung bus holds a worker thread, never the
        event loop the Core page's probes answer on (rule 8)."""
        limit = max(1, min(limit, EVENTS_PAGE_MAX))
        evs, nxt = events.page(since, limit)
        for _ in range(EVENTS_PAGE_MAX // limit):     # pages of only malformed lines: read past them
            if evs or nxt >= events.end():
                break
            evs, nxt = events.page(nxt, limit)
        return {"events": evs, "next": nxt}

    stamp = project.config_stamp()
    declare, loaded_collectors = mount_plugins(app, project, stylesheets)
    plugin_collectors.update(stamp=stamp, list=loaded_collectors)
    app.add_middleware(AuthMiddleware, project=project, on=auth_on)   # added last: the outermost, in front of every route
    return app
