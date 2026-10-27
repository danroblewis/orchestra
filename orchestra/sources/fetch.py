"""Reading one definition from its source for a window, as series discovery can use.

- A **level** is a query evaluated with ``query_range`` on discovery's grid, but never finer than
  the series' own resolution: the step is discovery's step times the smallest whole number that
  reaches the reporting interval, and the first point is at or before the window's start.
- A **counter** read from raw samples (view ``increments``) keeps the real sample times: each
  reporting series' increments are ``b − a``, or ``b`` after a drop (a reset), and its first
  sample is a baseline, not events; the increments are summed by the definition's grouping into
  a running total that starts at 0. A series that began inside the window (its first sample more
  than two of its own sample intervals after the start, and no larger than twice its largest
  increment: a counter that started at 0, such as a publisher's new channel) counts its first
  value too.
- A **turnover** (views ``starts`` and ``stops``) is read from the same raw samples a count is
  made from: the series that started and stopped reporting, so the count is a stock its two
  counters balance exactly.
- A **count** (views ``count`` and ``distinct``) reads 0 for a group at the steps it has no
  reporters while another group of the same count has some (``zero_fill``).
- A **rate** (a query of per-second rates) is integrated over each step into a running total
  that starts at 0.
- A counter evaluated by a query (a script's ``kind = "counter"``) is passed on as it is, and its
  first sample is a baseline (``sd.series.Declared``).

Results are renamed to canonical labels, labelled ``machine = <prefix>.<value>`` when they carry
the source's machine label, and named ``<prefix>:<name>``. A ``machine`` or ``source`` label the
remote itself wrote is prefixed too, since discovery reads machines from them, and a remote
``authz`` must never merge with an own one. A definition of counted traffic (``traffic.py``)
resolves, per result series, the channel and the machine it counts for, and that machine is the
series' ``machine`` label, so discovery attributes its flow to the producer or consumer."""

from __future__ import annotations

import math
from itertools import pairwise

from . import Labels, Points, Source
from .traffic import resolve
from .views import Definition, count_window


def grid_step(step: float, resolution_s: float | None) -> float:
    """Discovery's step, or the smallest multiple of it no finer than the series' resolution."""
    if not resolution_s or resolution_s <= step:
        return step
    return step * math.ceil(resolution_s / step - 1e-9)


