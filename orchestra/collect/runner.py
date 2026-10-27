"""Running the declared collectors on their intervals, for the host that launches.

``tick`` is called every second or so (with the launcher's tick). It reads ``orchestra.toml`` again
whenever the file changed, and asks the plugins for theirs again then too (``Plugin.collectors``;
a project entry of the same name wins): a collector added starts at once, one removed stops (a round under way
finishes and its points are dropped), one changed starts over with its new entry. Each due round
runs in a thread of its own, so a slow one holds up no other; a collector whose last round is still
running skips its turn.

When a collector is added or changed, the host announces it on the bus on its behalf
(``orchestra.machine.started`` with the collector's name as ``source``: mode ``scheduled`` for a
command, ``continuous`` for a scraped program, kind ``program``, its log, and a plugin's name as
``package``), so it appears on the
Machines page though it imports nothing.

A round that fails writes nothing, adds a line to the host's log and the collector's log, and is
counted in ``orchestra_collect_failures_total{collector=<name>}``, which the host writes as its own
(``machine="orchestra-host"``): a failing collector's writes must not look like it is alive. A
series named ``orchestra_*`` is refused, said once per series. A round that succeeds adds a line
to the collector's log only."""

from __future__ import annotations

import threading
import time
import tomllib
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from ..config import Project
from ..events import HOST
from ..launcher import LOG_MAX
from ..metrics import Point
from ..metrics import for_project as metrics_for
from .round import Round, collect
from .spec import Collector, from_toml

FAILURES = "orchestra_collect_failures_total"


