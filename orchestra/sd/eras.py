"""Eras: a new one begins when a machine changes the system (goal G11, docs/roadmap/goals.md).

An era is the time the model is discovered in. After a machine changes how the system works (a
prompt or a role edited, the configuration changed, a worker kind added, a deploy) it is a
different system, and what was measured before is not evidence for it: discovery reads only the
current era (``sd.rediscover``), and the previous era's model is its prior (``sd.prior``).

**Which events begin an era.** Orchestra knows no domain (AGENTS.md rule 1), so it is told:

- ``system.changed`` always does. It is the generic mark any machine may publish when it changed
  the system: its ``source`` is the machine that made the change, and its ``subject`` may say
  what was changed. Its ``data`` is the machine's own and is never read;
- ``[discovery] eras_from`` names more, as filters on the envelope (rule 3: Orchestra reads the
  envelope, never ``data``). A filter is an event type, or a glob of types, optionally followed by
  ``:`` and ``field=glob`` pairs separated by commas, on ``source`` and ``subject``:

      eras_from = ["config.changed", "role.changed:source=supervisor", "gate.landed:subject=orchestra.toml"]

  The default is ``["config.changed"]``, what the Supervisor publishes when it changes the
  configuration; ``[]`` leaves only ``system.changed``. A change of what is measured only (an
  instrument or a source added) is no change to the system, and the Supervisor announces it as
  ``instruments.changed``, which begins none: an era begun there would drop the history a new
  source brings.

Orchestra's own events (types beginning ``orchestra.``) never begin one.

**The record.** ``sync`` follows the bus from where it last stopped (an offset kept in the model
store's ``eras.json``), records each matching event once (by its id) as an era ``e1``, ``e2``, …
in the order they were read, with its start (the event's ``time``), label (``type from source``)
and cause (the event's id, type, source and subject), and says which are new, so whoever recorded
them announces them (``orchestra.era.started``). When the filters change, the bus is read again
from its start and the eras are numbered again. Before the first era there is no era (``None``):
the time since the system was first measured."""

from __future__ import annotations

import fnmatch
from dataclasses import asdict

from ..events import event_time
from .model import Era
from .store import ModelStore

ALWAYS = "system.changed"
DEFAULT_FROM = ["config.changed"]
FIELDS = ("source", "subject")
OWN = "orchestra."
RECORD = "eras"


class FilterError(ValueError):
    pass


def parse(entry: str) -> tuple[str, dict[str, str]]:
    """One ``eras_from`` filter: its type glob and its envelope fields' globs."""
    if not isinstance(entry, str) or not entry.strip():
        raise FilterError(f"eras_from: {entry!r} is not an event type")
    ty, _, rest = entry.strip().partition(":")
    fields = {}
    for part in filter(None, (p.strip() for p in rest.split(","))):
        k, eq, v = part.partition("=")
        if not eq or k.strip() not in FIELDS:
            raise FilterError(f"eras_from: {entry!r}: after the type, only {' and '.join(f'{f}=…' for f in FIELDS)} "
                              "(the envelope's fields; an event's data is never read)")
        fields[k.strip()] = v.strip()
    return ty.strip(), fields


def check(entries) -> list[str]:
    """The filters as configured, each checked; raises FilterError."""
    if not isinstance(entries, list):
        raise FilterError("eras_from must be a list of event types")
    for e in entries:
        parse(e)
    return list(entries)


def begins(ev: dict, entries: list[str]) -> bool:
    """Whether the event begins an era: ``system.changed``, or a configured filter, read from
    its envelope alone; never one of Orchestra's own."""
    ty = ev.get("type") or ""
    if not ty or ty.startswith(OWN):
        return False
    if ty == ALWAYS:
        return True
    for entry in entries:
        glob, fields = parse(entry)
        if fnmatch.fnmatchcase(ty, glob) and all(fnmatch.fnmatchcase(str(ev.get(k) or ""), g) for k, g in fields.items()):
            return True
    return False


def era_of(ev: dict, n: int) -> Era | None:
    t = event_time(ev)
    if t is None:
        return None
    src = ev.get("source")
    return Era(f"e{n}", t, f"{ev['type']} from {src or 'an unnamed source'}", ev.get("id"), ev.get("type"), src, ev.get("subject"))


def recorded(store: ModelStore) -> list[Era]:
    """Every era recorded, by start."""
    rec = store.read_record(RECORD) or {}
    return sorted((Era(**e) for e in rec.get("eras") or []), key=lambda e: (e.start, e.id))


def sync(store: ModelStore, events, entries: list[str], publish=None) -> tuple[list[Era], list[Era]]:
    """Read what is new on the bus and record the eras it begins; returns every era (by start)
    and the new ones. ``publish(type, data, **ext)``, when given, announces each new era as
    ``orchestra.era.started``: only the process that recorded it does."""
    with store.locked(RECORD):
        rec = store.read_record(RECORD) or {}
        if rec.get("filters") != list(entries) or rec.get("offset", 0) > events.end():
            rec = {"filters": list(entries), "offset": 0, "eras": []}        # the filters changed, or the bus was replaced
        evs, offset = events.after(rec["offset"])
        seen = {e.get("cause") for e in rec["eras"]}
        new = []
        for ev in evs:
            if begins(ev, entries) and ev.get("id") not in seen and (era := era_of(ev, len(rec["eras"]) + 1)):
                rec["eras"].append(asdict(era))
                seen.add(era.cause)
                new.append(era)
        rec["offset"] = offset
        store.write_record(RECORD, rec)
    if publish is not None:
        for era in new:
            publish("orchestra.era.started", {"era": era.id, "start": era.start, "label": era.label,
                                              "cause": {"id": era.cause, "type": era.type, "source": era.source, "subject": era.subject}},
                    subject=era.id, causationid=era.cause)
    return recorded(store), new


def current(eras: list[Era], at: float) -> Era | None:
    """The era in force at ``at``: the last to begin at or before it."""
    return next((e for e in sorted(eras, key=lambda e: e.start, reverse=True) if e.start <= at), None)


def previous(eras: list[Era], era: Era | None) -> Era | None:
    """The era before ``era`` (None: the time before any era)."""
    if era is None:
        return None
    before = [e for e in eras if e.start < era.start or (e.start == era.start and e.id < era.id)]
    return max(before, key=lambda e: e.start) if before else None
