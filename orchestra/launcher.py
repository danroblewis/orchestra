"""The launcher: the commands a project or a plugin asks ``orchestra run`` to keep running.

A project declares them in ``orchestra.toml``::

    [[machines]]
    name = "telemetry"                               # letters, digits, . _ -
    command = "python machines/telemetry.py"         # split like a shell would, not run by one; `python` is Orchestra's
    restart = "always"                               # always (the default) | on-failure | never
    stop_grace = 10                                  # seconds from SIGTERM to SIGKILL (default 10)

and a plugin in ``Plugin.processes`` (the same ``Process``). Each runs in the repository root
with ``ORCHESTRA_REPO`` (the root) and ``ORCHESTRA_MACHINE_LOG`` (its log,
``<state>/logs/machines/<name>.log``, which gets its output) set, and what the host adds (``env``:
the events endpoint's address and token, ``orchestra.endpoint``), in a process group of its own so
stopping it stops what it started: SIGTERM to the group, then SIGKILL after its stop grace
(``stop_grace``, ``STOP_GRACE_S`` unless given). One that exits is started again after a pause that doubles
with each quick exit (up to a minute); one that fails ``GIVE_UP_AFTER`` times in a row, each
within ``STABLE_S`` of starting, is given up on, in the host's log, the process's log and on the
bus (``orchestra.process.gave_up``). ``orchestra.toml`` (and the private overlay, ``orchestra.overlay``) is read again whenever it changes, so a
machine added by a merged commit starts without restarting the host, one removed stops, and one
whose command or restart changed is restarted (and a given-up one tried again); the plugins'
processes are asked for again then too, so a plugin's section added or removed starts or stops
them. Every process is
in the runtime record under ``processes`` for the Core page. A plugin's processes are named
``<plugin>.<name>`` there and in their logs' names, so a project's ``[[machines]]`` never collide
with them.

A command whose first word is ``python`` or ``python3`` runs with the Python Orchestra runs in
(``sys.executable``, ``own_python``), so a plugin's modules and Orchestra's own are importable
whatever is first on the PATH; any other interpreter is named by its path (``.venv/bin/python``) or
run through ``uv run python``. ``[[collect]]`` commands follow the same rule.

Orchestra starts commands and knows nothing else of them: a process is not a machine to it until
it publishes (AGENTS.md rules 1 and 2)."""

from __future__ import annotations

import os
import re
import shlex
import signal
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path

import psutil

from . import runtime
from .config import ConfigError, Project

RESTARTS = ("always", "on-failure", "never")
NAME = re.compile(r"^[A-Za-z0-9_.-]+$")
STABLE_S = 60.0          # a run this long is no crash: the pause and the count of failures start over
GIVE_UP_AFTER = 5        # failures in a row, each within STABLE_S of starting
BACKOFF_MAX = 60.0
STOP_GRACE_S = 10.0      # after SIGTERM, before SIGKILL
LOG_MAX = 5_000_000
PYTHONS = ("python", "python3")   # a command's first word that means the Python Orchestra runs in


def own_python(argv: list[str]) -> list[str]:
    """``argv`` with a first word of ``python`` or ``python3`` replaced by the Python Orchestra runs in,
    so the command imports what Orchestra can (its plugins, ``orchestra`` itself) rather than
    whatever Python is first on the PATH (often none, or another one)."""
    if argv and argv[0] in PYTHONS and sys.executable:
        return [sys.executable, *argv[1:]]
    return argv


@dataclass
class Process:
    name: str
    command: str | list[str]
    restart: str = "always"
    owner: str = "project"         # "project", or the plugin that declared it
    stop_grace_s: float | None = None   # from SIGTERM to SIGKILL when stopping it; None: STOP_GRACE_S

    def argv(self) -> list[str]:
        return own_python(shlex.split(self.command) if isinstance(self.command, str) else [str(a) for a in self.command])

    def same(self, other: Process) -> bool:
        return self.argv() == other.argv() and self.restart == other.restart


