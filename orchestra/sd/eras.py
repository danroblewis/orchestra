"""Eras: a new one begins when a machine changes how the system behaves (goal G11, docs/roadmap/goals.md).

An era is the time the model is discovered in. After a machine changes how the system works (a
machine's spec, its model or its duties edited, a definition the machines work by changed, a
declared effect confirmed, a deploy) it is a different system, and what was measured before is not
evidence for it: discovery reads only the current era (``sd.rediscover``) for what the change
could have altered (a source's series keep their history through an era a ``config.changed``
began: ``sources_era``), and the previous era's model is its prior (``sd.prior``). Measuring more, or otherwise, is not such a change: an era begun
by it would throw away the history a new source brings.

**Which events begin an era.** Orchestra knows no domain (AGENTS.md rule 1), so it is told, by the
envelope alone (rule 3: never ``data``):

- ``system.changed``, the generic mark any machine may publish when it changed the system: its
  ``source`` is the machine that made the change, and its ``subject`` may say what was changed;
- ``[discovery] eras_from`` names more, as filters on the envelope. A filter is an event type, or
  a glob of types, optionally followed by ``:`` and ``field=glob`` pairs separated by commas, on
  ``source`` and ``subject``:

      eras_from = ["config.changed", "deploy.finished:subject=billing*", "release.*:source=ci"]

  The default is ``["config.changed"]``, the conventional type any machine may publish when it
  changes the configuration; ``[]`` leaves only ``system.changed``.

Of those, the ``subject`` decides (``begins``):

- a subject naming what is measured or a setting (``instrument:``, ``collector:``, ``collect:``,
  ``scrape:``, ``source:``, ``series:``, ``setting:``, ``MEASURES``) never begins one;
- a change a prediction is about (an ``orchestra.prediction.made`` whose ``change`` is its id: a
  declared effect confirmed, a machine's predicted fix) always does: it says it changes the system;
- a ``machine:<name>`` subject whose name is an instrument's is a measurement change too, and never
  begins one, whatever the subject says (bootstrap run 5: a GitHub poller, a ``[[machines]]`` entry
  with a ``[[collect]]`` twin, removed as ``machine:github_plugins_poller``, began the run's one
  era and cut a week of a source's history to 58 minutes). A name is an instrument's when the
  configuration gives an instrument that name (a ``[[collect]]`` or ``[[scrape]]`` entry, a
  plugin's collector in the runtime record, a ``[[sources]]`` entry: ``instrument_names``) or the
  bus has named it as one (a subject ``instrument:``, ``collector:``, ``collect:`` or ``scrape:``
  with that name, read before it); the names are kept in the record (``instruments``), so an
  instrument removed from the configuration is still known as one when its removal is read;
- a subject naming a part that behaves (``machine:<name>``: its spec, its model or its duties;
  ``definition:<name>``: a definition machines work by; ``override:<name>``: code loaded over a
  package's, ``BEHAVES``) does;
- otherwise ``config.changed`` does not: it says the configuration changed, not that the system's
  behaviour did (the configuration also holds the instruments, the sources and the plugins'
  settings), and ``system.changed`` and every other type a filter names do.

A ``config.changed`` read while the configuration is what it was at the one before (its content,
hashed: ``config_key``) changed nothing, and begins no era (a no-op). Only an event read within
``FRESH_S`` of its time is judged so: a bus read again from its start cannot tell what the
configuration was then. Orchestra's own events (types beginning ``orchestra.``) never begin one.

**An era is never shorter than discovery needs.** A stock must cover ``MIN_COVER`` of discovery's
window (``sd.discover``), so a change that comes within ``MIN_COVER`` × ``[discovery] window`` of
the current era's start begins no era: it is kept in that era (``Era.changes``, shown with it), and
a prediction about it belongs to that era (``of_change``). Changes every few minutes (a merge
taken for a release) make one era per half hour, not one per change, and each holds enough to fit.

**The record.** ``sync`` follows the bus from where it last stopped (an offset kept in the model
store's ``eras.json``), records each era-beginning event once (by its id) as an era ``e1``, ``e2``,
… in the order they were read, with its start (the event's ``time``), label (``type from source``)
and cause (the event's id, type, source and subject), and says which are new, so whoever recorded
them announces them (``orchestra.era.started``). When the filters change, the bus is read again
from its start and the eras are numbered again. Before the first era there is no era (``None``):
the time since the system was first measured."""

from __future__ import annotations

import fnmatch
import hashlib
import json
import time
from collections.abc import Callable
from dataclasses import asdict

from ..events import event_time
from .model import Era
from .store import ModelStore