def began_inside(pts: Points, start: float | None) -> bool:
    """Whether a counter series began inside the window: its first sample well after the start (two
    of its own sample intervals) and no larger than twice its largest increment, so it counted
    from 0 rather than being an old counter the store was missing at the start."""
    if start is None or len(pts) < 3:
        return False
    gaps = sorted(b[0] - a[0] for a, b in pairwise(pts))
    incs = [(b - a) if b >= a else b for (_, a), (_, b) in pairwise(pts)]
    return pts[0][0] - start > 2 * gaps[len(gaps) // 2] and pts[0][1] <= 2 * max(incs, default=0.0)


def increments(raw: list[tuple[Labels, Points]], by_real: list[str], start: float | None = None) -> list[tuple[Labels, Points]]:
    """Raw counter samples summed by ``by_real`` into running totals of their increments; with
    ``start``, a series that began inside the window counts its first value too."""
    groups: dict[tuple, tuple[Labels, dict[float, float], list[float]]] = {}
    for labels, pts in raw:
        key = {k: labels[k] for k in by_real if k in labels}
        g = groups.setdefault(tuple(sorted(key.items())), (key, {}, []))
        if pts:
            g[2].append(pts[0][0])
            if began_inside(pts, start) and pts[0][1] > 0:
                g[1][pts[0][0]] = g[1].get(pts[0][0], 0.0) + pts[0][1]
        for (_, a), (t, b) in pairwise(pts):
            g[1][t] = g[1].get(t, 0.0) + ((b - a) if b >= a else b)
    out = []
    for key, incs, firsts in groups.values():
        if not firsts:
            continue
        total, pts = 0.0, [(min(firsts), 0.0)]
        for t in sorted(incs):
            total += incs[t]
            if t == pts[-1][0]:
                pts[-1] = (t, total)
            else:
                pts.append((t, total))
        out.append((key, pts))
    return out


def turnover(raw: list[tuple[Labels, Points]], by_real: list[str], window: float, start: float, end: float,
             stops: bool) -> list[tuple[Labels, Points]]:
    """How many reporting series (pods) started, or stopped, reporting: running totals by
    ``by_real``. A series is reporting from a sample until ``window`` after its last one (as
    ``last_over_time(…[window])`` counts it), so a stretch of samples no further apart than
    ``window`` is one life: it starts at its first sample (unless that is at or before ``start``:
    reporting already, a baseline) and stops ``window`` after its last (unless that is after
    ``end``). Then the count at any time is the count at ``start`` plus starts less stops."""
    groups: dict[tuple, tuple[Labels, list[float]]] = {}
    for labels, pts in raw:
        key = {k: labels[k] for k in by_real if k in labels}
        g = groups.setdefault(tuple(sorted(key.items())), (key, []))
        ts = sorted(t for t, _ in pts)
        lives, a = [], ts[0] if ts else None
        for x, y in pairwise(ts):
            if y - x > window:
                lives.append((a, x))
                a = y
        if ts:
            lives.append((a, ts[-1]))
        for a, b in lives:
            if stops and b + window <= end:
                g[1].append(b + window)
            elif not stops and a > start:
                g[1].append(a)
    out = []
    for key, events in groups.values():
        pts, total = [(start, 0.0)], 0.0
        for t in sorted(events):
            total += 1
            if t == pts[-1][0]:
                pts[-1] = (t, total)
            else:
                pts.append((t, total))
        out.append((key, pts))
    return out


def zero_fill(got: list[tuple[Labels, Points]]) -> list[tuple[Labels, Points]]:
    """A count's groups at 0 where nothing reported: ``count by (G)`` returns no series for a group
    with no reporters, so a region down reads as missing, not as 0 pods. Each group seen in the
    window reads 0 at every step at which another group of the same count has a point. A step at
    which no group has one stays empty: the store had nothing then (a gap), not zero."""
    steps = {t for _, pts in got for t, _ in pts}
    out = []
    for labels, pts in got:
        have = {t for t, _ in pts}
        out.append((labels, sorted(pts + [(t, 0.0) for t in steps - have])))
    return out


def integrate(pts: Points) -> Points:
    """Per-second rates into a running total: each value covers the step that ends at it."""
    if not pts:
        return []
    out, total = [(pts[0][0], 0.0)], 0.0
    for (t0, _), (t1, v) in pairwise(pts):
        total += v * (t1 - t0)
        out.append((t1, total))
    return out


def read(source: Source, d: Definition, prefix: str, machine: str | None, start: float, end: float,
         step: float, producers: dict[str, str] | None = None, until: float | None = None) -> list[tuple[str, Labels, Points, dict | None]]:
    """Each result series: its name, labels, points, and what it counts when it is traffic.
    ``until``: the source's deadline (``time.monotonic()``), past which no request is made."""
    if d.view == "increments":
        res = d.resolution_s or 0.0
        got = increments(source.select(d.query, start - res, end, until=until), d.by_real, start)
    elif d.view in ("starts", "stops"):
        w = count_window(d.resolution_s)
        got = turnover(source.select(d.query, start - w, end, until=until), d.by_real, w, start, end, d.view == "stops")
    else:
        q = grid_step(step, d.resolution_s)
        got = source.query_range(d.query, math.floor(start / q) * q, end, q, until=until)
        if d.view in ("count", "distinct"):
            got = zero_fill(got)
        if d.kind == "rate":
            got = [(labels, integrate(pts)) for labels, pts in got]
    out = []
    for labels, pts in got:
        lab = {d.rename.get(k, k): v for k, v in labels.items() if k != "__name__"}
        lab.update(d.extra_labels)
        counted = resolve(d.traffic, lab, prefix, producers) if d.traffic else None
        named = lab.get(machine) if machine else None   # read before the prefixing below: `machine` may be "machine"
        for k in ("machine", "source"):           # the labels discovery reads machines from: never an own machine's name
            if lab.get(k):
                lab[k] = f"{prefix}.{lab[k]}"
        if named:
            lab["machine"] = f"{prefix}.{named}"
        if counted and counted["machine"]:
            lab["machine"] = counted["machine"]
        elif counted and lab.get("machine"):           # no template, but the source's machine label names it
            counted.update(machine=lab["machine"], attributed="from its machine label")
        out.append((f"{prefix}:{d.name}", lab, pts, counted))
    return out
