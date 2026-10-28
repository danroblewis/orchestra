"""The schema's reads of samples, batched across families (``batch.py``), so a tenant of hundreds
of metrics is read in tens of requests, not thousands.

- ``raw``: the raw samples of a few series of each family over the window (its interval and
  behaviour), several small families in one read.
- ``history``: the same series coarsely (every ``history / HISTORY_POINTS``) over the source's
  ``history`` (a day by default), for the families the window cannot judge: one that only rose
  in it may be a queue that fills in incidents and drains otherwise, or a counter that resets
  once a day.
- ``extremes``: the least and largest value of every series of the families whose samples are all
  1 (an info metric must be 1 throughout).
- ``churn``: for each family, which values of its labels report in the window and at
  ``CHURN_POINTS`` moments of it, from two queries per batch of families: values seen
  (``count by (L…) (count_over_time(…[window]))``) and values reporting at each moment
  (``count by (L…) (last_over_time(…[R]))``). A label's churn is the share of its values seen that
  is not reporting at an average moment.
- ``grid``: each series of a family on ``DUPLICATE_POINTS`` points of the window, for duplicates.

Every function returns what it read by family name and, separately, the families it could not
read and why: the caller decides what an unread family is (``schema.py``)."""

from __future__ import annotations

from . import Labels, Points, Source
from .batch import Part, run, select_many
from .checks import CHURN_POINTS, DUPLICATE_POINTS
from .family import lookback

HISTORY_POINTS = 288


def raw(source: Source, picks: dict[str, tuple[str, int]], start: float, end: float, until: float | None,
        concurrency: int) -> tuple[dict[str, list[Points]], dict[str, str]]:
    """``picks``: key -> (selector, series): each key's raw samples in the window, sorted."""
    sel_of: dict[str, list[str]] = {}
    for k, (sel, _) in picks.items():
        sel_of.setdefault(sel, []).append(k)
    got, failed = select_many(source, [(sel, picks[ks[0]][1]) for sel, ks in sel_of.items()], start, end, until, concurrency)
    out: dict[str, list[Points]] = {}
    bad: dict[str, str] = {}
    for sel, ks in sel_of.items():
        for k in ks:
            if sel in failed:
                bad[k] = failed[sel]
            else:
                out[k] = [sorted(pts) for _, pts in got.get(sel, []) if pts]
    return out, bad


def history(source: Source, picks: dict[str, tuple[str, int]], end: float, span: float, until: float | None,
            concurrency: int) -> tuple[dict[str, list[Points]], dict[str, str]]:
    """Each key's picked series every ``span / HISTORY_POINTS`` over ``[end - span, end]``."""
    step = max(60.0, span / HISTORY_POINTS)
    got, failed = run(source, [Part(k, sel, max(1, n)) for k, (sel, n) in picks.items()], end - span, end, step, until, concurrency)
    return {k: [sorted(p) for _, p in rows if p] for k, rows in got.items()}, failed


def extremes(source: Source, sels: dict[str, tuple[str, int]], start: float, end: float, until: float | None,
             concurrency: int) -> tuple[dict[str, tuple[float | None, float | None]], dict[str, str]]:
    """Each key's least and largest value over the window, of every series its selector names."""
    w = f"{int(end - start) + 1}s"
    parts = [Part((k, "min"), f"min(min_over_time({sel}[{w}]))", n) for k, (sel, n) in sels.items()]
    parts += [Part((k, "max"), f"max(max_over_time({sel}[{w}]))", n) for k, (sel, n) in sels.items()]
    got, failed = run(source, parts, end, end, 60.0, until, concurrency)
    out, bad = {}, {}
    for k in sels:
        if (k, "min") in failed or (k, "max") in failed:
            bad[k] = failed.get((k, "min")) or failed[(k, "max")]
            continue
        one = lambda rows: rows[0][1][-1][1] if rows and rows[0][1] else None
        out[k] = (one(got.get((k, "min"))), one(got.get((k, "max"))))
    return out, bad


def churn(source: Source, asks: dict[str, tuple[str, list[str], float | None, int]], start: float, end: float,
          until: float | None, concurrency: int) -> tuple[dict[str, dict[str, tuple[int, float]]], dict[str, str]]:
    """``asks``: key -> (selector, real labels, resolution, series). For each key and label: how
    many values report in the window, and the share of them not reporting at an average moment."""
    w = int(end - start) + 1
    seen_parts = [Part(k, f"count by ({', '.join(ls)}) (count_over_time({sel}[{w}s]))", n) for k, (sel, ls, _, n) in asks.items()]
    seen, failed = run(source, seen_parts, end, end, 60.0, until, concurrency)
    by_step: dict[float, list[Part]] = {}
    for k, (sel, ls, res, n) in asks.items():
        r = lookback(res)
        step = max(float(r), (end - start) / CHURN_POINTS)
        by_step.setdefault(step, []).append(Part(k, f"count by ({', '.join(ls)}) (last_over_time({sel}[{r}s]))", n))
    now: dict = {}
    for step, parts in by_step.items():
        got, bad = run(source, parts, start + step, end, step, until, concurrency)
        now.update({k: (step, rows) for k, rows in got.items()})
        failed.update(bad)
    out: dict[str, dict[str, tuple[int, float]]] = {}
    for k, (_, ls, _, _) in asks.items():
        if k in failed or k not in seen or k not in now:
            failed.setdefault(k, "not read")
            continue
        step, rows = now[k]
        steps = max(1, int((end - start - step) // step) + 1)
        out[k] = {}
        for lab in ls:
            distinct = len({r.get(lab) for r, _ in seen[k] if r.get(lab) is not None})
            if distinct <= 1:
                out[k][lab] = (distinct, 0.0)
                continue
            at: dict[float, set] = {}
            for r, pts in rows:
                if r.get(lab) is not None:
                    for t, v in pts:
                        if v > 0:
                            at.setdefault(t, set()).add(r[lab])
            present = sum(len(v) for v in at.values()) / steps
            out[k][lab] = (distinct, round(max(0.0, 1.0 - present / distinct), 3))
    return out, failed


def grid(source: Source, sels: dict[str, tuple[str, float | None, int]], start: float, end: float, until: float | None,
         concurrency: int) -> tuple[dict[str, list[tuple[Labels, list[float | None]]]], dict[str, str]]:
    """``sels``: key -> (selector, resolution, series): each series on ``DUPLICATE_POINTS`` points."""
    step = max(1.0, (end - start) / (DUPLICATE_POINTS - 1))
    parts = [Part(k, f"last_over_time({sel}[{lookback(res)}s])", n) for k, (sel, res, n) in sels.items()]
    got, failed = run(source, parts, start, end, step, until, concurrency)
    points = [start + i * step for i in range(DUPLICATE_POINTS)]
    out = {}
    for k, rows in got.items():
        out[k] = []
        for lab, pts in rows:
            at = dict(pts)
            out[k].append((lab, [next((at[t] for t in at if abs(t - g) < step / 2), None) for g in points]))
    return out, failed