ALWAYS = "system.changed"
CONFIG = "config.changed"
DEFAULT_FROM = [CONFIG]
FIELDS = ("source", "subject")
OWN = "orchestra."
PREDICTION = "orchestra.prediction.made"
RECORD = "eras"
BEHAVES = ("machine:", "definition:", "override:")      # subjects naming a part that behaves
MEASURES = ("instrument:", "collector:", "collect:", "scrape:", "source:", "series:", "setting:")   # what is measured, or a setting
NAMES_INSTRUMENT = ("instrument:", "collector:", "collect:", "scrape:")   # subjects that name an instrument by its name
MACHINE = "machine:"
FRESH_S = 300.0              # a config.changed read within this of its time is judged a no-op or not


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


def named(ev: dict, entries: list[str]) -> bool:
    """Whether ``system.changed`` or a configured filter names the event, by its envelope alone;
    never one of Orchestra's own."""
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


def _names(subject: str, prefixes: tuple[str, ...]) -> list[str]:
    """The names a subject with one of ``prefixes`` names (``collector:a`` -> [a]; ``machine:a,b``
    -> [a, b]); [] for any other subject."""
    if not subject.startswith(prefixes):
        return []
    return [n.strip() for n in subject.partition(":")[2].split(",") if n.strip()]


def of_instrument(subject: str, instruments: set[str] | frozenset[str]) -> bool:
    """Whether a ``machine:<name>`` subject names only instruments' processes: a measurement change."""
    names = _names(subject, (MACHINE,))
    return bool(names) and all(n in instruments for n in names)


def begins(ev: dict, entries: list[str], predicted: set[str] | frozenset[str] = frozenset(),
           instruments: set[str] | frozenset[str] = frozenset()) -> bool:
    """Whether the event is a change of how the system behaves, and so begins an era (unless it
    comes too soon after the current era's start, ``sync``): named by ``system.changed`` or a
    filter, and then decided by its subject (the module's docstring). ``predicted``: the ids of
    the changes predictions are about; ``instruments``: the names known as instruments', whose
    ``machine:`` changes are measurement changes."""
    if not named(ev, entries):
        return False
    subject = str(ev.get("subject") or "")
    if subject.startswith(MEASURES) or of_instrument(subject, instruments):
        return False
    if ev.get("id") and ev["id"] in predicted:
        return True
    if subject.startswith(BEHAVES):
        return True
    return ev.get("type") != CONFIG


def instrument_names(project) -> set[str]:
    """The names the configuration gives instruments now: its ``[[collect]]``, ``[[scrape]]`` and
    ``[[sources]]`` entries, and the plugins' collectors the host runs (its runtime record). What
    cannot be read gives nothing."""
    out: set[str] = set()
    try:
        raw = getattr(project.config, "raw", None) or {}
        for section in ("collect", "scrape", "sources"):
            out |= {str(e["name"]) for e in raw.get(section) or [] if isinstance(e, dict) and e.get("name")}
    except (AttributeError, TypeError):
        pass
    if getattr(project, "runtime_file", None) is not None:      # no runtime record (no host yet): the configuration's alone
        from .. import runtime
        out |= {str(n) for n in (runtime.read(project).get("instruments") or {})}
    return out


def config_key(raw: dict) -> str:
    """The configuration's content (``orchestra.toml`` with the private overlay), hashed: what a
    no-op ``config.changed`` leaves as it was."""
    return hashlib.sha256(json.dumps(raw or {}, sort_keys=True, default=str).encode()).hexdigest()[:16]


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


def _predicted(store: ModelStore) -> set[str]:
    """The changes the recorded predictions are about (``sd.predictions``)."""
    rec = store.read_record("predictions") or {}
    return {str(p["change"]) for p in rec.get("predictions") or [] if isinstance(p, dict) and p.get("change")}


