"""A quiet window holds the model: a stock whose series did not move is not gone.

A stock that stops moving still holds its quantity. When a discovery's window is quiet for a
stock of the current version, the window has no evidence about it, for or against; dropping it
would save a poorer model as "the structure changed" (the core demo, 2026-11-01: a quiet hour
saved v4 with one stock of v3's seven, and the next discovery drew DONE=34 as gone). A stock is
quiet when discovery did not find it and its series is **still**: written up to the end of the
window (its last point no further from the end than two steps or three of its own write
intervals) and moving less than ``MIN_EVENTS`` times in it (a level's changes, a counter's
events). A stock no series measures is quiet when every counter of its flows is (whatever
discovery made of them: left out as unmoved, as too few, or folded into another counter of the
same few events). A series that stopped being written inside the window has **stopped**, not
gone still: its stock goes, as discovery says.

``hold`` carries each quiet stock from the current version into the discovery, with the current
version's flows that reach it (whose other end is outside or in the discovery), marked
``evidence["quiet"]``: the version they stand on and since when (the last time its series moved,
else the window's start). Nothing is fitted or deleted: the held parts are the current version's,
numbers and all, and a discovery whose structure is then the current version's saves no version
(``rediscover``); the record says ``quiet since <time>: the model of v<N> stands``."""

from __future__ import annotations

import copy
from datetime import UTC, datetime
from itertools import pairwise

from .balance import MIN_EVENTS
from .model import Machine, Model
from .series import series_key


def _gap(times: list[float]) -> float:
    gaps = sorted(b - a for a, b in pairwise(times))
    return gaps[len(gaps) // 2] if gaps else 0.0


def still(points: list, counter: bool, start: float, end: float, step: float) -> tuple[bool, float | None]:
    """Whether a series was written up to the window's end and moved fewer than ``MIN_EVENTS``
    times in it, and when it last moved (None: never, in what was read)."""
    if not points:
        return False, None
    times = [t for t, _ in points]
    moved = [t for (_, a), (t, b) in pairwise(points) if ((b > a or 0 < b < a) if counter else b != a)]   # a counter's drop is a reset
    recent = times[-1] >= end - max(2 * step, 3 * _gap(times))
    return recent and sum(1 for t in moved if start < t <= end) < MIN_EVENTS, (moved[-1] if moved else None)


def _quiet_stock(s, flows: list, read: dict, start: float, end: float, step: float) -> tuple[bool, float | None]:
    refs = [(s.series, False)] if s.series is not None else \
        [(f.counter, True) for f in flows if s.id in (f.src, f.dst) and f.counter is not None]
    if not refs:
        return False, None
    found = [still(read.get(series_key(r.name, r.labels), []), c, start, end, step) for r, c in refs]
    return all(q for q, _ in found), max((t for _, t in found if t is not None), default=None)


def hold(model: Model, current: Model | None, version: int | None, dump: list | None) -> Model:
    """The discovered ``model`` with the quiet stocks of ``current`` (saved as ``version``) it
    lacks carried in, each with the flows that reach it; recorded in ``model.discovery["quiet"]``.
    ``dump``: what the discovery read, as (name, labels, points); without it nothing is held."""
    if current is None or current.era != model.era or not dump:
        return model                   # another era's parts are the prior's to carry (sd.prior)
    d = model.discovery
    start, end, step = d.get("start"), d.get("end"), d.get("step")
    if start is None or end is None or not step:
        return model
    read = {series_key(n, labels): sorted(pts) for n, labels, pts in dump}
    have = {s.id for s in model.stocks}
    used = {series_key(s.series.name, s.series.labels) for s in model.stocks if s.series is not None}
    held, since = [], {}
    for s in current.stocks:
        if s.id in have or (s.evidence or {}).get("simulated") or (s.series and series_key(s.series.name, s.series.labels) in used):
            continue
        q, last = _quiet_stock(s, current.flows, read, start, end, step)
        if q:
            held.append(s)
            since[s.id] = last if last is not None and last <= end else start
    if not held:
        return model
    for s in held:
        c = copy.deepcopy(s)
        c.evidence = {**c.evidence, "quiet": {"version": version, "since": since[s.id],
                                              "why": "its series was written to the end of the window and hardly moved: no evidence for or against it, so it stands"}}
        model.stocks.append(c)
        have.add(s.id)
    ids, flows = {s.id for s in held}, {f.id for f in model.flows}
    carried = []
    for f in current.flows:
        if f.id in flows or not ({f.src, f.dst} & ids) or not all(x is None or x in have for x in (f.src, f.dst)):
            continue
        c = copy.deepcopy(f)
        c.evidence = {**c.evidence, "quiet": {"version": version, "why": "a flow of a stock held through a quiet window"}}
        model.flows.append(c)
        carried.append(f.id)
    mine = {m.id: m for m in model.machines}
    for m in current.machines:
        theirs = [fid for fid in m.attributed if fid in carried]
        if not theirs:
            continue
        if m.id in mine:
            mine[m.id].attributed = list(dict.fromkeys([*mine[m.id].attributed, *theirs]))
        else:
            model.machines.append(Machine(m.id, m.name, m.kind, m.description, theirs, list(m.observed_by), m.bootstrap))
    first = min((t for t in since.values() if t is not None), default=None)
    model.discovery["quiet"] = {"version": version, "since": first, "since_by_stock": since,
                                "stocks": [s.id for s in held], "flows": carried}
    return model


def stands(model: Model) -> str | None:
    """What the discovery record says when the held model is the current version's."""
    q = model.discovery.get("quiet")
    if not q:
        return None
    if q.get("since") is None:
        return f"quiet: the model of v{q['version']} stands"
    at = datetime.fromtimestamp(q["since"], UTC).strftime("%Y-%m-%d %H:%M UTC")
    return f"quiet since {at}: the model of v{q['version']} stands"
