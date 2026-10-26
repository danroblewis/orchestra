"""When a series was live: the stretches in which its machine was alive and it had been written
since, and the grid steps that fall inside them.

Liveness is the machine's, not the series'. A machine is alive between writes (any of its series,
or Orchestra's count of an event it published) no further apart than its live limit: ten times
the interval of its fastest series written on a schedule (its heartbeat; at least a minute). A
longer silence is the machine down, or not started yet. A machine none of whose series is on a
schedule writes only when something happens, so its silence says nothing about it, and it is taken
to be alive from its first write to the end of the window.

A gauge that is not re-written because nothing changed holds its last value for as long as its
machine is alive: a count of tickets by state is written when a ticket moves, and in a quiet
quarter of an hour it is still the count. It goes stale only when its machine goes silent: the
value from before a silence is not carried past it (a machine restarted with a cleared state
re-writes its gauges), so a gauge is live from its first write in each stretch its machine was
alive to the end of that stretch. A counter is live whenever its machine is: before its first write
it had counted nothing. Carrying a value through a machine's silence would read as "nothing
happened" (for a level: no change, so no flow; for a counter: no events), which is false, so the
silence is cut: a stock's balance and a flow's fit use only the steps when the level and the
counters involved were all live."""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from itertools import pairwise

GAP_FACTOR, MIN_GAP_S = 10.0, 60.0
LOOKBACK_S = 3600.0        # writes this long before the window still say whether a machine was alive at its start


def usual_interval(points: list[tuple[float, float]]) -> float | None:
    """The interval a series is written on when it is on a schedule (a machine's own metrics, a
    heartbeat): most gaps between writes within half and twice the usual one. None for a series
    written as things happen (a count of tickets by state, written at every move: a burst of writes
    seconds apart, then minutes of nothing), whose silences say nothing about whether anything was
    running."""
    ts = [t for t, _ in points[-2000:]]
    if len(ts) < 10:
        return None
    gaps = sorted(b - a for a, b in pairwise(ts))
    med = gaps[len(gaps) // 2]
    return med if med > 0 and sum(1 for g in gaps if 0.5 * med <= g <= 2 * med) >= 0.8 * len(gaps) else None


def regular(points: list[tuple[float, float]]) -> bool:
    """Written on a schedule (``usual_interval``)."""
    return usual_interval(points) is not None


def live_limit(interval: float) -> float:
    """How long a machine written on this interval may be silent and still be alive."""
    return max(MIN_GAP_S, GAP_FACTOR * interval)


def stretches(times: list[float], limit: float | None, start: float, end: float) -> list[tuple[float, float]]:
    """The stretches of [start, end] in which writes at ``times`` (sorted) came no further apart
    than ``limit``, and to the end when the last write is within the limit of it. With no limit,
    one stretch from the first write to the end. A lone write after a silence starts a stretch of
    its own; it does not bridge the silence."""
    ts = [t for t in times if start - LOOKBACK_S <= t <= end]
    if not ts:
        return []
    if limit is None:
        out = [(ts[0], end)]
    else:
        out = []
        for t in ts:
            if out and t - out[-1][1] <= limit:
                out[-1] = (out[-1][0], t)
            else:
                out.append((t, t))
        if end - out[-1][1] <= limit:
            out[-1] = (out[-1][0], end)
    clipped = [(max(a, start), min(b, end)) for a, b in out]
    return [(a, b) for a, b in clipped if b > a]


def live_intervals(points: list[tuple[float, float]], start: float, end: float) -> list[tuple[float, float]]:
    """A machine-less series' own live stretches, from its own schedule."""
    u = usual_interval(points)
    return stretches([t for t, _ in points], live_limit(u), start, end) if u else [(start, end)]


def held(points: list[tuple[float, float]], alive: list[tuple[float, float]], start: float, end: float
         ) -> list[tuple[float, float]]:
    """A gauge's live stretches: from its first write in each stretch its machine was alive to the
    end of that stretch. Its value from before the machine's silence is not carried past it."""
    ts = [t for t, _ in points]
    out = []
    for a, b in alive:
        i = bisect_left(ts, a - 1e-9)
        if i < len(ts) and ts[i] < b:
            lo, hi = max(ts[i], start), min(b, end)
            if hi > lo:
                out.append((lo, hi))
    return out


def held_for(points: list[tuple[float, float]], live: list[tuple[float, float]]) -> tuple[float, float]:
    """How long a gauge's value was carried on its machine's word rather than its own: the time
    inside ``live`` since a write more than ``MIN_GAP_S`` ago, in all and at the end of its last
    stretch (seconds)."""
    ts = [t for t, _ in points]
    total = at_end = 0.0
    for a, b in live:
        for x, y in pairwise([a, *[t for t in ts if a < t <= b], b]):
            if y - x > MIN_GAP_S:
                total += y - x
                if (a, b) == live[-1] and y == b:
                    at_end = y - x
    return total, at_end


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
    """The steps a level's balance may use: those in which the level and every counter were live
    (a series whose ``live`` is None is always live). The level's stale value from before a
    silence, and a counter's jump or reset when its machine came back, fall outside, so neither
    reads as a change the balance must explain."""
    steps = None
    for ser in [level, *counters]:
        if ser.live is not None:
            steps = set(ser.live) if steps is None else steps & set(ser.live)
    return list(range(len(level.values) - 1)) if steps is None else sorted(steps)
