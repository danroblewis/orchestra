"""Each series' real resolution, and how it is read between its points.

A series is known only at its points. How often its value changes is its **resolution**: the
usual gap between the points where it changed. Every series is read with its last value held
until it is written again: a count or a state stays what it was, and so does a measurement, as far
as anything observed says. A measurement is not drawn as a line between the points where it changed
(the rule until 2026-10-28): a gauge written every 30 s that changed twice in an hour was read as two
long ramps, which any counter that rose steadily matched, and its balance was judged on the two
stretches between its changes, at R² 1.000 whatever the counters were (the metrics lab, review r1
F3 and F9). A repeat of the value it had is an observation that nothing changed, not a gap to fill.
How the series is read and how fine it is are separate questions.

Every write is a real point only of a counter, and of a level written as things happen: no
schedule (``sd.live.usual_interval`` finds none in at least ``ENOUGH`` writes: bursts, then
silences) and its value changed at most of them (a write because something moved). Such a series
is as fine as its events. A level written on a schedule, whole or not, is resolved by its
changes: a repeat of the value it had is the same observation polled again, so its resolution is
the usual (median) gap between the points where it changed. A feed that changes every half hour,
polled every minute, then has a resolution of half an hour, not a minute, whether its values are
whole (a power demand in MW, an air quality index, a count of flights) or not; a count polled every
second that changes every few seconds keeps a resolution of a few seconds. A level with too few
writes to show a schedule (an hourly measurement in a few hours' window) is resolved from its
changes when it changed at least twice, and, if its values are whole, at steady gaps (``steady``):
a few writes of a count in a burst and a silence are things happening, as fine as they are. The
choice is made per series and recorded (``Resolution``), and a resolution a source declared (a
remote store's reporting interval) is a floor.

Discovery uses the resolution three ways (``sd.discover``): a level written less often than the
grid is balanced on the stretches between its writes (``blocks``, ``observed_every``), not on
every step, and never on the stretches between its changes, which are no observations; a driver slower
than the grid needs as many of its own intervals holding a flow's events as a form needs events
(``intervals_with``); and a level's net flow is fitted on a grid no finer than every series it
reads (``sd.netflow``)."""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
from itertools import pairwise
from statistics import median

from .live import usual_interval

HOLD, LINEAR = "hold", "linear"     # how a series is read (always HOLD); LINEAR names a measurement's changes (``real_points``)
SLOW = 1.5          # a series is slower than the grid when its resolution is this many steps or more
ENOUGH = 10         # writes it takes to tell a schedule from writes as things happen (``sd.live.usual_interval``)
RESAMPLED = 4.5     # a series that moves steadily every 2 to 4 reads is a coarser store's samples read again (``counted_every``)


@dataclass(frozen=True)
class Resolution:
    seconds: float | None      # the usual gap between real points; None: written as things happen, as fine as its events
    read: str                  # HOLD: every series is read with its last value held

    def record(self) -> dict:
        return {"resolution_s": None if self.seconds is None else round(self.seconds, 3), "read": self.read}


def whole(points: list[tuple[float, float]]) -> bool:
    """Every value a whole number: a count or a state."""
    return all(float(v).is_integer() for _, v in points)


def steady(gaps: list[float]) -> bool:
    """Gaps that keep a schedule: most within half and twice the usual one (as
    ``sd.live.usual_interval`` judges writes), not a burst and a silence."""
    med = median(gaps)
    return med > 0 and sum(1 for g in gaps if 0.5 * med <= g <= 2 * med) >= 0.8 * len(gaps)


def real_points(points: list[tuple[float, float]], read: str) -> list[tuple[float, float]]:
    """The points that are observations: every write of a count or a state; of a measurement,
    the first and each that differs from the one before."""
    if read == HOLD or not points:
        return list(points)
    out = [points[0]]
    for t, v in points[1:]:
        if v != out[-1][1]:
            out.append((t, v))
    return out


def measure(points: list[tuple[float, float]], counter: bool, declared: float | None = None,
            on_events: bool = False) -> Resolution:
    """A series' resolution and read. ``declared``: a resolution its source reported, a floor;
    ``on_events``: a counter written only when it moves (no schedule)."""
    smooth = not counter and not whole(points)      # a measurement, not a count: its changes say its resolution
    interval = usual_interval(points)
    seconds: float | None
    if counter:
        seconds = None if on_events else (counted_every(points, interval) or interval)
    elif not smooth and interval is None and len(points) >= ENOUGH and 2 * len(real_points(points, LINEAR)) > len(points):
        seconds = None                  # a count written as things happen: every write is one
    else:
        changes = [b - a for (a, _), (b, _) in pairwise(real_points(points, LINEAR))]
        enough = len(changes) >= 2 and (smooth or len(points) >= ENOUGH or steady(changes))
        seconds = median(changes) if enough else interval
    if declared:
        seconds = max(seconds or 0.0, float(declared))
    return Resolution(seconds, HOLD)


