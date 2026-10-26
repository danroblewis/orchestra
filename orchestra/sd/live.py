"""When a series was being written: the live intervals of a series written on a schedule, and the
grid steps that fall inside them.

A series written every second that then says nothing for an hour was not measuring anything in
that hour: its machine was down, or not started yet. Carrying its last value through the silence
would read as "nothing happened" (for a level: no change, so no flow; for a counter: no events),
which is false, and the first fresh value after the silence would read as one big change that no
counter explains. So the silence is cut: a stock's balance and a flow's fit use only the steps when
the level and the counters involved were all being written."""

from __future__ import annotations

from bisect import bisect_right
from itertools import pairwise

GAP_FACTOR, MIN_GAP_S = 10.0, 60.0


def live_intervals(points: list[tuple[float, float]], start: float, end: float) -> list[tuple[float, float]]:
    """When a series written on a schedule was being written: between consecutive points no further
    apart than ten times its usual interval (at least a minute). A longer silence is missing data (its machine was down
    or cut off), not a measurement: carrying the last value through it would read as "nothing
    happened at this level", which is false."""
    ts = [t for t, _ in points if start - 3600 <= t <= end]
    if len(ts) < 2:
        return []
    gaps = sorted(b - a for a, b in pairwise(ts))
    limit = max(MIN_GAP_S, GAP_FACTOR * gaps[len(gaps) // 2])
    out: list[tuple[float, float]] = []
    for a, b in pairwise(ts):
        if b - a > limit:
            continue
        a, b = max(a, start), min(b, end)
        if b <= a:
            continue
        if out and a <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], b))
        else:
            out.append((a, b))
    if out and ts[-1] >= end - limit:                 # still being written at the end of the window
        out[-1] = (out[-1][0], end)
    return out


def regular(points: list[tuple[float, float]]) -> bool:
    """Written on a schedule (most intervals near the usual one), as a machine's own metrics are.
    A series written only when something happens (Orchestra's event counters) is not: its
    silences mean nothing happened, so they say nothing about whether anything was running."""
    ts = [t for t, _ in points[-2000:]]
    if len(ts) < 10:
        return False
    gaps = sorted(b - a for a, b in pairwise(ts))
    med = gaps[len(gaps) // 2]
    return med > 0 and sum(1 for g in gaps if g <= 3 * med) >= 0.8 * len(gaps)


def intersect(a: list[tuple[float, float]], b: list[tuple[float, float]]) -> list[tuple[float, float]]:
    out, i, j = [], 0, 0
    while i < len(a) and j < len(b):
        lo, hi = max(a[i][0], b[j][0]), min(a[i][1], b[j][1])
        if lo < hi:
            out.append((lo, hi))
        if a[i][1] < b[j][1]:
            i += 1
        else:
            j += 1
    return out


def union(intervals: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """The intervals as one sorted list with the overlaps joined."""
    out: list[tuple[float, float]] = []
    for a, b in sorted(intervals):
        if out and a <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], b))
        else:
            out.append((a, b))
    return out


def within(t: float, live: list[tuple[float, float]]) -> bool:
    i = bisect_right([a for a, _ in live], t) - 1
    return i >= 0 and live[i][0] < t <= live[i][1]


def steps_within(intervals: list[tuple[float, float]], start: float, step: float, n: int) -> list[int]:
    """The grid steps (of ``n`` from ``start``) that lie whole inside one of the intervals: the
    steps in which a change of the series is a measured change."""
    return [i for i in range(n) if any(a <= start + i * step and start + (i + 1) * step <= b for a, b in intervals)]


def balance_steps(level, counters: list) -> list[int]:
    """The steps a level's balance may use: those in which the level and every counter were being
    written (a series not written on a schedule, ``live`` None, is always live). The level's stale
    value from before a silence, and a counter's jump or reset when its machine came back, fall
    outside, so neither reads as a change the balance must explain."""
    steps = None
    for ser in [level, *counters]:
        if ser.live is not None:
            steps = set(ser.live) if steps is None else steps & set(ser.live)
    return list(range(len(level.values) - 1)) if steps is None else sorted(steps)
