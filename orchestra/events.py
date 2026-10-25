"""Append-only event log plus in-process subscribers. SPEC.md section 6.5.

``Events`` is the facade the rest of Orchestra uses; the log itself is an ``EventBus``
(``orchestra.bus``): a JSONL file by default, or Redis Streams, a RabbitMQ stream or Kafka, chosen
by ``[events] url`` in ``orchestra.toml`` or the ``ORCHESTRA_EVENTS_URL`` environment variable.
Subscribers registered here hear only the events this process emits; other processes read the
log by offset."""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .bus import EventBus, open_bus
from .bus.file import FileBus
from .model import now

if TYPE_CHECKING:
    from .config import Project


class Events:
    def __init__(self, path: Path | None = None, *, bus: EventBus | None = None):
        if bus is None and path is None:
            raise ValueError("Events needs a file path or a bus")
        self.bus: EventBus = bus or FileBus(path)
        self.path = path
        self._subs: list[Callable[[dict], None]] = []

    @classmethod
    def for_project(cls, project: Project) -> Events:
        url = os.environ.get("ORCHESTRA_EVENTS_URL") or project.config.events_url
        return cls(project.events_file, bus=open_bus(url, project_key=project.key, file_path=project.events_file))

    def subscribe(self, fn: Callable[[dict], None]) -> None:
        self._subs.append(fn)

    def emit(self, type: str, **data: Any) -> dict:
        ev = {"ts": now(), "type": type, **data}
        self.bus.append(ev)
        for fn in list(self._subs):
            try:
                fn(ev)
            except Exception:
                pass
        return ev

    def read(self, since: int = 0, limit: int = 500) -> tuple[list[dict], int]:
        """Return (events, next_offset): the last ``limit`` events after ``since``, and the offset
        to read from next."""
        return self.bus.read(since, limit)

    def end(self) -> int:
        return self.bus.end()

    def close(self) -> None:
        self.bus.close()
