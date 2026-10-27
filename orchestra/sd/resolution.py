"""Each series' real resolution, and how it is read between its points.

A series is known only at its real points. How often those come is its **resolution**: the usual
gap between them. A count or a state (a counter, or a level that only takes whole values: orders
by state, pods, people in a line) is read with its last value held, because it stays what it was
until it is written again; its real points are all its writes, a repeat included (the shelf still
holds three), and a count written only when it changes (no schedule) is as fine as its events. A
smooth measurement (a temperature, a price, a load: any value that is not whole) is read linearly
between its real points; a repeat of the value it had is the same observation polled again, not
a new one, so its real points are those where it changed. A feed that changes every half hour,
polled every minute, then has a resolution of half an hour, not a minute. The choice is made per
series and recorded (``Resolution``), and a resolution a source declared (a remote store's
reporting interval) is a floor.

Discovery uses the resolution three ways (``sd.discover``): a level slower than the grid is
balanced on the stretches between its writes (``blocks``), not on every step; a driver slower
than the grid needs as many of its own intervals holding a flow's events as a form needs events
(``intervals_with``); and a level's net flow is fitted on a grid no finer than every series it
reads (``sd.netflow``)."""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
from itertools import pairwise
from statistics import median

from .live import usual_interval

HOLD, LINEAR = "hold", "linear"
SLOW = 1.5          # a series is slower than the grid when its resolution is this many steps or more


@dataclass(frozen=True)
class Resolution:
    seconds: float | None      # the usual gap between real points; None: written as things happen, as fine as its events
    read: str                  # HOLD (counts and states) or LINEAR (smooth measurements)

    def record(self) -> dict:
        return {"resolution_s": None if self.seconds is None else round(self.seconds, 3), "read": self.read}


def whole(points: list[tuple[float, float]]) -> bool:
    """Every value a whole number: a count or a state."""
    return all(float(v).is_integer() for _, v in points)


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
    read = HOLD if counter or whole(points) else LINEAR
    seconds: float | None
    if read == HOLD:
        seconds = None if on_events else usual_interval(points)
    else:
        real = real_points(points, read)
        gaps = [b - a for (a, _), (b, _) in pairwise(real)]
        seconds = median(gaps) if len(gaps) >= 2 else usual_interval(points)
    if declared:
        seconds = max(seconds or 0.0, float(declared))
    return Resolution(seconds, read)


def interpolate(points: list[tuple[float, float]], times: list[float]) -> list[float | None]:
    """A measurement's value at each time, linear between its real points: before its first point
    nothing (None), after its last the last value."""
    real = real_points(points, LINEAR)
    out: list[float | None] = []
    j = 0
    for t in times:
        while j < len(real) and real[j][0] <= t:
            j += 1
        if j == 0:
            out.append(None)
        elif j == len(real):
            out.append(real[-1][1])
        else:
            (t0, v0), (t1, v1) = real[j - 1], real[j]
            out.append(v0 + (v1 - v0) * (t - t0) / (t1 - t0) if t1 > t0 else v1)
    return out


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


def pick(ser, unit) -> float:
    """A series' change over one unit: a step, or a stretch between a slow level's writes. Over a
    stretch, a counter's is what it counted between the two writes, from its own points; any
    other series' is the sum of its changes over the stretch's steps."""
    if isinstance(unit, int):
        return ser.deltas[unit]
    if ser.counter and ser.points and ser.points[0][0] <= unit.after:
        return counted_between(ser, unit.after, unit.until)
    return sum(ser.deltas[i] for i in unit.steps)


def intervals_with(events: list[tuple[float, float]], start: float, width: float) -> int:
    """How many intervals of ``width`` from ``start`` hold at least one of the events: at a
    driver's resolution, the events within one of its intervals are one observation of it."""
    return len({int((t - start) // width) for t, _ in events})
