"""The runtime record: which of Orchestra's own processes are running, in
``<state>/runtime.json``. The bootstrap hosts and the web server register themselves here; the
Core page reads it. Writes take the project's lock, so processes never clobber each other.

A process is recorded as ``{"pid", "since"}``, ``since`` being the process's own create time, so a
record whose pid the system has since given to another process is not mistaken for it
(``holds``). The keys:

- ``hosts``: every running ``orchestra run``, by pid; each adds and removes only its own entry;
- ``launcher``: the one host that launches the project's processes. It is taken under the lock
  only when nobody holds it or its holder is dead, and cleared only by its holder;
- ``processes``: what that host launched (``orchestra.launcher``)."""

from __future__ import annotations

import fcntl
import json
import os
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
