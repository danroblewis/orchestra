"""The launcher: the commands a project or a plugin asks ``orchestra run`` to keep running.

A project declares them in ``orchestra.toml``::

    [[machines]]
    name = "telemetry"                               # letters, digits, . _ -
    command = "python machines/telemetry.py"         # split like a shell would, not run by one; `python` is Orchestra's
    restart = "always"                               # always (the default) | on-failure | never
    stop_grace = 10                                  # seconds from SIGTERM to SIGKILL (default 10)

and a plugin in ``Plugin.processes`` (the same ``Process``). Each runs in the repository root
with ``ORCHESTRA_REPO`` (the root), ``ORCHESTRA_MACHINE_LOG`` (its log,
``<state>/logs/machines/<name>.log``, which gets its output) and ``ORCHESTRA_PROCESS`` (its name
here, ``<plugin>.<name>`` for a plugin's; a machine's announcement passes it on as ``process``,
``events.announcing``) set, and what the host adds (``env``:
the events endpoint's address and token, ``orchestra.endpoint``), in a process group of its own so
stopping it stops what it started: SIGTERM to the group, then SIGKILL after its stop grace
(``stop_grace``, ``STOP_GRACE_S`` unless given). One that exits is started again after a pause that doubles
with each quick exit (up to a minute); one that fails ``GIVE_UP_AFTER`` times in a row, each
within ``STABLE_S`` of starting, has spent its fast-crash budget: it is stopped and tried again on
the backoff schedule (``BACKOFF_SCHEDULE``: one minute, five, fifteen, then hourly) for as long as
the host runs, said in the host's log, the process's log and on the bus (``orchestra.process.gave_up``,
once per spent budget, with ``next_try``), and recorded as ``stopped after N crashes; next try at
<time>``. One that then stays up ``STABLE_S`` has its budget reset. A restart asked for in the
runtime record (``runtime.request_restart``, the Supervisor's) is carried out at the next tick, for
a process declared here, whatever its state: stopped if it runs (SIGTERM, then SIGKILL after its
grace), its crash budget and backoff reset, started again at once, the request cleared, and
``orchestra.process.restart_requested`` published (``by``, ``reason``). ``orchestra.toml`` (and the private overlay, ``orchestra.overlay``) is read again whenever it changes, so a
machine added by a merged commit starts without restarting the host, one removed stops, and one
whose command or restart changed is restarted (and a backing-off one tried at once); the plugins'
processes are asked for again then too, so a plugin's section added or removed starts or stops
them. A plugin's process that reads its settings once, when it starts, names them in
``config_keys`` (dotted keys of the merged configuration, ``["myplugin.upstream"]``): when the value
under any of them changes, it is restarted the same way, and one backing off is tried at once, so a
fixed setting reaches it without restarting the host. Every process is
in the runtime record under ``processes`` for the Core page. A plugin's processes are named
``<plugin>.<name>`` there and in their logs' names, so a project's ``[[machines]]`` never collide
with them.

Inside every command Orchestra runs, ``python`` and ``python3`` are the Python Orchestra runs in
(``orchestra.launcher_env``: ``child_env``, ``own_python``).

Orchestra starts commands and knows nothing else of them: a process is not a machine to it until
it publishes (AGENTS.md rules 1 and 2). ``ORCHESTRA_PROCESS`` is a name, not a machine: the launcher
never reads what a process announces."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import signal
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path

import psutil

from . import runtime
from .config import ConfigError, Project
from .events import PROCESS_ENV
from .launcher_env import child_env, own_python

RESTARTS = ("always", "on-failure", "never")
NAME = re.compile(r"^[A-Za-z0-9_.-]+$")
STABLE_S = 60.0          # a run this long is no crash: the pause and the count of failures start over
GIVE_UP_AFTER = 5        # failures in a row, each within STABLE_S of starting: the fast-crash budget
BACKOFF_MAX = 60.0
BACKOFF_SCHEDULE = (60.0, 300.0, 900.0, 3600.0)   # after the budget: the pauses before each next try; the last repeats
STOP_GRACE_S = 10.0      # after SIGTERM, before SIGKILL
LOG_MAX = 5_000_000


@dataclass
class Process:
    name: str
    command: str | list[str]
    restart: str = "always"
    owner: str = "project"         # "project", or the plugin that declared it
    stop_grace_s: float | None = None   # from SIGTERM to SIGKILL when stopping it; None: STOP_GRACE_S
    config_keys: list[str] = field(default_factory=list)   # dotted keys of the configuration it reads when it
                                                           # starts: a change under any of them restarts it

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
    if not isinstance(p.config_keys, list | tuple) or not all(isinstance(k, str) and k for k in p.config_keys):
        return f"{p.name}: config_keys must be a list of dotted keys, not {p.config_keys!r}"
    if p.stop_grace_s is not None and (isinstance(p.stop_grace_s, bool) or not isinstance(p.stop_grace_s, int | float)
                                       or p.stop_grace_s < 0):
        return f"{p.name}: stop_grace must be a number of seconds, not {p.stop_grace_s!r}"
    return None


def fingerprint(raw: dict, keys: list[str]) -> str:
    """A digest of the values under ``keys`` (dotted) in the configuration ``raw``; a key that is
    not there counts as absent, so its appearing or going changes the digest too."""
    if not keys:
        return ""
    picked = {}
    for k in keys:
        v: object = raw
        for part in str(k).split("."):
            v = v.get(part) if isinstance(v, dict) else None
        picked[str(k)] = v
    return hashlib.sha256(json.dumps(picked, sort_keys=True, default=str).encode()).hexdigest()


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
    state: str = "waiting"         # running | waiting | exited | backing_off (budget spent, tried on the schedule)
    start_at: float = 0.0          # while waiting: when to start
    code: int | None = None        # the last exit code (negative: killed by that signal)
    fingerprint: str = ""          # of the settings under its spec's config_keys when it was declared


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
    schedule: tuple[float, ...] = BACKOFF_SCHEDULE
    grace: float = STOP_GRACE_S
    runs: dict[str, _Run] = field(default_factory=dict)
    _mtime: tuple | None = None                   # the configuration's stamp last read
    _project: list[Process] = field(default_factory=list)
    _plugins: list[Process] = field(default_factory=list)
    _raw: dict = field(default_factory=dict)      # the merged configuration last read well
    _said: set[str] = field(default_factory=set)
    _recorded: dict | None = None

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
                self._raw = self.project.read_config().raw
                self._project = from_toml(self._raw)
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
        env = child_env({**self.env, "ORCHESTRA_REPO": str(self.project.repo_root), "ORCHESTRA_MACHINE_LOG": str(run.log),
                         PROCESS_ENV: run.spec.name, "PYTHONUNBUFFERED": "1"})
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
        self._tell("orchestra.process.started", {"name": run.spec.name, "pid": run.popen.pid,
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
            spent = run.failures - self.give_up_after             # tries on the schedule since the budget ran out
            delay = self.schedule[min(spent, len(self.schedule) - 1)]
            run.state, run.start_at = "backing_off", time.time() + delay
            run.restarts += 1
            self._note(run, f"exited with code {code}; {_stopped(run)} (in {delay:g} s; each of the last {run.failures} "
                            f"within {self.stable_s:g} s of starting)")
            self._tell("orchestra.process.exited", {"name": run.spec.name, "pid": pid, "code": code, "restart_in": delay})
            if spent == 0:
                self._tell("orchestra.process.gave_up", {"name": run.spec.name, "code": code, "failures": run.failures,
                                                         "next_try": run.start_at})
            return
        delay = min(self.backoff * 2 ** run.quick, BACKOFF_MAX) if restart else None
        if restart:
            run.state, run.start_at = "waiting", time.time() + delay
            run.restarts += 1
        else:
            run.state = "exited"
        self._note(run, f"exited with code {code} after {ran:.1f} s; " + (f"starting again in {delay:g} s" if restart else "not restarted"))
        self._tell("orchestra.process.exited", {"name": run.spec.name, "pid": pid, "code": code, "restart_in": delay})

    def _grace(self, p: Process) -> float:
        return self.grace if p.stop_grace_s is None else float(p.stop_grace_s)

    def _stop(self, runs: list[_Run], why: str) -> None:
        """Stop these processes and their groups: SIGTERM, then SIGKILL after each one's grace.
        Every process is killed first; only then is each exit published, each on its own, so a
        failing bus can neither leave a process running nor skip the record."""
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
        for r in live:
            self._note(r, f"stopped ({why})")
            self._tell("orchestra.process.exited", {"name": r.spec.name, "pid": r.popen.pid,
                                                    "code": r.popen.returncode, "restart_in": None})
        for r in runs:
            r.popen, r.state = None, "exited"

    def _tell(self, type_: str, data: dict) -> None:
        """Publish one of the launcher's events; a bus that fails is logged, never stops the launcher."""
        try:
            self.publish(type_, data)
        except Exception as e:  # noqa: BLE001 - the processes come first; the event is lost, and logged
            self.log(f"launcher: {type_} for {data.get('name')} not published: {type(e).__name__}: {e}")

    def tick(self) -> None:
        """Start what is declared and not running, restart what exited, stop what is no longer
        declared or was declared differently, and record it all."""
        wanted = self.wanted()
        prints = {n: fingerprint(self._raw, list(p.config_keys)) for n, p in wanted.items()}
        gone = [n for n, r in self.runs.items()
                if n not in wanted or not r.spec.same(wanted[n]) or r.fingerprint != prints[n]]
        if gone:
            self._stop([self.runs[n] for n in gone], "no longer declared as it was")
            for n in gone:
                del self.runs[n]
        requests = dict(runtime.read(self.project).get("restart_requests") or {})
        now = time.time()
        for name, spec in wanted.items():
            run = self.runs.get(name)
            if run is None:
                run = self.runs[name] = _Run(spec, self.project.logs_dir / "machines" / f"{name}.log",
                                             fingerprint=prints[name])
            run.spec = spec                                       # the owner may have changed
            if (req := requests.pop(name, None)) is not None:
                self._restart(run, req)
                continue
            if run.state == "running" and run.popen is not None and (code := run.popen.poll()) is not None:
                self._exited(run, code)
            elif run.state == "running" and run.failures and now - run.started >= self.stable_s:
                run.quick = run.failures = 0                      # it stayed up: its budget is whole again
            if run.state in ("waiting", "backing_off") and now >= run.start_at:
                self._start(run)
        for name, req in requests.items():                        # for nothing declared here: dropped, and said
            self.log(f"launcher: restart of {name} requested by {req.get('by')}: not declared here; dropped")
            self._clear_request(name, req)
        self._record()

    def _restart(self, run: _Run, req: dict) -> None:
        """Carry out a requested restart: stop it if it runs, reset its budget and pause, start it now."""
        by, reason = req.get("by"), req.get("reason")
        self._stop([run], f"restart requested by {by}")
        run.quick = run.failures = 0
        self._note(run, f"restart requested by {by}: {reason}")
        self._clear_request(run.spec.name, req)
        self._tell("orchestra.process.restart_requested", {"name": run.spec.name, "by": by, "reason": reason,
                                                            "owner": run.spec.owner})
        run.restarts += 1
        self._start(run)

    def _clear_request(self, name: str, req: dict) -> None:
        """Clear this request, and not one made since it was read."""
        def clear(d: dict) -> None:
            reqs = d.get("restart_requests") or {}
            if reqs.get(name) == req:
                del reqs[name]
            if not reqs:
                d.pop("restart_requests", None)
        runtime.update(self.project, clear)

    def stop_all(self) -> None:
        self._stop(list(self.runs.values()), "orchestra run stopping")
        self.runs.clear()
        self._record()

    def snapshot(self) -> dict:
        return {n: {"pid": r.popen.pid if r.popen else None, "since": r.started if r.popen else None,
                    "state": r.state, "restarts": r.restarts, "code": r.code, "owner": r.spec.owner,
                    "command": r.spec.argv(), "log": str(r.log), "stop_grace_s": self._grace(r.spec),
                    **({"crashes": r.failures, "next_try": r.start_at, "note": _stopped(r)} if r.state == "backing_off" else {})}
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


def _stopped(run: _Run) -> str:
    return f"stopped after {run.failures} crashes; next try at {datetime.fromtimestamp(run.start_at).strftime('%Y-%m-%d %H:%M:%S')}"


def _signal_group(pid: int, sig: int) -> None:
    try:
        os.killpg(pid, sig)
    except (ProcessLookupError, PermissionError):
        pass
