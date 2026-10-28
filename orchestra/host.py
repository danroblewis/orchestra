"""The bootstrap host: Orchestra's own machine, started by ``orchestra run``.

In an empty Orchestra it does little, on purpose:
- it registers itself in the runtime record (``hosts``) and writes its log (``<state>/logs/orchestra-host.log``);
- it publishes ``orchestra.host.started`` and ``orchestra.host.stopped``, and writes
  ``orchestra_host_up`` to the metrics store, so the host is observed like any machine;
- it runs Orchestra's event collector: every event on the bus, from any machine, counted by type
  and source (``orchestra.collectors``). It replays the whole bus once at start, so the counters
  continue from the full history, then follows the bus;
- it records the eras the bus begins (``orchestra.sd.eras``: ``system.changed`` and the events
  ``[discovery] eras_from`` names) as it follows the bus, and announces each
  (``orchestra.era.started``);
- it rediscovers the model in the background (``orchestra.sd.rediscover``, with the strategy,
  window and interval in ``[discovery]``, within the current era), caches the result for
  readers, and saves a new model version when the structure changed or an era began; after each
  discovery it announces what is due about the model (``orchestra.sd.announce``:
  ``orchestra.model.changed``, ``orchestra.model.diverged``, ``orchestra.model.returned``);
- it records the predictions machines make of their changes as it follows the bus
  (``orchestra.prediction.made``, ``orchestra.sd.predictions``), and after each discovery judges
  those that are due and publishes each verdict (``orchestra.prediction.judged``,
  ``orchestra.sd.judge``);
- it keeps running the commands the project declares (``[[machines]]`` in ``orchestra.toml``) and
  the plugins declare (``Plugin.processes``), through ``orchestra.launcher``, and stops them when
  it stops. Only one host launches for a project (``launcher`` in the runtime record): a second one, started while the
  first runs, launches nothing, says so, and leaves the first one's record alone;
- in the host that launches, it serves the events endpoint (``orchestra.endpoint``): machines
  publish and read events over HTTP on ``[events] listen`` (127.0.0.1 and a port the system picks,
  unless given), with the project's token. Its address is in the runtime record
  (``events_endpoint``) and, with the token, in the environment of what the host launches
  (``ORCHESTRA_EVENTS_ENDPOINT``, ``ORCHESTRA_EVENTS_TOKEN``). It starts before the processes and
  stops after them, so a machine can publish until it is stopped;
- in the host that launches, it runs the instruments the project declares (``[[collect]]``, a
  command, and ``[[scrape]]``, a URL, in ``orchestra.toml``) and the plugins declare
  (``Plugin.collectors``) on their intervals and writes what they print, in the Prometheus text
  format, to the metrics store, labelled ``instrument=<name>`` (``orchestra.collect``). An
  instrument is not a machine: nothing is announced for it; its health is in the runtime record.

Stopping it (SIGTERM, SIGHUP or Ctrl-C) stops what it launched."""

from __future__ import annotations

import os
import signal
import threading
import time
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime

from . import endpoint, plugins, runtime
from .collect.runner import Collecting
from .collect.spec import Collector
from .collectors import EventCollector, backfill, collapse
from .config import Project
from .events import HOST, Events
from .launcher import Launcher, Process
from .metrics import Point
from .metrics import for_project as metrics_for

HOST_LOG_MAX = 5_000_000
ERAS_EVERY_S = 5.0              # how often the collector looks for events that begin an era


