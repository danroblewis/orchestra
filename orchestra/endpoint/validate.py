"""What ``POST /events`` accepts: one event's fields, checked before anything is written.

The body is a JSON object with ``type`` and ``source`` and, optionally, ``data`` (any JSON),
``subject``, ``time``, ``id``, ``correlationid`` and ``causationid``. A structured-mode CloudEvent
is the same object with ``specversion`` ("1.0") and ``datacontenttype`` ("application/json"),
which are checked and then left to ``orchestra.events.envelope`` to write. Anything else is
refused by name, so a misspelt field is not silently lost.

Orchestra's own types (``orchestra.*``) are the host's to publish, except the announcements a
machine makes of itself (``orchestra.machine.started`` and the older
``orchestra.machine.subscribed``) and the predictions a machine makes of its changes
(``orchestra.prediction.made``, ``sd.predictions``). The source ``orchestra-host`` is the host's own. ``data`` is
never read (AGENTS.md rule 3): only its size counts, through the body's."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from typing import Any

from ..events import HOST

MAX_BODY = 1_000_000            # bytes of one request's body
MAX_TYPE = 256
MAX_SOURCE = 256
MAX_TEXT = 1024                 # subject, correlationid, causationid
MAX_ID = 256

ANNOUNCEMENTS = ("orchestra.machine.started", "orchestra.machine.subscribed")
STATEMENTS = ("orchestra.prediction.made",)          # what a machine says of its own changes (sd.predictions)
MACHINES_MAY = (*ANNOUNCEMENTS, *STATEMENTS)
OPTIONAL_TEXT = ("subject", "correlationid", "causationid")
ACCEPTED = {"type", "source", "data", "time", "id", "specversion", "datacontenttype", *OPTIONAL_TEXT}

TYPE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")
SOURCE_PART = r"[A-Za-z0-9][A-Za-z0-9_.:@-]*"
SOURCE = re.compile(rf"^{SOURCE_PART}(/{SOURCE_PART})?$")
PRINTABLE = re.compile(r"^[\x21-\x7e]+$")


class Invalid(ValueError):
    """A request Orchestra refuses, with the HTTP status to answer it with."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def parse(body: bytes) -> dict:
    """The request's JSON object."""
    if len(body) > MAX_BODY:
        raise Invalid(f"the body is {len(body)} bytes; at most {MAX_BODY}", 413)
    try:
        obj = json.loads(body)
    except (UnicodeDecodeError, ValueError) as e:
        raise Invalid(f"the body is not JSON: {e}") from None
    if not isinstance(obj, dict):
        raise Invalid("the body must be one JSON object: one event")
    return obj


def _text(obj: dict, name: str, limit: int, pattern: re.Pattern | None = None, what: str = "") -> str | None:
    v = obj.get(name)
    if v is None:
        return None
    if not isinstance(v, str) or not v:
        raise Invalid(f"{name} must be a non-empty string")
    if len(v) > limit:
        raise Invalid(f"{name} is {len(v)} characters; at most {limit}")
    if pattern is not None and not pattern.match(v):
        raise Invalid(f"{name} {v!r} {what}")
    if pattern is None and any(ord(c) < 32 or ord(c) == 127 for c in v):
        raise Invalid(f"{name} must not contain control characters")
    return v


def _time(raw: str) -> str:
    try:
        t = datetime.fromisoformat(raw)
    except ValueError:
        raise Invalid(f"time {raw!r} is not RFC 3339 (2026-10-27T18:58:31.043Z)") from None
    if t.tzinfo is None:
        raise Invalid(f"time {raw!r} has no timezone: end it with Z or an offset")
    return t.astimezone(UTC).isoformat(timespec="milliseconds")


def check(obj: dict) -> dict[str, Any]:
    """The keyword arguments of ``Events.publish`` for one event, or ``Invalid``."""
    unknown = sorted(set(obj) - ACCEPTED)
    if unknown:
        raise Invalid(f"unknown field{'s' if len(unknown) > 1 else ''} {', '.join(unknown)}; "
                      f"an event has {', '.join(sorted(ACCEPTED))}")
    if "specversion" in obj and obj["specversion"] != "1.0":
        raise Invalid(f"specversion must be \"1.0\", not {obj['specversion']!r}")
    if "datacontenttype" in obj and obj["datacontenttype"] != "application/json":
        raise Invalid("datacontenttype must be \"application/json\": data is JSON")
    type_ = _text(obj, "type", MAX_TYPE, TYPE, "must start with a letter or digit and use letters, digits, '.', '_', ':' and '-'")
    if type_ is None:
        raise Invalid("type is required: what happened, such as invoice.sent")
    if type_.startswith("orchestra.") and type_ not in MACHINES_MAY:
        raise Invalid(f"{type_} is Orchestra's own type; a machine may send only {', '.join(MACHINES_MAY)} "
                      "of those", 403)
    source = _text(obj, "source", MAX_SOURCE, SOURCE, "must be <machine> or <machine>/<instance>, each of letters, "
                                                      "digits, '.', '_', ':', '@' and '-'")
    if source is None:
        raise Invalid("source is required: the machine, or <machine>/<instance>")
    if source.partition("/")[0] == HOST:
        raise Invalid(f"{HOST} is Orchestra's own source", 403)
    out: dict[str, Any] = {"type": type_, "source": source, "data": obj.get("data")}
    for name in OPTIONAL_TEXT:
        if (v := _text(obj, name, MAX_TEXT)) is not None:
            out[name] = v
    if (raw := _text(obj, "time", 64)) is not None:
        out["time"] = _time(raw)
    if (eid := _text(obj, "id", MAX_ID, PRINTABLE, "must be printable ASCII without spaces")) is not None:
        out["id"] = eid
    return out


def types_filter(raw: str | None) -> set[str] | None:
    """``types=a,b`` of ``GET /events``: the types to keep, or None for every type."""
    if not raw:
        return None
    types = {t.strip() for t in raw.split(",") if t.strip()}
    for t in types:
        if len(t) > MAX_TYPE or not TYPE.match(t):
            raise Invalid(f"types: {t!r} is not an event type")
    return types or None


def number(raw: str | None, name: str, default: float, lo: float, hi: float, integer: bool = False) -> float:
    """A query parameter that is a number between ``lo`` and ``hi``."""
    if raw is None or raw == "":
        return default
    try:
        v = int(raw) if integer else float(raw)
    except ValueError:
        raise Invalid(f"{name} must be a{'n integer' if integer else ' number'}, not {raw!r}") from None
    if not lo <= v <= hi:
        raise Invalid(f"{name} must be between {lo:g} and {hi:g}, not {raw}")
    return v