@dataclass
class Collecting:
    project: Project
    publish: Callable[..., object]          # Events.publish: (type, data, source=...)
    log: Callable[[str], None]              # the host's log
    open_store: Callable[[], object] | None = None   # opens the metrics store; default: the project's
    plugin_collectors: list[Collector] | Callable[[], list[Collector]] = field(default_factory=list)   # a callable
                                                     # is asked again whenever orchestra.toml changes
    wanted: dict[str, Collector] = field(default_factory=dict)
    failures: Counter = field(default_factory=Counter)
    _due: dict[str, float] = field(default_factory=dict)
    _busy: dict[str, threading.Thread] = field(default_factory=dict)
    _mtime: float | None = None
    _said: set[str] = field(default_factory=set)
    _plugins: list[Collector] = field(default_factory=list)
    _stop: threading.Event = field(default_factory=threading.Event)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def _say_once(self, msg: str) -> None:
        if msg not in self._said:
            self._said.add(msg)
            self.log(f"collect: {msg}")

    def _log_of(self, c: Collector) -> Path:
        return self.project.logs_dir / "machines" / f"{c.name}.log"

    def _note(self, c: Collector, msg: str) -> None:
        path = self._log_of(c)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.exists() and path.stat().st_size > LOG_MAX:
                path.replace(path.with_suffix(".log.1"))
            with path.open("a", encoding="utf-8") as f:
                f.write(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} [orchestra] {msg}\n")
        except OSError:
            pass

    def _read(self) -> None:
        """Take ``orchestra.toml``'s collectors and the plugins' again if the file changed; a file
        that cannot be read leaves them as they are, and plugins that cannot be asked leave theirs."""
        path = self.project.repo_root / "orchestra.toml"
        try:
            mtime = path.stat().st_mtime
            if mtime == self._mtime:
                return
            self._mtime = mtime
            self._ask_plugins()
            found, errors = from_toml(tomllib.loads(path.read_text(encoding="utf-8")), self._plugins)
        except (OSError, ValueError) as e:
            self._say_once(f"cannot read {path.name}: {type(e).__name__}: {e}; keeping the collectors as they were")
            return
        for err in errors:
            self._say_once(err)
        now = {c.name: c for c in found}
        with self._lock:
            for name in [n for n in self.wanted if n not in now]:
                self.log(f"collect: {name}: no longer declared; stopped")
                self._due.pop(name, None)
            for c in now.values():
                if self.wanted.get(c.name) != c:
                    self._due[c.name] = 0.0
                    self._announce(c)
            self.wanted = now

    def _ask_plugins(self) -> None:
        if not callable(self.plugin_collectors):
            self._plugins = list(self.plugin_collectors)
            return
        try:
            self._plugins = list(self.plugin_collectors())
        except Exception as e:  # noqa: BLE001 - a plugin's mistake must not stop what collects
            self._say_once(f"cannot read the plugins' collectors: {type(e).__name__}: {e}; keeping theirs as they were")

    def _announce(self, c: Collector) -> None:
        what = {"command": c.target} if c.kind == "collect" else {"url": c.target}
        package = {"package": c.owner} if c.owner != "project" else {}
        self.publish("orchestra.machine.started", {"mode": c.mode, "kind": "program", "listens_for": [],
                                                   "log": str(self._log_of(c)), "collector": c.kind, **what,
                                                   "every_s": c.every_s, **package}, source=c.name)
        self.log(f"collect: {c.name}: {'running' if c.kind == 'collect' else 'scraping'} `{c.target}` every {c.every_s:g} s")

    def tick(self, now: float | None = None) -> None:
        """Start the rounds that are due."""
        self._read()
        now = time.time() if now is None else now
        with self._lock:
            for name, c in self.wanted.items():
                run = self._busy.get(name)
                if (run is not None and run.is_alive()) or now < self._due.get(name, 0.0):
                    continue
                self._due[name] = now + c.every_s
                self._busy[name] = t = threading.Thread(target=self._round, args=(c,), name=f"collect-{name}", daemon=True)
                t.start()

    def _round(self, c: Collector) -> None:
        r = collect(c, self.project.repo_root, self.project.key, self._log_of(c), self._stop)
        with self._lock:
            current = self.wanted.get(c.name) == c and not self._stop.is_set()
        if current:
            self._record(c, r)

    def _record(self, c: Collector, r: Round) -> None:
        if r.error:
            self.failures[c.name] += 1
            self.log(f"collect: {c.name}: {r.error}; nothing written")
            self._note(c, f"{r.error}; nothing written")
            self._write([Point(FAILURES, self.failures[c.name], time.time(),
                               {"project": self.project.key, "machine": HOST, "collector": c.name})])
            return
        for name in r.refused:
            self._say_once(f"{c.name}: series {name} refused: the orchestra_ prefix is Orchestra's own; "
                           f"rename it for what it measures (docs/machines.md)")
            self._note(c, f"series {name} refused: the orchestra_ prefix is Orchestra's own; rename it")
        if r.bad:
            n, why = r.bad[0]
            self._say_once(f"{c.name}: {len(r.bad)} line(s) of its output not understood and skipped (line {n}: {why})")
        if self._write(r.points):
            self._note(c, f"wrote {len(r.points)} points" + (f"; skipped {len(r.bad)} line(s), first line {r.bad[0][0]}: {r.bad[0][1]}"
                                                             if r.bad else ""))

    def _write(self, points: list[Point]) -> bool:
        try:
            (self.open_store or (lambda: metrics_for(self.project)))().write(points)
            return True
        except Exception as e:  # noqa: BLE001 - the next round tries again
            self.log(f"collect: cannot write to the metrics store: {type(e).__name__}: {e}")
            return False

    def idle(self, timeout: float = 30.0) -> bool:
        """Wait for the rounds under way to finish; whether they all did."""
        end = time.time() + timeout
        for t in list(self._busy.values()):
            t.join(max(0.0, end - time.time()))
        return not any(t.is_alive() for t in self._busy.values())

    def stop(self) -> None:
        """Stop: a command under way is killed, and nothing more is written."""
        self._stop.set()
        self.idle(max((c.timeout_s for c in self.wanted.values()), default=0.0) + 2.0)
