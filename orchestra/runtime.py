"""The runtime record: which of Orchestra's own processes are running, in
``<state>/runtime.json``. The bootstrap hosts and the web server register themselves here; the
Core page reads it. Writes take the project's lock, so processes never clobber each other.

A process is recorded as ``{"pid", "since"}``, ``since`` being the process's own create time, so a
record whose pid the system has since given to another process is not mistaken for it
(``holds``). The keys:

- ``hosts``: every running ``orchestra run``, by pid; each adds and removes only its own entry;
- ``launcher``: the one host that launches the project's processes. It is taken under the lock
  only when nobody holds it or its holder is dead, and cleared only by its holder;
- ``processes``: what that host launched (``orchestra.launcher``);
- ``restart_requests``: by process name, ``{"by", "reason", "requested_at"}``: a restart asked of
  the launching host (``request_restart``), which it carries out and clears at its next tick;
- ``discovery_next``: when the discovering host starts its next discovery (``{"at", "pid", "since"}``),
  so the Dynamics page can say when the model is looked for again."""

from __future__ import annotations

import fcntl
import json
import os
import time
from collections.abc import Callable
from typing import Any

import psutil

from .config import Project


def alive(pid) -> bool:
    """A recorded pid proves liveness only if that process exists and is not a zombie."""
    try:
        return bool(pid) and psutil.Process(int(pid)).status() != psutil.STATUS_ZOMBIE
    except (psutil.NoSuchProcess, psutil.AccessDenied, ValueError, TypeError):
        return False


def me() -> dict:
    """This process, as the record holds a process."""
    return {"pid": os.getpid(), "since": psutil.Process().create_time()}


def holds(rec) -> bool:
    """Whether the process a record names still runs: its pid exists, is no zombie, and was
    created when the record says (within a second), so a reused pid does not count."""
    try:
        p = psutil.Process(int(rec["pid"]))
        return p.status() != psutil.STATUS_ZOMBIE and abs(p.create_time() - float(rec["since"])) < 1.0
    except (psutil.NoSuchProcess, psutil.AccessDenied, ValueError, TypeError, KeyError):
        return False


def launcher(record: dict) -> dict | None:
    """The live launching host in a read record, or None."""
    rec = record.get("launcher")
    return rec if isinstance(rec, dict) and holds(rec) else None


def hosts(record: dict) -> list[dict]:
    """The live hosts in a read record."""
    return [r for r in (record.get("hosts") or {}).values() if isinstance(r, dict) and holds(r)]


def read(project: Project) -> dict:
    try:
        return json.loads(project.runtime_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def update(project: Project, fn: Callable[[dict], Any]) -> Any:
    """Apply ``fn`` to the record under the lock and write it back; returns what ``fn`` returns."""
    project.state_dir.mkdir(parents=True, exist_ok=True)
    with project.lock_file.open("a+") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            data = read(project)
            out = fn(data)
            tmp = project.runtime_file.with_name(f".runtime.{os.getpid()}.tmp")
            tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
            os.replace(tmp, project.runtime_file)
            return out
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def request_restart(project: Project, name: str, *, by: str, reason: str) -> dict:
    """Ask the launching host to restart the process it recorded as ``name``: recorded under
    ``restart_requests`` (``by``, ``reason``, ``requested_at``), which the launcher reads at its
    next tick (``orchestra.launcher``). Returns the request; raises ``ValueError`` with the reason
    when it is refused: no host launches this project's processes, or none is named ``name``.
    The Supervisor's way to act on a process (AGENTS.md rule 9); a later request replaces one
    still pending."""
    if not isinstance(name, str) or not name:
        raise ValueError("a restart names the process to restart")

    def put(d: dict) -> dict:
        if launcher(d) is None:
            raise ValueError("no orchestra run launches this project's processes; nothing to restart")
        known = d.get("processes") or {}
        if name not in known:
            raise ValueError(f"no process named {name!r}; the host keeps " + (", ".join(sorted(known)) or "none"))
        req = {"by": str(by), "reason": str(reason), "requested_at": time.time()}
        d.setdefault("restart_requests", {})[name] = req
        return {"name": name, **req}

    return update(project, put)
