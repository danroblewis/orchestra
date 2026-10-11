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


_detected: dict[str, int] = {}


def detect_host_slots(provider: str | None, configured: int, default: int = 2) -> int:
    """The number of model slots to allow. `configured` > 0 wins. Otherwise ask the Pi
    provider's server (llama.cpp's /props reports total_slots); fall back to `default`."""
    if configured and configured > 0:
        return configured
    key = provider or ""
    if key in _detected:
        return _detected[key]
    slots = default
    try:
        import json
        import urllib.request
        models = json.loads((Path.home() / ".pi" / "agent" / "models.json").read_text())
        base = ((models.get("providers") or {}).get(key) or {}).get("baseUrl", "")
        base = base.rstrip("/")
        if base.endswith("/v1"):
            base = base[:-3]
        if base:
            with urllib.request.urlopen(base + "/props", timeout=3) as r:
                props = json.loads(r.read())
            if int(props.get("total_slots") or 0) > 0:
                slots = int(props["total_slots"])
    except Exception:
        pass
    _detected[key] = slots
    return slots
