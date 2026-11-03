"""How far back a source holds: its first read reaches back into its history.

A source added to a project usually holds days of what the system did before (bootstrap run 4: a
Prometheus with seven days of the team's queues, of which discovery read none, because it read only
the last hour). So the **first read** of a ``[[sources]]`` entry, and the first after its ``url``,
``match`` or ``history`` changed (``key``), looks back from now, a page at a time (``PAGE_S``, a day,
at ``PAGE_POINTS`` points a series: a coarse look), until a page returns nothing (the store holds no
more), the source's ``history`` (default 7 days) is reached, or the round's budget is spent (its
``max_requests`` and ``deadline``, under the store's rate and daily cap: ``limits.py``). A round
stopped by its budget is taken up where it stopped by the next discovery; after ``STALLS`` rounds
in a row that read no page at all, it stands at what it has. What it found is kept
in ``<state>/sources/<name>.held.json``: the oldest point the store returned (``oldest``), how far
back the pages reached (``through``) and whether they are done (``complete``).

Discovery's window is then the longer of ``[discovery] window`` and what the sources hold, up to
``history`` (``sd.rediscover``): read at a step that keeps the grid's number of steps, through the
read cache like any window, and within the last era that could change what the source measures
(``sd.rediscover.cuts``: an era the project's configuration began keeps it). Every definition is
read in the pages, levels as well as counters. Only the host's discovery and the CLI make
a first read; every other reader uses what is kept."""

from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
import time
from pathlib import Path

from .spec import SourceSpec

PAGE_S = 86400.0             # one page of the first read
PAGE_POINTS = 48             # points per series in a page: enough to see where the store's data begins
STALLS = 3                   # rounds in a row whose budget read no page, then the first read stands at what it has


def key(spec: SourceSpec) -> str:
    """What a first read is made for: the store, what it selects, and how far back it may go."""
    body = json.dumps([spec.url, spec.match, spec.history], sort_keys=True)
    return hashlib.sha256(body.encode()).hexdigest()[:16]


def _path(state_dir: Path, name: str) -> Path:
    return Path(state_dir) / "sources" / f"{name}.held.json"


def read(state_dir: Path, name: str) -> dict:
    try:
        d = json.loads(_path(state_dir, name).read_text())
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def write(state_dir: Path, name: str, rec: dict) -> None:
    p = _path(state_dir, name)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=p.parent, prefix=f".{p.stem}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as fh:
            fh.write(json.dumps(rec))
        os.replace(tmp, p)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def due(rec: dict, spec: SourceSpec) -> bool:
    """Whether a first read is to be made, or taken up: none under these settings, or one not done."""
    return rec.get("key") != key(spec) or not rec.get("complete")


def span(rec: dict, spec: SourceSpec, now: float) -> float:
    """How far back from ``now`` the source holds, up to its ``history``; 0 when not known."""
    oldest = rec.get("oldest") if rec.get("key") == key(spec) else None
    return min(spec.history, max(0.0, now - float(oldest))) if oldest is not None else 0.0


def pages(spec: SourceSpec, now: float, through: float | None) -> list[tuple[float, float, float]]:
    """The pages still to read, newest first: (start, end, step), from ``through`` (or now) back to
    ``history`` before now."""
    out, b, bound = [], min(now, through) if through else now, now - spec.history
    while b > bound + 1e-6:
        a = max(bound, b - PAGE_S)
        out.append((a, b, max(60.0, math.ceil((b - a) / PAGE_POINTS / 60.0) * 60.0)))
        b = a
    return out


def first_read(spec: SourceSpec, rec: dict, now: float, read_page) -> dict:
    """The first read, or what is left of one: ``read_page(start, end, step)`` returns the oldest
    point of the page (None: nothing in it) and whether the round's budget stopped it. Returns the
    record to keep."""
    if rec.get("key") != key(spec):
        rec = {}
    rec = {**rec, "key": key(spec), "at": time.time()}
    read_any = False
    for a, b, step in pages(spec, now, rec.get("through")):
        oldest, stopped = read_page(a, b, step)
        if stopped:                          # the budget or the deadline: the next discovery takes it up here
            stalls = 0 if read_any else int(rec.get("stalls") or 0) + 1
            rec.update(through=b, complete=stalls >= STALLS, stalls=stalls)   # never a page in a round, STALLS times: what it has
            return rec
        read_any = True
        rec["pages"] = int(rec.get("pages") or 0) + 1
        if oldest is None:                   # nothing in this page: the store holds no more
            rec.update(through=a, complete=True)
            return rec
        rec["oldest"] = min(float(oldest), float(rec.get("oldest") or oldest))
        rec["through"] = a
        if oldest > a + 2 * step:            # its data begins inside this page: there is none before
            rec["complete"] = True
            return rec
    rec["complete"] = True
    return rec