def sync(store: ModelStore, events, entries: list[str], publish=None, *, min_s: float = 0.0,
         config: Callable[[], str] | None = None, noted: list | None = None,
         clock: Callable[[], float] = time.time,
         instruments: Callable[[], set[str]] | None = None) -> tuple[list[Era], list[Era]]:
    """Read what is new on the bus and record the eras it begins; returns every era (by start)
    and the new ones. ``publish(type, data, **ext)``, when given, announces each new era as
    ``orchestra.era.started``: only the process that recorded it does. ``min_s``: the shortest
    era; a change within it of the current era's start is kept in that era (and appended to
    ``noted``, when given). ``config``: the configuration's key now (``config_key``), asked only
    when a fresh ``config.changed`` is read, so a no-op begins nothing. ``instruments``: the names
    the configuration gives instruments now (``instrument_names``), kept in the record with those
    the bus named, so a ``machine:`` change of an instrument's process begins nothing."""
    with store.locked(RECORD):
        rec = store.read_record(RECORD) or {}
        if rec.get("filters") != list(entries) or rec.get("offset", 0) > events.end():
            # the filters changed, or the bus was replaced: read again from its start
            rec = {"filters": list(entries), "offset": 0, "eras": [],
                   **{k: rec[k] for k in ("config", "instruments") if rec.get(k)}}
        evs, offset = events.after(rec["offset"])
        known = set(rec.get("instruments") or []) | (set(instruments()) if instruments is not None else set())
        seen = {e.get("cause") for e in rec["eras"]} | {c.get("id") for e in rec["eras"] for c in e.get("changes") or []}
        predicted = _predicted(store) | {str(ev["data"]["change"]) for ev in evs
                                         if ev.get("type") == PREDICTION and isinstance(ev.get("data"), dict) and ev["data"].get("change")}
        now_key: list[str] = []
        new = []
        for ev in evs:
            if not str(ev.get("type") or "").startswith(OWN):
                known |= set(_names(str(ev.get("subject") or ""), NAMES_INSTRUMENT))    # the bus names an instrument
            if ev.get("type") == CONFIG and config is not None and named(ev, entries):
                t = event_time(ev)
                if t is not None and clock() - t <= FRESH_S:
                    if not now_key:
                        now_key.append(config())
                    same = rec.get("config") == now_key[0]
                    rec["config"] = now_key[0]
                    if same:
                        continue                # the configuration is what it was: nothing changed
            if not begins(ev, entries, predicted, known) or ev.get("id") in seen:
                continue
            cur = rec["eras"][-1] if rec["eras"] else None
            t = event_time(ev)
            if t is None:
                continue
            if cur is not None and t - cur["start"] < min_s:
                change = {"id": ev.get("id"), "type": ev.get("type"), "source": ev.get("source"), "subject": ev.get("subject"), "at": t}
                cur.setdefault("changes", []).append(change)
                seen.add(ev.get("id"))
                if noted is not None:
                    noted.append((cur["id"], change))
                continue
            if era := era_of(ev, len(rec["eras"]) + 1):
                rec["eras"].append(asdict(era))
                seen.add(era.cause)
                new.append(era)
        rec["offset"] = offset
        rec["instruments"] = sorted(known)
        store.write_record(RECORD, rec)
    if publish is not None:
        for era in new:
            publish("orchestra.era.started", {"era": era.id, "start": era.start, "label": era.label,
                                              "cause": {"id": era.cause, "type": era.type, "source": era.source, "subject": era.subject}},
                    subject=era.id, causationid=era.cause)
    return recorded(store), new


def shortest(cfg) -> float:
    """The shortest era: ``MIN_COVER`` of discovery's window (``sd.discover``), what a stock must
    cover to be fitted."""
    from .discover import MIN_COVER
    return MIN_COVER * float(getattr(cfg, "discovery_window", 3600.0) or 3600.0)


def follow(store: ModelStore, events, project, publish=None, noted: list | None = None) -> tuple[list[Era], list[Era]]:
    """``sync`` as the host and discovery run it: the project's filters, the shortest era its
    window allows, and its configuration's key for the no-op check."""
    def key() -> str:
        read = getattr(project, "read_config", None)
        return config_key(getattr(read() if read else project.config, "raw", None) or {})
    return sync(store, events, project.config.eras_from, publish, min_s=shortest(project.config), config=key, noted=noted,
                instruments=lambda: instrument_names(project))


def of_change(eras: list[Era], change: str | None) -> Era | None:
    """The era a change belongs to: the one it began, or the one it was kept in."""
    if not change:
        return None
    return next((e for e in eras if e.cause == change or any(c.get("id") == change for c in e.changes)), None)


def by_change(eras: list[Era]) -> dict[str, Era]:
    """Each change's era (``of_change``), by the change's id."""
    out = {}
    for e in eras:
        for c in e.changes:
            if c.get("id"):
                out[c["id"]] = e
        if e.cause:
            out[e.cause] = e
    return out


def current(eras: list[Era], at: float) -> Era | None:
    """The era in force at ``at``: the last to begin at or before it."""
    return next((e for e in sorted(eras, key=lambda e: e.start, reverse=True) if e.start <= at), None)


def sources_era(eras: list[Era], at: float) -> Era | None:
    """The era a source's series are discovered in (``sd.rediscover``): the last to begin at or
    before ``at`` whose cause could have changed what another system's store measures. A
    ``config.changed`` changes the project's own configuration (a machine's spec, a definition,
    code loaded over a package's), not the system a source reads in place, so it cuts the own
    store's series only; ``system.changed`` and the other types a filter names (a deploy) cut
    every series."""
    return next((e for e in sorted(eras, key=lambda e: e.start, reverse=True) if e.start <= at and e.type != CONFIG), None)


def previous(eras: list[Era], era: Era | None) -> Era | None:
    """The era before ``era`` (None: the time before any era)."""
    if era is None:
        return None
    before = [e for e in eras if e.start < era.start or (e.start == era.start and e.id < era.id)]
    return max(before, key=lambda e: e.start) if before else None