def counted_every(points: list[tuple[float, float]], interval: float | None) -> float | None:
    """How often a series on a schedule is really sampled: the usual gap between the points where it
    moved, when it moves steadily (``steady``) every two to four writes (``RESAMPLED``). A store read
    on a finer grid than its scrape repeats each sample (a counter scraped every minute, read every
    30 s, holds its value for one read and doubles the next; a stock level too), and so does a
    store that reports once a minute: its counts arrive a minute at a time, and between them
    nothing was observed, not nothing counted. None when it moves at nearly every write, as things
    happen (gaps that keep no schedule: a counter of rare events is as fine as its writes), or
    seldom (a gauge polled every 30 s that changes every half hour is observed at every poll)."""
    if not interval:
        return None
    moved = [t for (_, a), (t, b) in pairwise(points[-2000:]) if b != a]
    gaps = [b - a for a, b in pairwise(moved)]
    if len(gaps) < ENOUGH or not steady(gaps):
        return None
    usual = median(gaps)
    return usual if SLOW * interval <= usual <= RESAMPLED * interval else None


def moved_points(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """A counter's observations when it counts more seldom than it is written (``counted_every``):
    every point where it moved; the repeats between are the same reading again. Its first point is
    none: it may be a reading from before the window, repeated, so when it was counted is unknown."""
    return [(t, b) for (_, a), (t, b) in pairwise(points) if b != a]


def observed_every(points: list[tuple[float, float]], res: Resolution, declared: float | None = None) -> float | None:
    """How far apart a level's observations are, for its balance (``blocks``): its writes, a repeat
    included (the shelf still holds three; the gauge still reads 4.2), on the interval it is written
    on, however seldom it changes. The stretches between its changes are no observations: a level
    polled every 30 s that changed twice in an hour was seen 120 times, not twice."""
    seconds = usual_interval(points)
    return max(seconds or 0.0, float(declared)) if declared else seconds


def steps_of(seconds: float | None, step: float) -> int:
    """How many grid steps a series' resolution spans: 1 for one as fine as the grid."""
    if not seconds or seconds < SLOW * step:
        return 1
    return max(1, round(seconds / step))


@dataclass(frozen=True)
class Block:
    """A stretch of grid steps between two writes of a slow level, and the writes' times."""

    steps: tuple[int, ...]
    after: float           # the write that opens it (excluded)
    until: float           # the write that closes it (included)


def block_ends(points: list[tuple[float, float]], start: float, step: float, n: int) -> list[tuple[int, float]]:
    """The grid steps in which a slow level was written, with the time of the write: on a grid of
    steps (step ``i`` ends at ``start + (i + 1) × step``, where a held value is read), each write's
    change shows in the step it falls in. The last write in a step closes it."""
    out: dict[int, float] = {}
    for t, _ in points:
        i = int((t - start) // step)
        if 0 <= i < n:
            out[i] = t
    return sorted(out.items())


def units(blocks: list[tuple[int, float]] | None, steps: list[int]) -> list:
    """``steps`` as the units a balance is judged on: each step, for a level as fine as the grid
    (``blocks`` None); for a slow one, the stretches from one of its writes to the next
    (``Block``), each kept only when every step in it is among ``steps``. Its change between two
    writes is then compared with what the counters counted between those two instants, where on
    single steps it would show only in the step of the write, after the counters had counted it
    in the steps before."""
    if blocks is None:
        return steps
    have = set(steps)
    out, prev = [], None
    for e, t in blocks:
        if prev is not None:
            block = tuple(range(prev[0] + 1, e + 1))
            if block and all(i in have for i in block):
                out.append(Block(block, prev[1], t))
        prev = (e, t)
    return out


def counted_between(ser, a: float, b: float) -> float:
    """What a counter counted after ``a`` and up to ``b``, from its raw points (its increments; a
    drop is a reset, and the new value was counted since). The running total of increments is
    worked out once per series."""
    cached = ser.__dict__.get("_counted")
    if cached is None or cached[0] is not ser.points:
        times, totals, total, prev = [], [], 0.0, None
        for t, v in ser.points:
            if prev is not None:
                total += v - prev if v >= prev else v
            times.append(t)
            totals.append(total)
            prev = v
        cached = ser.__dict__["_counted"] = (ser.points, times, totals)
    _, times, totals = cached

    def at(t: float) -> float:
        i = bisect_right(times, t) - 1
        return totals[i] if i >= 0 else 0.0
    return at(b) - at(a)


def value_at(ser, t: float) -> float:
    """A level's value at ``t``, from its own points, its last value held."""
    cached = ser.__dict__.get("_times")
    if cached is None or cached[0] is not ser.points:
        cached = ser.__dict__["_times"] = (ser.points, [x for x, _ in ser.points])
    i = bisect_right(cached[1], t) - 1
    return ser.points[max(0, i)][1]


def pick(ser, unit) -> float:
    """A series' change over one unit: a step, or a stretch between two writes of a slow series
    (``Block``). Over a stretch, each series is read at the stretch's two instants from its own
    points: a counter's change is what it counted between them; a level's, its value at the second
    less its value at the first (the slow level's own writes, or a fast level read where a slow
    counter was). A series with no points of its own (a residual) sums its changes over the steps."""
    if isinstance(unit, int):
        return ser.deltas[unit]
    if ser.points and ser.points[0][0] <= unit.after:
        if ser.counter:
            return counted_between(ser, unit.after, unit.until)
        return value_at(ser, unit.until) - value_at(ser, unit.after)
    return sum(ser.deltas[i] for i in unit.steps)


def intervals_with(events: list[tuple[float, float]], start: float, width: float) -> int:
    """How many intervals of ``width`` from ``start`` hold at least one of the events: at a
    driver's resolution, the events within one of its intervals are one observation of it."""
    return len({int((t - start) // width) for t, _ in events})