def check(p: Process) -> str | None:
    """Why ``p`` cannot be run, or None."""
    if not isinstance(p.name, str) or not NAME.match(p.name):
        return f"bad name {p.name!r}: use letters, digits, '.', '_' and '-'"
    try:
        if not p.argv():
            return f"{p.name}: empty command"
    except (ValueError, TypeError) as e:
        return f"{p.name}: bad command: {e}"
    if p.restart not in RESTARTS:
        return f"{p.name}: restart must be one of {', '.join(RESTARTS)}, not {p.restart!r}"
    if p.stop_grace_s is not None and (isinstance(p.stop_grace_s, bool) or not isinstance(p.stop_grace_s, int | float)
                                       or p.stop_grace_s < 0):
        return f"{p.name}: stop_grace must be a number of seconds, not {p.stop_grace_s!r}"
    return None


def from_toml(raw: dict) -> list[Process]:
    """The ``[[machines]]`` of a parsed ``orchestra.toml``."""
    entries = raw.get("machines") or []
    if not isinstance(entries, list):
        raise TypeError("machines must be an array of tables: write each one as [[machines]]")
    out = []
    for i, m in enumerate(entries):
        if not isinstance(m, dict):
            raise TypeError(f"[[machines]] entry {i + 1} is not a table")
        out.append(Process(name=m.get("name"), command=m.get("command") or "", restart=m.get("restart", "always"),
                           stop_grace_s=m.get("stop_grace")))
    return out


@dataclass
class _Run:
    spec: Process
    log: Path
    popen: subprocess.Popen | None = None
    started: float = 0.0           # when the current run began (the process's own create time)
    quick: int = 0                 # exits in a row within STABLE_S of starting
    failures: int = 0              # of those, the ones that failed
    restarts: int = 0
    state: str = "waiting"         # running | waiting | exited | gave_up
    start_at: float = 0.0          # while waiting: when to start
    code: int | None = None        # the last exit code (negative: killed by that signal)


