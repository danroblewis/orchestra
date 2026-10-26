"""The runtime record: which of Orchestra's own processes are running, in
``<state>/runtime.json``. The bootstrap host and the web server register themselves here; the
Core page reads it. Writes take the project's lock, so processes never clobber each other."""

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
