"""Running the declared instruments on their intervals, for the host that launches.

``tick`` is called every second or so (with the launcher's tick). It reads ``orchestra.toml`` again
whenever the file changed, and asks the plugins for theirs again then too (``Plugin.collectors``;
a project entry of the same name wins): an instrument added starts at once, one removed stops (a
round under way finishes and its points are dropped), one changed starts over with its new entry.
Each due round runs in a thread of its own, so a slow one holds up no other; an instrument whose
last round is still running skips its turn.

An instrument is not a machine (AGENTS.md rule 7): nothing is announced on the bus for it. Its
health is recorded where Orchestra's own processes are: in the runtime record under
``instruments`` (what it is, its target, how often, its log, its last write and how many points,
its failures and the last error), at most every ``RECORD_EVERY_S`` unless an instrument was added,
removed, failed, first wrote or wrote a different number of points; in its log
(``<state>/logs/instruments/<name>.log``); and in the host's log.

A round that fails writes nothing, adds a line to the host's log and the instrument's log, and is
counted in ``orchestra_collect_failures_total{collector=<name>}``, which the host writes as its own
(``machine="orchestra-host"``). A series named ``orchestra_*`` is refused, said once per series. A
round that succeeds adds a line to the instrument's log only."""

from __future__ import annotations

import threading
import time
import tomllib
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .. import runtime
from ..config import Project
from ..events import HOST
from ..launcher import LOG_MAX
from ..metrics import Point
from ..metrics import for_project as metrics_for
from .round import Round, collect
from .spec import Collector, from_toml

FAILURES = "orchestra_collect_failures_total"
RECORD_EVERY_S = 5.0


@dataclass
class Collecting:
    project: Project
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
    health: dict[str, dict] = field(default_factory=dict)   # name -> its last write, points, last error
    _recorded: dict | None = None
    _recorded_at: float = 0.0
    _urgent: bool = False
    _stop: threading.Event = field(default_factory=threading.Event)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def _say_once(self, msg: str) -> None:
        if msg not in self._said:
            self._said.add(msg)
            self.log(f"collect: {msg}")

    def _log_of(self, c: Collector) -> Path:
        return self.project.logs_dir / "instruments" / f"{c.name}.log"

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
                self.health.pop(name, None)
            for c in now.values():
                if self.wanted.get(c.name) != c:
                    self._due[c.name] = 0.0
                    self.log(f"collect: {c.name}: {'running' if c.kind == 'collect' else 'scraping'} `{c.target}` every {c.every_s:g} s")
            self.wanted = now
            self._urgent = True

    def _ask_plugins(self) -> None:
        if not callable(self.plugin_collectors):
            self._plugins = list(self.plugin_collectors)
            return
        try:
            self._plugins = list(self.plugin_collectors())
        except Exception as e:  # noqa: BLE001 - a plugin's mistake must not stop what collects
            self._say_once(f"cannot read the plugins' collectors: {type(e).__name__}: {e}; keeping theirs as they were")

    def snapshot(self) -> dict:
        """The instruments as the runtime record holds them."""
        with self._lock:
            return {n: {"kind": c.what, "target": c.target, "every_s": c.every_s, "timeout_s": c.timeout_s, "owner": c.owner,
                        "log": str(self._log_of(c)), "failures": self.failures[n], **self.health.get(n, {})}
                    for n, c in sorted(self.wanted.items())}

    def _record_health(self, now: float) -> None:
        """Write the instruments' health to the runtime record when it changed: at once when one
        was added, removed or failed, else at most every ``RECORD_EVERY_S``."""
        if not self._urgent and now - self._recorded_at < RECORD_EVERY_S:
            return
        snap = self.snapshot()
        if snap != self._recorded:
            try:
                runtime.update(self.project, lambda d: d.__setitem__("instruments", snap) if snap else d.pop("instruments", None))
                self._recorded = snap
            except OSError as e:
                self._say_once(f"cannot write the runtime record: {e}")
        self._recorded_at, self._urgent = now, False

    def tick(self, now: float | None = None) -> None:
        """Start the rounds that are due, and record the instruments' health."""
        self._read()
        self._record_health(time.time())
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
        at = time.time()
        if r.error:
            with self._lock:
                self.failures[c.name] += 1
                self.health.setdefault(c.name, {}).update(last_error=r.error, last_error_at=at)
                self._urgent = True
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
            with self._lock:
                h = self.health.setdefault(c.name, {})
                self._urgent = self._urgent or "last_write" not in h or h.get("points") != len(r.points)
                h.update(last_write=at, points=len(r.points))
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
        self._urgent = True
        self._record_health(time.time())
