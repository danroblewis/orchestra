"""A host-wide limit on concurrent model turns.

A local model server has a fixed number of slots; more simultaneous turns than that
just queue inside the server while every agent's turn clock runs. Every Orchestra
process on the machine (each project's loop, chat, staging instances) shares these
file locks, so total in-flight turns never exceed the configured count."""

from __future__ import annotations

import fcntl
import os
import time
from contextlib import contextmanager
from pathlib import Path


def slots_dir() -> Path:
    d = Path(os.environ.get("ORCHESTRATOR_HOME") or Path.home() / ".orchestrator") / "host" / "slots"
    d.mkdir(parents=True, exist_ok=True)
    return d


@contextmanager
def turn_slot(max_slots: int, poll: float = 0.5):
    """Hold one of `max_slots` host slots for the duration of the block. Blocks until free."""
    if max_slots <= 0:
        yield None
        return
    d = slots_dir()
    while True:
        for i in range(max_slots):
            fh = (d / f"{i}.lock").open("a+")
            try:
                fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                fh.close()
                continue
            try:
                yield i
            finally:
                fcntl.flock(fh, fcntl.LOCK_UN)
                fh.close()
            return
        time.sleep(poll)


def slots_in_use(max_slots: int) -> int:
    d = slots_dir()
    busy = 0
    for i in range(max_slots):
        fh = (d / f"{i}.lock").open("a+")
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(fh, fcntl.LOCK_UN)
        except OSError:
            busy += 1
        finally:
            fh.close()
    return busy


def host_slots(configured: int) -> int:
    """The in-flight turn limit, or 0 for none. Orchestra does not infer the model server's
    capacity; a limit exists only when the operator sets one."""
    return configured if configured and configured > 0 else 0
