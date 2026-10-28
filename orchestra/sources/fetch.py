"""Reading one definition from its source for a window, as series discovery can use.

- A **level** is a query evaluated with ``query_range`` on discovery's grid, but never finer than
  the series' own resolution: the step is discovery's step times the smallest whole number that
  reaches the reporting interval, and the first point is at or before the window's start.
- An inferred **counter** (view ``increments``) is read server-side, ``sum by (G) (increase(x[S]))``
  on a grid of S (``plan.read_form``), and accumulated into a running total that starts at 0.
- A declared counter (``[[series]]`` with ``select``) is read from raw samples and keeps the real
  sample times: each reporting series' increments are ``b − a``, or ``b`` after a drop (a reset),
  and its first sample is a baseline, not events; the increments are summed by the definition's
  grouping into a running total that starts at 0. A series that began inside the window (its
  first sample more than two of its own sample intervals after the start, and no larger than
  twice its largest increment: a counter that started at 0, such as a publisher's new channel)
  counts its first value too.
- A **turnover** (views ``starts`` and ``stops``) is read from the same raw samples a count is
  made from: the series that started and stopped reporting, so the count is a stock its two
  counters balance exactly. One raw read serves every turnover of one selector.
- The **generated views** of a family are read together, once per aggregation at the finest
  grouping, every family's in few requests (``plan.py``): ``read_many``; so are queries as written
  (declared, or a script's), each a tagged part of a batched read on its grid (``batch.py``). With a ``ReadCache``,
  a window read before is asked for only from where the cache ends (``readcache.py``).
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
from concurrent.futures import ThreadPoolExecutor
from itertools import pairwise

from . import Labels, PastDeadline, Points, Source, SourceError
from .batch import OVER_LIMIT, Part
from .plan import grid_step, kept_run, read_form, shared
from .readcache import ReadCache
from .traffic import resolve
from .transport import TooBig
from .views import Definition, lookback

__all__ = ["grid_step", "read", "read_many"]


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


def accumulate(rows: list[tuple[Labels, Points]], t0: float, step: float) -> list[tuple[Labels, Points]]:
    """Each step's events (``increase`` over it) into a running total from 0, one step before its
    first increase in the window (``t0`` at the earliest: the step at ``t0`` itself covers time
    before the window and is not counted). A counter that began reporting inside the window starts
    there, not at the window's start: a 0 written at the start would read, to discovery, as a
    write followed by a silence until its first sample."""
    out = []
    for labels, pts in rows:
        pts = sorted((t, v) for t, v in pts if t > t0)
        if not pts:
            continue
        total, acc = 0.0, [(max(t0, pts[0][0] - step), 0.0)]
        for t, v in pts:
            total += v
            acc.append((t, total))
        out.append((labels, acc))
    return out


def _kept_select(source: Source, sel: str, a: float, end: float, until: float | None, cache: ReadCache | None,
                 resettle: float) -> list[tuple[Labels, Points]]:
    """Raw samples of ``sel`` in [a, end]; with a cache, only those it does not keep are asked for."""
    if cache is None:
        return source.select(sel, a, end, until=until)
    k = f"s|{sel}"
    if why := cache.refusal(k):
        raise SourceError(why)
    if (sp := cache.plan(k, a, end, 0.0, resettle)) is not None:
        try:
            got = source.select(sel, sp[0], sp[1], until=until)
        except TooBig as e:
            cache.refuse(k, f"{OVER_LIMIT}: {e}")
            raise
        cache.put(k, got, sp[0], sp[1], whole=sp[0] <= a + 1e-6)
    return cache.get(k, a, end)


def _kept_range(source: Source, query: str, a: float, end: float, q: float, until: float | None, cache: ReadCache | None,
                resettle: float) -> list[tuple[Labels, Points]]:
    """``query`` on the grid of ``q`` over [a, end]; with a cache, only what it does not keep."""
    if cache is None:
        return source.query_range(query, a, end, q, until=until)
    k = f"q|{q:g}|{query}"
    if why := cache.refusal(k):
        raise SourceError(why)
    if (sp := cache.plan(k, a, end, q, resettle)) is not None:
        try:
            got = source.query_range(query, sp[0], sp[1], q, until=until)
        except TooBig as e:
            cache.refuse(k, f"{OVER_LIMIT}: {e}")
            raise
        cache.put(k, got, sp[0], sp[1], whole=sp[0] <= a + 1e-6)
    return cache.get(k, a, end)


def _raw(source: Source, d: Definition, start: float, end: float, step: float, until: float | None,
         selects: dict | None = None, cache: ReadCache | None = None, resettle: float = 0.0) -> list[tuple[Labels, Points]]:
    """A definition read on its own: a declared counter or a turnover from raw samples (each
    selector once, through ``selects``), a query as written on discovery's grid."""
    def select(sel: str, a: float) -> list:
        if selects is None:
            return _kept_select(source, sel, a, end, until, cache, resettle)
        if (sel, a) not in selects:
            selects[(sel, a)] = _kept_select(source, sel, a, end, until, cache, resettle)
        return selects[(sel, a)]
    if d.view == "increments":
        res = d.resolution_s or 0.0
        return increments(select(d.query, start - res), d.by_real, start)
    if d.view in ("starts", "stops"):
        w = lookback(d.resolution_s)
        return turnover(select(d.query, start - w), d.by_real, w, start, end, d.view == "stops")
    q = grid_step(step, d.resolution_s)
    return _kept_range(source, d.query, math.floor(start / q) * q, end, q, until, cache, resettle)


