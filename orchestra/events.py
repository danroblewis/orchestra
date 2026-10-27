"""The events facade over the event bus.

``Events`` is what the rest of Orchestra uses; the log itself is an ``EventBus``
(``orchestra.bus``): a JSONL file by default, or Redis Streams, a RabbitMQ stream or Kafka, chosen
by ``[events] url`` in ``orchestra.toml`` or the ``ORCHESTRA_EVENTS_URL`` environment variable.

Every event published now carries the **CloudEvents** envelope (``specversion`` 1.0):

- ``id``, ``type``, ``source`` (the machine that emitted it, or ``<machine>/<instance>`` for one
  of several instances of a machine), ``time`` (RFC 3339);
- optional ``subject`` (what it is about), ``correlationid`` and ``causationid`` (extensions);
- ``data``: the payload, which belongs to the machines that use it; Orchestra never reads it.

Events written before the envelope (flat dicts with ``ts`` and ``type``) stay readable:
``event_time`` and ``event_source`` read either shape."""

from __future__ import annotations

import os
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .bus import EventBus, open_bus
from .bus.file import FileBus

if TYPE_CHECKING:
    from .config import Project

HOST = "orchestra-host"


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


def envelope(type: str, source: str, data: Any = None, *, subject: str | None = None,
             correlationid: str | None = None, causationid: str | None = None,
             time: str | None = None, id: str | None = None) -> dict:
    """A CloudEvents 1.0 event, as a dict. ``time`` and ``id`` are for an event brought in from
    another system (a sync): it keeps the time it happened there, and an id stable across
    re-imports; otherwise now and a fresh id."""
    ev: dict[str, Any] = {"specversion": "1.0", "id": id or uuid.uuid4().hex, "type": type, "source": source, "time": time or now()}
    if subject is not None:
        ev["subject"] = subject
    if correlationid is not None:
        ev["correlationid"] = correlationid
    if causationid is not None:
        ev["causationid"] = causationid
    if data is not None:
        ev["datacontenttype"] = "application/json"
        ev["data"] = data
    return ev


def event_time(ev: dict) -> float | None:
    """Unix seconds of an event, from ``time`` (CloudEvents) or ``ts`` (older events)."""
    raw = ev.get("time") or ev.get("ts")
    try:
        return datetime.fromisoformat(raw).timestamp() if raw else None
    except (TypeError, ValueError):
        return None


def event_source(ev: dict) -> str | None:
    """The machine instance that emitted an event, when the event says so (CloudEvents ``source``)."""
    return ev.get("source")


def for_an_instrument(ev: dict) -> bool:
    """An announcement the host made on an instrument's behalf before 2026-10-27
    (``orchestra.machine.started`` with ``data.collector``): an instrument is not a machine
    (AGENTS.md rules 2 and 7), so this is no machine's event, wherever machines are listed."""
    return ev.get("type") == "orchestra.machine.started" and isinstance(ev.get("data"), dict) and "collector" in ev["data"]


def machine_and_instance(source: str | None) -> tuple[str | None, str | None]:
    """A source names a machine, or one instance of it as ``<machine>/<instance>`` (``baker/2``:
    the second of several bakers, all one machine)."""
    if not source:
        return None, None
    machine, _, instance = source.partition("/")
    return machine, instance or None


class Events:
    def __init__(self, path: Path | None = None, *, bus: EventBus | None = None, source: str = HOST):
        if bus is None and path is None:
            raise ValueError("Events needs a file path or a bus")
        self.bus: EventBus = bus or FileBus(path)
        self.path = path
        self.source = source
        self._subs: list[Callable[[dict], None]] = []

    @classmethod
    def for_project(cls, project: Project, source: str = HOST) -> Events:
        url = os.environ.get("ORCHESTRA_EVENTS_URL") or project.config.events_url
        return cls(project.events_file, bus=open_bus(url, project_key=project.key, file_path=project.events_file),
                   source=source)

    def subscribe(self, fn: Callable[[dict], None]) -> None:
        """Hear the events this process publishes (other processes read the bus by offset)."""
        self._subs.append(fn)

    def publish(self, type: str, data: Any = None, *, source: str | None = None, **ext: Any) -> dict:
        """Publish one event with the CloudEvents envelope; ``ext`` takes subject, correlationid,
        causationid, and for an event brought in from another system its time and id."""
        ev = envelope(type, source or self.source, data, **ext)
        self.bus.append(ev)
        for fn in list(self._subs):
            try:
                fn(ev)
            except Exception:  # noqa: BLE001, S110 - a subscriber never breaks the publisher
                pass
        return ev

    def emit(self, type: str, **data: Any) -> dict:
        """Publish an event from this process's own source, its keyword arguments as the data."""
        return self.publish(type, data or None)

    def read(self, since: int = 0, limit: int = 500) -> tuple[list[dict], int]:
        """Return (events, next_offset): the last ``limit`` events after ``since``, and the offset
        to read from next."""
        return self.bus.read(since, limit)

    def after(self, offset: int) -> tuple[list[dict], int]:
        """Return (events, next_offset): every event after ``offset``, in order, and the offset
        to read from next. Unlike ``read`` nothing is cut off, even when events arrive while it
        reads; nothing new is an empty list and the same offset. It reads through ``read``, so a
        subclass that shapes what ``read`` returns shapes this too."""
        room = max(self.end() - offset, 1)
        while True:
            evs, nxt = self.read(offset, room)
            if nxt - offset <= room:
                return evs, nxt
            room = nxt - offset                  # more arrived between end() and the read

    def end(self) -> int:
        return self.bus.end()

    def close(self) -> None:
        self.bus.close()
