"""The bootstrap host: Orchestra's own machine, started by ``orchestra run``.

In an empty Orchestra it does little, on purpose:
- it registers itself in the runtime record and writes its log (``<state>/logs/orchestra-host.log``);
- it publishes ``orchestra.host.started`` and ``orchestra.host.stopped``, and writes
  ``orchestra_host_up`` to the metrics store, so the host is observed like any machine;
- it runs Orchestra's event collector: every event on the bus, from any machine, counted by type
  and source (``orchestra.collectors``). It replays the whole bus once at start, so the counters
  continue from the full history, then follows the bus;
- it rediscovers the model in the background (``orchestra.sd.rediscover``, with the strategy,
  window and interval in ``[discovery]``), caches the result for readers, and saves a new model
  version when the structure changed;
- it keeps running the commands the project declares (``[[machines]]`` in ``orchestra.toml``) and
  the plugins declare (``Plugin.processes``), through ``orchestra.launcher``, and stops them when
  it stops. Only one host launches for a project: a second one, started while the first runs,
  launches nothing and says so."""

from __future__ import annotations

import os
import signal
import threading
import time
from collections.abc import Callable
from datetime import datetime

from . import plugins, runtime
from .collectors import EventCollector, backfill, collapse
from .config import Project
from .events import HOST, Events
from .launcher import Launcher, Process
from .metrics import Point
from .metrics import for_project as metrics_for

HOST_LOG_MAX = 5_000_000


class Host:
    def __init__(self, project: Project, interval: float = 15.0, collect_every: float = 2.0,
                 found: Callable[[], list] | None = None, launch_every: float = 1.0):
        self.project = project
        self.collect_every = collect_every
        self.events = Events.for_project(project, source=HOST)
        self.interval = interval
        self.launch_every = launch_every
        self._found = found               # stands in for the installed plugins (tests)
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
        while not self._stop.is_set():
            self._stop.wait(self.collect_every)
            try:
                new, offset = self.events.read(offset, limit=100_000)
                pts = collapse([p for ev in new for p in col.observe(ev)])
                if pts:
                    store.write(pts)
            except Exception as e:  # noqa: BLE001 - keep following; the next read retries
                self.log(f"collector: {type(e).__name__}: {e}")

    def _discover(self) -> None:
        """Rediscover the model every interval (``orchestra.sd.rediscover``)."""
        from .sd.rediscover import Busy, rediscover

        wait = 5.0                                    # soon after starting, then every interval
        while not self._stop.wait(wait):
            wait = self.project.config.discovery_every
            try:
                r = rediscover(self.project, metrics_for(self.project), skip_if_busy=True)
                what = f"saved as version {r.version}" if r.version else "structure unchanged"
                self.log(f"discovery ({r.strategy}): {len(r.model.stocks)} stocks, {len(r.model.flows)} flows; {what}")
            except Busy:                              # the CLI or the web page is discovering: theirs will do
                self.log("discovery: skipped, another process is discovering this project")
            except Exception as e:  # noqa: BLE001 - try again next interval
                self.log(f"discovery: {type(e).__name__}: {e}")

    def _plugin_processes(self) -> list[Process]:
        loaded = plugins.load(self.project, self._found)
        for err in loaded.errors:
            self.log(f"plugin {err['plugin']} failed to load, so its processes are not started: {err['error']}")
        return [Process(p.name, p.command, p.restart, owner=plug.name) for plug in loaded.plugins for p in plug.processes]

    def _launch(self) -> None:
        """Keep the declared processes running until the host stops, then stop them."""
        launcher = Launcher(self.project, self.events.publish, self.log, self._plugin_processes())
        launcher.reap_orphans()
        try:
            while not self._stop.is_set():
                try:
                    launcher.tick()
                except Exception as e:  # noqa: BLE001 - keep launching; the next tick retries
                    self.log(f"launcher: {type(e).__name__}: {e}")
                self._stop.wait(self.launch_every)
        finally:
            launcher.stop_all()

    def _other_host(self) -> int | None:
        """The pid of another live host of this project, if one runs."""
        pid = (runtime.read(self.project).get("host") or {}).get("pid")
        return pid if pid and pid != os.getpid() and runtime.alive(pid) else None

    def stop(self, *_):
        self._stop.set()

    def run(self, once: bool = False) -> None:
        other = self._other_host()
        runtime.update(self.project, lambda d: d.__setitem__("host", {"pid": os.getpid(), "since": time.time()}))
        if threading.current_thread() is threading.main_thread():
            signal.signal(signal.SIGTERM, self.stop)
        self.events.publish("orchestra.host.started", {"pid": os.getpid()})
        self.events.publish("orchestra.machine.started", {"mode": "continuous", "listens_for": []})
        self.log(f"host started (pid {os.getpid()}) for {self.project.key}")
        if not once:
            threading.Thread(target=self._collect, name="collector", daemon=True).start()
            threading.Thread(target=self._discover, name="discovery", daemon=True).start()
        launching = None
        if other:
            self.log(f"launcher: another orchestra run (pid {other}) runs this project and keeps its processes; this one starts none")
        elif not once:
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
            runtime.update(self.project, lambda d: d.pop("host", None) if (d.get("host") or {}).get("pid") == os.getpid() else None)
            self.log("host stopped")
