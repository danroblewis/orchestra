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
``event_time`` reads either shape."""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .bus import EventBus, open_bus
from .bus.file import FileBus

if TYPE_CHECKING:
    from .config import Project

HOST = "orchestra-host"


def utc_time(t: datetime | str | float) -> str:
    """An envelope's ``time`` in its one format: UTC, to the millisecond, ending in ``Z``
    (``2026-10-27T18:58:31.043Z``), whatever it was given: a datetime, an ISO 8601 string with an
    offset, ``Z`` or ``+00:00``, or Unix seconds. A datetime or string with no zone is taken as UTC."""
    if isinstance(t, bool):
        raise TypeError("time: a datetime, an ISO 8601 string or Unix seconds")
    if isinstance(t, int | float):
        d = datetime.fromtimestamp(t, UTC)
    elif isinstance(t, datetime):
        d = t
    elif isinstance(t, str):
        try:
            d = datetime.fromisoformat(t.strip())
        except ValueError:
            raise ValueError(f"time {t!r} is not ISO 8601 (2026-10-27T18:58:31.043Z)") from None
    else:
        raise TypeError("time: a datetime, an ISO 8601 string or Unix seconds")
    d = d.replace(tzinfo=UTC) if d.tzinfo is None else d.astimezone(UTC)
    return d.strftime("%Y-%m-%dT%H:%M:%S.") + f"{d.microsecond // 1000:03d}Z"


def now() -> str:
    return utc_time(datetime.now(UTC))


def envelope(type: str, source: str, data: Any = None, *, subject: str | None = None,
             correlationid: str | None = None, causationid: str | None = None,
             time: datetime | str | float | None = None, id: str | None = None) -> dict:
    """A CloudEvents 1.0 event, as a dict. ``time`` and ``id`` are for an event brought in from
    another system (a sync): it keeps the time it happened there, and an id stable across
    re-imports; otherwise now and a fresh id. Every ``time`` is written in one format, UTC ending
    in ``Z`` (``utc_time``), whatever the caller passed."""
    ev: dict[str, Any] = {"specversion": "1.0", "id": id or uuid.uuid4().hex, "type": type, "source": source, "time": now() if time is None else utc_time(time)}
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


def for_an_instrument(ev: dict) -> bool:
    """An announcement the host made on an instrument's behalf before 2026-10-27
    (``orchestra.machine.started`` with ``data.collector``): an instrument is not a machine
    (AGENTS.md rules 2 and 7), so this is no machine's event, wherever machines are listed."""
    return ev.get("type") == "orchestra.machine.started" and isinstance(ev.get("data"), dict) and "collector" in ev["data"]


ANNOUNCEMENT = "orchestra.machine.started"
ANNOUNCED_TEXT = ("mode", "kind", "log", "package", "name", "group", "team")   # each a string when present


def announcement(ev: dict) -> dict:
    """The data of an ``orchestra.machine.started`` as Orchestra reads it (AGENTS.md rules 2 and
    3): an object, anything else read as empty, and its ``listens_for`` only the strings of a list.
    The endpoint refuses other shapes (``endpoint.validate``); this keeps a bad one already on the
    bus, or written through the library, from breaking a reader."""
    d = ev.get("data")
    d = dict(d) if isinstance(d, dict) else {}
    subs = d.get("listens_for")
    d["listens_for"] = [t for t in subs if isinstance(t, str)] if isinstance(subs, list) else []
    return d


def machine_and_instance(source: str | None) -> tuple[str | None, str | None]:
    """A source names a machine, or one instance of it as ``<machine>/<instance>`` (``baker/2``:
    the second of several bakers, all one machine)."""
    if not isinstance(source, str) or not source:
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

    @classmethod
    def for_project(cls, project: Project, source: str = HOST) -> Events:
        url = os.environ.get("ORCHESTRA_EVENTS_URL") or project.config.events_url
        return cls(project.events_file, bus=open_bus(url, project_key=project.key, file_path=project.events_file),
                   source=source)

    def publish(self, type: str, data: Any = None, *, source: str | None = None, **ext: Any) -> dict:
        """Publish one event with the CloudEvents envelope; ``ext`` takes subject, correlationid,
        causationid, and for an event brought in from another system its time and id."""
        ev = envelope(type, source or self.source, data, **ext)
        self.bus.append(ev)
        return ev

    def emit(self, type: str, **data: Any) -> dict:
        """Publish an event from this process's own source, its keyword arguments as the data."""
        return self.publish(type, data or None)

    def read(self, since: int = 0, limit: int = 500) -> tuple[list[dict], int]:
        """Return (events, next_offset): the last ``limit`` events after ``since``, and the offset
        to read from next."""
        return self.bus.read(since, limit)

    def page(self, since: int = 0, limit: int = 500) -> tuple[list[dict], int]:
        """Return (events, next_offset): the events at the offsets after ``since`` up to
        ``min(since + limit, end)``, in order, and that bound to read from next, whatever was
        skipped there (``EventBus.page``). A loop on it from 0 reads every event once, each page
        bounded."""
        return self.bus.page(since, limit)

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
