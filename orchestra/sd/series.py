"""The series discovery works on: every series of a project sampled onto a grid of steps, told
apart as a counter or a level, a machine's instances summed into one counter, and each marked
with when it was being written (``sd.live``)."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from itertools import pairwise

from ..metrics import step_sample
from .live import live_intervals, regular, steps_within, union

EVENT_COUNTER = "orchestra_events_total"   # Orchestra's own count of each event type, by source


def series_key(name: str, labels: dict[str, str]) -> str:
    """A series' identity in a discovery: its name and every label but the project (the machine
    included: two machines' series of one name are two series)."""
    inner = ",".join(f'{k}="{v}"' for k, v in sorted(labels.items()) if k != "project")
    return f"{name}{{{inner}}}" if inner else name


@dataclass
class Series:
    name: str
    labels: dict[str, str]
    points: list[tuple[float, float]]
    values: list[float]                     # at each grid time
    counter: bool
    members: list = field(default_factory=list)   # the instances' series, when this one sums them (sum_instances)
    intervals: list[tuple[float, float]] | None = None   # when it was being written; None: not on a schedule, so always
    live: list[int] | None = None                        # the grid steps inside those intervals; None: every step

    @property
    def key(self) -> str:
        return series_key(self.name, self.labels)

    @property
    def deltas(self) -> list[float]:
        """Change per step; for a counter, a drop is a reset (as in Prometheus): the new value is
        what was counted since."""
        if self.counter:
            return [(b - a) if b >= a else b for a, b in pairwise(self.values)]
        return [b - a for a, b in pairwise(self.values)]


def _is_counter(name: str, values: list[float]) -> bool:
    """Named like a counter, and never falls except for the odd reset (a machine restarting)."""
    drops = sum(1 for a, b in pairwise(values) if b < a)
    return name.endswith("_total") and drops <= max(2, len(values) // 100)


def on_events(points: list[tuple[float, float]]) -> bool:
    """Written only when it moves, as Orchestra's event counters are (the collector writes a count
    when an event arrives): consecutive points never repeat a value. A machine's own counter,
    written on a schedule, repeats its value between events."""
    pairs = list(pairwise(v for _, v in points[-2000:]))
    return bool(pairs) and sum(1 for a, b in pairs if a == b) <= 0.05 * len(pairs)


def mark_live(ser: Series, start: float, step: float, n: int) -> Series:
    """Record when the series was being written: only a scheduled series' silence means its
    machine was down. A counter written on events is silent when nothing happened, even when the
    events come steadily enough to look like a schedule."""
    if regular(ser.points) and not (ser.counter and on_events(ser.points)):
        ser.intervals = live_intervals(ser.points, start, start + n * step)
        ser.live = steps_within(ser.intervals, start, step, n)
    return ser


def sample(dump, start: float, step: float, n: int) -> list[Series]:
    """Every series on the grid; leading steps before its first point take its first value."""
    out = []
    times = [start + i * step for i in range(n + 1)]
    for name, labels, pts in dump:
        if not pts:
            continue
        got = dict(step_sample(pts, start, times[-1], step))
        first = next((v for t, v in pts if t >= start), pts[-1][1])
        vals, last = [], None
        for t in times:
            last = got.get(t, last)
            vals.append(first if last is None else last)
        out.append(mark_live(Series(name, dict(labels), pts, vals, _is_counter(name, vals)), start, step, n))
    return out


def sum_instances(series: list[Series]) -> tuple[list[Series], dict[str, str]]:
    """Counters that differ only by instance, summed into one per machine.

    A model is about machines, not their instances: six workers' counts of one event are one flow.
    Counting each instance apart multiplies the candidates a balance is chosen from (on a busy
    system, past the number of steps, where least squares can no longer tell them apart). An
    instance is an ``instance`` label, or the instance part of a ``source`` (``worker/3``).
    Increments are summed, so one instance's reset does not read as the total going back. The sum
    was being written whenever any instance was. Returns the series, and what each summed series
    was made from (for the record)."""
    groups: dict[tuple, list[Series]] = defaultdict(list)
    out: list[Series] = []
    for ser in series:
        src = ser.labels.get("source") or ""
        if not ser.counter or ("instance" not in ser.labels and "/" not in src):
            out.append(ser)
            continue
        labels = {k: v for k, v in ser.labels.items() if k != "instance"}
        if "/" in src:
            labels["source"] = src.partition("/")[0]
        groups[(ser.name, tuple(sorted(labels.items())))].append(ser)
    made: dict[str, str] = {}
    for (name, labels), members in groups.items():
        if len(members) == 1 and "/" not in (members[0].labels.get("source") or "") and "instance" not in members[0].labels:
            out.append(members[0])
            continue
        n = len(members[0].values)
        steps = [sum((b - a) if b >= a else b for a, b in ((m.values[i], m.values[i + 1]) for m in members)) for i in range(n - 1)]
        values, total = [0.0], 0.0
        for d in steps:
            total += d
            values.append(total)
        incs = []                                        # every instance's increments, in time order
        for m in members:
            for (t0, a), (t1, b) in pairwise(m.points):
                incs.append((t1, (b - a) if b >= a else b))
        incs.sort()
        points, total = [], 0.0
        if members[0].points:
            points.append((min(m.points[0][0] for m in members if m.points), 0.0))
        for t, d in incs:
            total += d
            points.append((t, total))
        merged = Series(name, dict(labels), points, values, True, members)
        if all(m.intervals is not None for m in members):
            merged.intervals = union([iv for m in members for iv in m.intervals])
            merged.live = sorted({i for m in members for i in m.live})
        out.append(merged)
        made[merged.key] = f"summed over {len(members)} instance{'s' if len(members) != 1 else ''}"
    return out, made