class Host:
    def __init__(self, project: Project, interval: float = 15.0, collect_every: float = 2.0,
                 found: Callable[[], list] | None = None, launch_every: float = 1.0):
        self.project = project
        self.collect_every = collect_every
        self.events = Events.for_project(project, source=HOST)
        self.interval = interval
        self.launch_every = launch_every
        self._found = found               # stands in for the installed plugins (tests)
        self._declared: dict[str, tuple[list[Process], list[Collector]]] = {}   # each plugin's, as last loaded
        self._loaded_for: tuple | None = None            # the configuration's stamp they were loaded for
        self._stop = threading.Event()

    def log(self, msg: str) -> None:
        line = f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} {msg}"
        print(line, flush=True)
        path = self.project.logs_dir / "orchestra-host.log"
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.exists() and path.stat().st_size > HOST_LOG_MAX:
                path.replace(path.with_suffix(".log.1"))
            with path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
        except OSError:
            pass

    def _beat(self, up: float) -> None:
        try:
            metrics_for(self.project).write([Point("orchestra_host_up", up, time.time(),
                                                   {"project": self.project.key, "machine": HOST})])
        except Exception as e:  # noqa: BLE001 - the host keeps running without its metric
            self.log(f"metrics: {type(e).__name__}: {e}")

    def _collect(self) -> None:
        """Follow the bus and keep the event counters current."""
        store = metrics_for(self.project)
        evs, offset = self.events.read(0, limit=10_000_000)
        rep = backfill(evs, project=self.project.key, store=store)
        col = EventCollector(self.project.key)
        for ev in evs:
            col.observe(ev)
        self.log(f"collector: replayed {rep.events} events into {rep.points} points; following the bus")
        eras_at = 0.0
        while not self._stop.is_set():
            if time.time() - eras_at >= ERAS_EVERY_S:
                eras_at = time.time()
                self._eras()
            self._stop.wait(self.collect_every)
            try:
                new, offset = self.events.read(offset, limit=100_000)
                pts = collapse([p for ev in new for p in col.observe(ev)])
                if pts:
                    store.write(pts)
            except Exception as e:  # noqa: BLE001 - keep following; the next read retries
                self.log(f"collector: {type(e).__name__}: {e}")

    def _eras(self) -> None:
        """Record the eras begun since the last look, and announce them (``orchestra.sd.eras``);
        record the predictions made since (``orchestra.sd.predictions``)."""
        from .sd import eras, predictions
        from .sd.store import ModelStore
        store = ModelStore.for_state(self.project.state_dir)
        try:
            _, new = eras.sync(store, self.events, self.project.config.eras_from, self.events.publish)
            for e in new:
                self.log(f"era {e.id} began: {e.label}")
        except Exception as e:  # noqa: BLE001 - the next look retries
            self.log(f"eras: {type(e).__name__}: {e}")
        try:
            for p in predictions.sync(store, self.events)[1]:
                self.log(f"prediction {p['id']} from {p['source']} about change {p.get('change')}: {p['status']}"
                         + (f" ({p['why']})" if p.get("why") else ""))
        except Exception as e:  # noqa: BLE001 - the next look retries
            self.log(f"predictions: {type(e).__name__}: {e}")

    def _judge(self, at: float) -> None:
        """Judge the predictions that are due (``orchestra.sd.judge``) and publish the verdicts."""
        from .sd.judge import judge_due
        for v in judge_due(self.project, metrics_for(self.project), at, self.events.publish, events=self.events):
            self.log(f"prediction {v['prediction']} judged: {v['verdict']} (era {v['era']})")

    def _announce(self, r) -> None:
        """What is due about the model after a discovery (``orchestra.sd.announce``)."""
        from .sd.announce import announce
        from .sd.store import ModelStore
        from .sd.strategies import sd_installed
        from .sources.catalogue import Catalogue
        from .web.background import history, stock_step

        cfg = self.project.config
        hist = None
        if sd_installed() and r.model.stocks:
            store, cat = metrics_for(self.project), Catalogue(self.project, metrics_for(self.project))
            step = stock_step(cfg.discovery_step)
            readers: dict = {}

            def raw(ref, start, end):
                if ref.source and ref.source != "own":
                    readers.setdefault((start, end), cat.reader(start, end, step))
                    return readers[(start, end)](ref)
                return store.raw(ref.name, ref.labels, start=start, end=end)
            span = max(cfg.diverge_after, 2 * cfg.discovery_every) + 600
            hist = history(r.model, raw, r.at, step, span_s=span)
        said = announce(ModelStore.for_state(self.project.state_dir), self.events.publish, r.model, r.at, hist,
                        hold=cfg.announce_hold, gap_s=cfg.announce_gap, after_s=cfg.diverge_after, every_s=cfg.discovery_every,
                        era_start=r.model.discovery.get("era_start"))
        if said:
            self.log(f"announced: {', '.join(said)}")

    def _discover(self) -> None:
        """Rediscover the model every interval (``orchestra.sd.rediscover``), then announce what is
        due about it."""
        from .sd.rediscover import Busy, rediscover

        wait = 5.0                                    # soon after starting, then every interval
        while not self._stop.wait(wait):
            wait = self.project.config.discovery_every
            try:
                r = rediscover(self.project, metrics_for(self.project), skip_if_busy=True, events=self.events)
                not_saved = r.model.discovery.get("not_saved")
                what = f"saved as version {r.version}" if r.version else (f"not saved: {not_saved}" if not_saved else "structure unchanged")
                self.log(f"discovery ({r.strategy}): {len(r.model.stocks)} stocks, {len(r.model.flows)} flows"
                         f"{', era ' + r.model.era if r.model.era else ''}; {what}")
                try:
                    self._announce(r)
                except Exception as e:  # noqa: BLE001 - the next discovery tries again
                    self.log(f"announce: {type(e).__name__}: {e}")
                try:
                    self._judge(r.at)
                except Exception as e:  # noqa: BLE001 - the next discovery tries again
                    self.log(f"predictions: {type(e).__name__}: {e}")
            except Busy:                              # the CLI or the web page is discovering: theirs will do
                self.log("discovery: skipped, another process is discovering this project")
            except Exception as e:  # noqa: BLE001 - try again next interval
                self.log(f"discovery: {type(e).__name__}: {e}")

    def _from_plugins(self) -> dict[str, tuple[list[Process], list[Collector]]]:
        """What the plugins ask to have run and collected, loaded again whenever orchestra.toml or
        the private overlay changes (the launcher and the collectors both ask; one load serves both): the project's
        config is read again first, since a plugin reads its own sections there. A plugin that
        fails to load keeps what it last declared; a config that does not parse raises, and the
        launcher and the collectors keep their last lists."""
        mtime = self.project.config_stamp()
        if mtime == self._loaded_for:
            return self._declared
        self.project.reload_config()
        loaded = plugins.load(self.project, self._found)
        now = {plug.name: ([replace(p, owner=plug.name) for p in plug.processes],
                           [replace(c, owner=plug.name) for c in plug.collectors]) for plug in loaded.plugins}
        for err in loaded.errors:
            self.log(f"plugin {err['plugin']} failed to load: {err['error']}; what it last declared, if anything, stands")
        if loaded.errors:
            now = {**self._declared, **now}
        self._declared, self._loaded_for = now, mtime
        return now

    def _plugin_processes(self) -> list[Process]:
        return [p for procs, _ in self._from_plugins().values() for p in procs]

    def _plugin_collectors(self) -> list[Collector]:
        return [c for _, cs in self._from_plugins().values() for c in cs]

    def _launch(self) -> None:
        """Keep the declared processes running and the declared collectors collecting until the
        host stops, then stop them."""
        served = self._serve_events()
        env = {endpoint.ENV_URL: served.url, endpoint.ENV_TOKEN: served.token} if served else {}
        launcher = Launcher(self.project, self.events.publish, self.log, self._plugin_processes, env=env)
        collecting = Collecting(self.project, self.log, plugin_collectors=self._plugin_collectors)
        launcher.reap_orphans()
        try:
            while not self._stop.is_set():
                try:
                    launcher.tick()
                except Exception as e:  # noqa: BLE001 - keep launching; the next tick retries
                    self.log(f"launcher: {type(e).__name__}: {e}")
                try:
                    collecting.tick()
                except Exception as e:  # noqa: BLE001 - keep collecting; the next tick retries
                    self.log(f"collect: {type(e).__name__}: {e}")
                self._stop.wait(self.launch_every)
        finally:
            collecting.stop()
            launcher.stop_all()
            if served is not None:
                served.stop()

    def _serve_events(self):
        """Start the events endpoint, or say why there is none; the host runs on without it."""
        from .endpoint.server import EventsEndpoint
        try:
            listen = endpoint.listen_address(self.project.config.events_listen)
            if listen is None:
                self.log("events endpoint: off ([events] listen)")
                return None
            ep = EventsEndpoint(self.project, Events.for_project(self.project), listen, endpoint.token(self.project), self.log)
            self.log(f"events endpoint: {ep.start()} (POST /events, GET /events; token in {endpoint.token_file(self.project)})")
            return ep
        except Exception as e:  # noqa: BLE001 - the core stays up without it
            self.log(f"events endpoint: not started: {type(e).__name__}: {e}")
            return None

    def _claim(self) -> int | None:
        """Take the launch for this project, unless a live host holds it; returns that host's pid,
        or None when this host now launches. Checked and set under the lock, so two hosts
        starting together cannot both take it."""
        mine = runtime.me()

        def take(d: dict) -> int | None:
            held = runtime.launcher(d)
            if held and held["pid"] != mine["pid"]:
                return held["pid"]
            d["launcher"] = mine
            return None
        return runtime.update(self.project, take)

    def _register(self, d: dict) -> None:
        d["hosts"] = {k: r for k, r in (d.get("hosts") or {}).items() if runtime.holds(r)}
        d["hosts"][str(os.getpid())] = runtime.me()
        d.pop("host", None)                       # the record before hosts and launcher were kept apart

    def _unregister(self, d: dict) -> None:
        (d.get("hosts") or {}).pop(str(os.getpid()), None)
        if (d.get("launcher") or {}).get("pid") == os.getpid():
            d.pop("launcher")

    def stop(self, *_):
        self._stop.set()

    def run(self, once: bool = False) -> None:
        runtime.update(self.project, self._register)
        if threading.current_thread() is threading.main_thread():
            signal.signal(signal.SIGTERM, self.stop)
            signal.signal(signal.SIGHUP, self.stop)       # a closed terminal stops the processes too
        self.events.publish("orchestra.host.started", {"pid": os.getpid()})
        self.events.publish("orchestra.machine.started", {"mode": "continuous", "listens_for": []})
        self.log(f"host started (pid {os.getpid()}) for {self.project.key}")
        if not once:
            threading.Thread(target=self._collect, name="collector", daemon=True).start()
            threading.Thread(target=self._discover, name="discovery", daemon=True).start()
        launching = None
        if not once:
            if other := self._claim():
                self.log(f"launcher: another orchestra run (pid {other}) runs this project and keeps its processes; this one starts none")
            else:
                launching = threading.Thread(target=self._launch, name="launcher")
                launching.start()
        try:
            while not self._stop.is_set():
                self._beat(1.0)
                if once:
                    break
                self._stop.wait(self.interval)
        except KeyboardInterrupt:
            pass
        finally:
            self._stop.set()
            if launching is not None:
                launching.join()
            self._beat(0.0)
            self.events.publish("orchestra.host.stopped", {"pid": os.getpid()})
            runtime.update(self.project, self._unregister)
            self.log("host stopped")