@dataclass
class Launcher:
    project: Project
    publish: Callable[[str, dict], object]        # Events.publish: the host's own events
    log: Callable[[str], None]                    # the host's log
    plugin_processes: list[Process] | Callable[[], list[Process]] = field(default_factory=list)   # a callable is asked
                                                                     # again whenever orchestra.toml changes
    env: dict[str, str] = field(default_factory=dict)  # added to every process's environment
    backoff: float = 1.0
    stable_s: float = STABLE_S
    give_up_after: int = GIVE_UP_AFTER
    grace: float = STOP_GRACE_S
    runs: dict[str, _Run] = field(default_factory=dict)
    _mtime: tuple | None = None                   # the configuration's stamp last read
    _project: list[Process] = field(default_factory=list)
    _plugins: list[Process] = field(default_factory=list)
    _said: set[str] = field(default_factory=set)
    _recorded: dict | None = None

    # ---- what should run ----
    def _say_once(self, msg: str) -> None:
        if msg not in self._said:
            self._said.add(msg)
            self.log(f"launcher: {msg}")

    def _declared(self) -> tuple[list[Process], list[Process]]:
        """The project's ``[[machines]]`` and the plugins' processes, read again only when
        configuration changed (orchestra.toml or the private overlay; a plugin's processes may depend
        on its sections there). What fails to read leaves the last good list standing."""
        if not callable(self.plugin_processes):
            self._plugins = list(self.plugin_processes)
        stamp = self.project.config_stamp()
        if stamp[0] is None:
            self._say_once(f"cannot read {self.project.config_file.name}: it is not there; keeping what runs")
            return self._project, self._plugins
        if stamp != self._mtime:
            self._mtime = stamp
            try:
                self._project = from_toml(self.project.read_config().raw)
            except (OSError, ValueError, TypeError, ConfigError) as e:
                self._say_once(f"cannot read the configuration: {type(e).__name__}: {e}; keeping what runs")
            if callable(self.plugin_processes):
                try:
                    self._plugins = list(self.plugin_processes())
                except Exception as e:  # noqa: BLE001 - a plugin's mistake must not stop what runs
                    self._say_once(f"cannot read the plugins' processes: {type(e).__name__}: {e}; keeping what runs")
        return self._project, self._plugins

    def wanted(self) -> dict[str, Process]:
        """What should run, by name. A plugin's processes are named ``<plugin>.<name>``, so a
        project's never takes their place; a project name in a plugin's ``<plugin>.`` is refused."""
        out: dict[str, Process] = {}
        project, plugin = self._declared()
        plugins = {p.owner for p in plugin}
        for p in [*project, *plugin]:
            if p.owner != "project":
                p = replace(p, name=f"{p.owner}.{p.name}")
            elif isinstance(p.name, str) and (taken := next((o for o in plugins if p.name.startswith(f"{o}.")), None)):
                self._say_once(f"project: {p.name!r} has the form {taken}.<name>, kept for the plugin {taken}'s processes; not started")
                continue
            if (why := check(p)) is not None:
                self._say_once(f"{p.owner}: {why}; not started")
            elif p.name in out:
                self._say_once(f"{p.owner} declares {p.name!r}, which {out[p.name].owner} declared first; not started")
            else:
                out[p.name] = p
        return out

    # ---- one process ----
    def _note(self, run: _Run, msg: str) -> None:
        self.log(f"launcher: {run.spec.name}: {msg}")
        try:
            with run.log.open("a", encoding="utf-8") as f:
                f.write(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} [orchestra] {msg}\n")
        except OSError:
            pass

    def _start(self, run: _Run) -> None:
        run.log.parent.mkdir(parents=True, exist_ok=True)
        if run.log.exists() and run.log.stat().st_size > LOG_MAX:
            run.log.replace(run.log.with_suffix(".log.1"))
        argv = run.spec.argv()
        env = {**os.environ, **self.env, "ORCHESTRA_REPO": str(self.project.repo_root), "ORCHESTRA_MACHINE_LOG": str(run.log),
               "PYTHONUNBUFFERED": "1"}
        try:
            with run.log.open("ab") as out:
                run.popen = subprocess.Popen(argv, cwd=self.project.repo_root, env=env, stdin=subprocess.DEVNULL,
                                             stdout=out, stderr=subprocess.STDOUT, start_new_session=True)
        except OSError as e:
            self._note(run, f"cannot start `{shlex.join(argv)}`: {type(e).__name__}: {e}")
            run.started = time.time()
            self._exited(run, 127)
            return
        try:
            run.started = psutil.Process(run.popen.pid).create_time()
        except psutil.Error:
            run.started = time.time()
        run.state = "running"
        self._note(run, f"started `{shlex.join(argv)}` (pid {run.popen.pid})")
        self.publish("orchestra.process.started", {"name": run.spec.name, "pid": run.popen.pid,
                                                   "command": argv, "owner": run.spec.owner})

    def _exited(self, run: _Run, code: int) -> None:
        ran = time.time() - run.started
        pid = run.popen.pid if run.popen else None
        if run.popen is not None:
            _signal_group(run.popen.pid, signal.SIGKILL)       # what it started goes with it
        run.popen, run.code = None, code
        if ran >= self.stable_s:
            run.quick = run.failures = 0
        else:
            run.quick += 1
            run.failures += code != 0
        restart = run.spec.restart == "always" or (run.spec.restart == "on-failure" and code != 0)
        if restart and run.failures >= self.give_up_after:
            run.state = "gave_up"
            self._note(run, f"exited with code {code}; gave up after {run.failures} failures in a row, each within "
                            f"{self.stable_s:g} s of starting (fix it and change its entry, or restart orchestra run)")
            self.publish("orchestra.process.exited", {"name": run.spec.name, "pid": pid, "code": code, "restart_in": None})
            self.publish("orchestra.process.gave_up", {"name": run.spec.name, "code": code, "failures": run.failures})
            return
        delay = min(self.backoff * 2 ** run.quick, BACKOFF_MAX) if restart else None
        if restart:
            run.state, run.start_at = "waiting", time.time() + delay
            run.restarts += 1
        else:
            run.state = "exited"
        self._note(run, f"exited with code {code} after {ran:.1f} s; " + (f"starting again in {delay:g} s" if restart else "not restarted"))
        self.publish("orchestra.process.exited", {"name": run.spec.name, "pid": pid, "code": code, "restart_in": delay})

    def _grace(self, p: Process) -> float:
        return self.grace if p.stop_grace_s is None else float(p.stop_grace_s)

    def _stop(self, runs: list[_Run], why: str) -> None:
        """Stop these processes and their groups: SIGTERM, then SIGKILL after each one's grace."""
        live = [r for r in runs if r.popen is not None and r.popen.poll() is None]
        for r in live:
            _signal_group(r.popen.pid, signal.SIGTERM)
        t0 = time.time()
        for r in sorted(live, key=lambda r: self._grace(r.spec)):
            try:
                r.popen.wait(timeout=max(0.0, t0 + self._grace(r.spec) - time.time()))
            except subprocess.TimeoutExpired:
                pass
            _signal_group(r.popen.pid, signal.SIGKILL)
            r.popen.wait()
            self._note(r, f"stopped ({why})")
            self.publish("orchestra.process.exited", {"name": r.spec.name, "pid": r.popen.pid,
                                                      "code": r.popen.returncode, "restart_in": None})
        for r in runs:
            r.popen, r.state = None, "exited"

    # ---- the tick ----
    def tick(self) -> None:
        """Start what is declared and not running, restart what exited, stop what is no longer
        declared or was declared differently, and record it all."""
        wanted = self.wanted()
        gone = [n for n, r in self.runs.items() if n not in wanted or not r.spec.same(wanted[n])]
        if gone:
            self._stop([self.runs[n] for n in gone], "no longer declared as it was")
            for n in gone:
                del self.runs[n]
        now = time.time()
        for name, spec in wanted.items():
            run = self.runs.get(name)
            if run is None:
                run = self.runs[name] = _Run(spec, self.project.logs_dir / "machines" / f"{name}.log")
            run.spec = spec                                       # the owner may have changed
            if run.state == "running" and run.popen is not None and (code := run.popen.poll()) is not None:
                self._exited(run, code)
            if run.state == "waiting" and now >= run.start_at:
                self._start(run)
        self._record()

    def stop_all(self) -> None:
        self._stop(list(self.runs.values()), "orchestra run stopping")
        self.runs.clear()
        self._record()

    # ---- the runtime record ----
    def snapshot(self) -> dict:
        return {n: {"pid": r.popen.pid if r.popen else None, "since": r.started if r.popen else None,
                    "state": r.state, "restarts": r.restarts, "code": r.code, "owner": r.spec.owner,
                    "command": r.spec.argv(), "log": str(r.log), "stop_grace_s": self._grace(r.spec)}
                for n, r in sorted(self.runs.items())}

    def _record(self) -> None:
        snap = self.snapshot()
        if snap != self._recorded:
            runtime.update(self.project, lambda d: d.__setitem__("processes", snap) if snap else d.pop("processes", None))
            self._recorded = snap

    def reap_orphans(self) -> None:
        """Stop what a previous host, killed without stopping its processes, left running: each
        recorded process that is still the same process (its create time matches). It waits for
        them to exit, up to each one's grace, and kills what remains, so no replacement started
        after it overlaps one."""
        reaped: list[tuple[psutil.Process, float]] = []
        for name, rec in (runtime.read(self.project).get("processes") or {}).items():
            pid, since = rec.get("pid"), rec.get("since")
            try:
                if pid and since and abs((p := psutil.Process(pid)).create_time() - since) < 1.0:
                    _signal_group(pid, signal.SIGTERM)
                    reaped.append((p, float(rec.get("stop_grace_s") or self.grace)))
                    self.log(f"launcher: stopping {name} (pid {pid}), left running by a previous orchestra run")
            except psutil.Error:
                pass
        t0 = time.time()
        for p, grace in sorted(reaped, key=lambda x: x[1]):
            try:
                p.wait(timeout=max(0.0, t0 + grace - time.time()))
            except psutil.TimeoutExpired:
                self.log(f"launcher: pid {p.pid} did not stop within {grace:g} s; killed")
            except psutil.Error:
                pass
            _signal_group(p.pid, signal.SIGKILL)                     # and whatever it started


def _signal_group(pid: int, sig: int) -> None:
    try:
        os.killpg(pid, sig)
    except (ProcessLookupError, PermissionError):
        pass