def _finish(d: Definition, got: list[tuple[Labels, Points]], prefix: str, machine: str | None,
            producers: dict[str, str] | None) -> list[tuple[str, Labels, Points, dict | None]]:
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


def read_many(source: Source, defs: list[Definition], prefix: str, machine: str | None, start: float, end: float,
              step: float, producers: dict[str, str] | None = None, until: float | None = None,
              concurrency: int = 4, cache: ReadCache | None = None,
              resettle: float = 0.0) -> tuple[dict[str, list[tuple[str, Labels, Points, dict | None]]], dict[str, str]]:
    """Every definition read for the window: the result series by definition id (name, labels,
    points, what it counts when traffic), and why for those that could not be read. ``until``:
    the deadline (``time.monotonic()``), past which no request is made. With a ``cache``
    (``readcache.py``), only what it does not keep of the window is asked for."""
    forms = {d.id: f for d in defs if (f := read_form(d, step)) is not None}
    starts = {q: math.floor(start / q) * q for _, _, q in forms.values()}
    rows, errors = shared(source, defs, forms, starts, end, until, concurrency, cache, resettle) if forms else ({}, {})
    out: dict[str, list] = {}
    out_rows: dict[str, list] = {}
    by_id = {d.id: d for d in defs}
    for i, got in rows.items():
        d = by_id[i]
        if d.agg == "increase":
            got = accumulate(got, starts[forms[i][2]], forms[i][2])
        out[i] = _finish(d, got, prefix, machine, producers)
    written = [d for d in defs if d.id not in forms and d.view not in ("increments", "starts", "stops") and d.query]
    if written:                              # queries as written: together too, each a part on its own grid
        by_q: dict[float, list[Part]] = {}
        for d in written:
            by_q.setdefault(grid_step(step, d.resolution_s), []).append(Part(d.id, d.query, max(1, d.est_series or d.touched or 1)))
        for q, parts in by_q.items():
            got, bad = kept_run(source, parts, math.floor(start / q) * q, end, q, until, concurrency, cache, resettle)
            for i, rows_of in got.items():
                out_rows[i] = rows_of
            errors.update(bad)
    selects: dict = {}
    alone = [d for d in defs if d.id not in forms and d.id not in out_rows and d.id not in errors]

    def one(d: Definition):
        try:
            return d.id, _finish(d, _raw(source, d, start, end, step, until, selects, cache, resettle), prefix, machine, producers), None
        except SourceError as e:
            return d.id, None, e
    with ThreadPoolExecutor(max(1, concurrency)) as pool:
        for i, got, e in pool.map(one, alone):
            if e is not None:
                errors[i] = str(e) if not isinstance(e, PastDeadline) else f"late: {e}"
            else:
                out[i] = got
    for i, got in out_rows.items():
        out[i] = _finish(by_id[i], got, prefix, machine, producers)
    return out, errors


def read(source: Source, d: Definition, prefix: str, machine: str | None, start: float, end: float,
         step: float, producers: dict[str, str] | None = None, until: float | None = None) -> list[tuple[str, Labels, Points, dict | None]]:
    """One definition's result series (``read_many``); raises ``SourceError`` when it fails."""
    out, errors = read_many(source, [d], prefix, machine, start, end, step, producers, until, 1)
    if d.id in errors:
        err = errors[d.id]
        raise (PastDeadline if err.startswith("late: ") else SourceError)(err.removeprefix("late: "))
    return out.get(d.id, [])
