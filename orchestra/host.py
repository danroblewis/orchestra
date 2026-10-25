"""The bootstrap host: Orchestra's own machine, started by ``orchestra run``.

In an empty Orchestra it does little, on purpose:
- it registers itself in the runtime record and writes its log (``<state>/logs/orchestra-host.log``);
- it publishes ``orchestra.host.started`` and ``orchestra.host.stopped``, and writes
  ``orchestra_host_up`` to the metrics store, so the host is observed like any machine;
- it runs Orchestra's event collector: every event on the bus, from any machine, counted by type
  and source (``orchestra.collectors``). It replays the whole bus once at start, so the counters
  continue from the full history, then follows the bus.
 Hosting drivers and starting the machines that
packages declare come later (docs/proposals/empty-orchestra.md)."""

from __future__ import annotations

import os
import signal
import threading
import time
from datetime import datetime

from . import runtime
from .collectors import EventCollector, backfill, collapse
from .config import Project
from .events import HOST, Events
from .metrics import Point
from .metrics import for_project as metrics_for

HOST_LOG_MAX = 5_000_000


class Host:
    def __init__(self, project: Project, interval: float = 15.0, collect_every: float = 2.0):
        self.project = project
        self.collect_every = collect_every
        self.events = Events.for_project(project, source=HOST)
        self.interval = interval
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

    def stop(self, *_):
        self._stop.set()

    def run(self, once: bool = False) -> None:
        runtime.update(self.project, lambda d: d.__setitem__("host", {"pid": os.getpid(), "since": time.time()}))
        signal.signal(signal.SIGTERM, self.stop)
        self.events.publish("orchestra.host.started", {"pid": os.getpid()})
        self.log(f"host started (pid {os.getpid()}) for {self.project.key}")
        if not once:
            threading.Thread(target=self._collect, name="collector", daemon=True).start()
        try:
            while not self._stop.is_set():
                self._beat(1.0)
                if once:
                    break
                self._stop.wait(self.interval)
        except KeyboardInterrupt:
            pass
        finally:
            self._beat(0.0)
            self.events.publish("orchestra.host.stopped", {"pid": os.getpid()})
            runtime.update(self.project, lambda d: d.pop("host", None) if (d.get("host") or {}).get("pid") == os.getpid() else None)
            self.log("host stopped")
