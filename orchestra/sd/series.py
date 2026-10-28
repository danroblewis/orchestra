"""The series discovery works on: every series of a project sampled onto a grid of steps, told
apart as a counter or a level, a machine's instances summed into one counter, and each marked
with when it was live (``sd.live``: its writer alive, and a gauge written since the writer's
last silence). A series' writer is who put it in the store (``writer_of``: an instrument, or a
machine writing its own), which says when it was measured, never which machine sets it."""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from itertools import pairwise

from ..metrics import step_sample
from .live import (
    before_first_write,
    held,
    live_intervals,
    live_limit,
    steps_within,
    stretches,
    union,
    usual_interval,
)
from .resolution import (
    Resolution,
    block_ends,
    measure,
    observed_every,
    real_points,
    steps_of,
)

EVENT_COUNTER = "orchestra_events_total"   # Orchestra's own count of each event type, by source
PLUMBING = re.compile(r"^orchestra_(?!events_total)")   # Orchestra's own other series (the host's, the Core page's probes): never a measure of the system
OWN = re.compile(r"^orchestra_(host_|core_|collect_)|^orchestra_(stock|stock_sampled|flow_total)$")   # the ones Orchestra writes (the host, the Core page, the collectors' failures), or wrote before 2026-10-25


def plumbing_reason(name: str) -> str:
    """Why discovery leaves out a series named ``orchestra_*``: Orchestra's own, or a program's
    that took Orchestra's prefix."""
    if OWN.match(name):
        return "Orchestra's own (the host's and the Core page's plumbing), not a measure of the system"
    return ("named orchestra_*: the orchestra_ prefix is Orchestra's own, so discovery ignores this series; "
            "rename it for what it measures (docs/machines.md)")


def not_current_reason(ser: Series, end: float) -> str:
    """Why a series that is not live at the end of the window (``sd.live.gone``), or never was in
    it (no intervals), is left out. ``end`` is the window's last grid step."""
    who = writer_of(ser)
    last = max((t for t, _ in ser.points), default=end)
    if ser.intervals:
        quiet = round((end - ser.intervals[-1][1]) / 60)
        if who:
            return f"no longer written: its writer {who} has written nothing in the last {quiet} min of the window"
        return f"no longer written: nothing in the last {quiet} min of the window"
    if ser.points and ser.points[0][0] >= end:
        return "too new to measure: its first point is after the window's last step, so the next discovery considers it"
    ago = max(0, round((end - last) / 60))
    if who:
        return f"not written while its writer {who} was live in the window: its last point is {ago} min before the end"
    return f"not written in the window: its last point is {ago} min before the end"


@dataclass(frozen=True)
class Declared:
    """What a series is, said by whoever defined it (a source's view, a ``[[series]]``) rather than
    guessed from its name: a ``counter`` or a ``level``. A counter read from another store
    (``baseline``) was counting before the window began: its first sample is where it stood, not
    events, so steps before it take its value instead of zero. Counted traffic (a source's
    definition said so: ``orchestra.sources.traffic``) also says its ``direction`` (out, in,
    backlog) and ``channel``. ``resolution_s`` is the reporting interval its source measured: no
    series is finer than that (``sd.resolution``). ``summary``: a statistic summarised across
    reporters (an average, a maximum), which discovery never takes for a stock by its net flow."""

    kind: str
    baseline: bool = False
    direction: str | None = None
    channel: str | None = None
    resolution_s: float | None = None
    summary: bool = False


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
    intervals: list[tuple[float, float]] | None = None   # when it was live; None: a machine-less series written as things happen, so always
    live: list[int] | None = None                        # the grid steps whose change is measured: inside those intervals, and for a counter also before its first write; None: every step
    traffic: tuple[str, str] | None = None               # counted traffic: (direction, channel), when a definition said so
    resolution: Resolution | None = None                 # its real resolution and how it is read between points (sd.resolution)
    blocks: list[tuple[int, float]] | None = None        # a level slower than the grid: the steps it was written in, and when (sd.resolution.units)
    summary: bool = False                                # a statistic its source summarised across reporters (Declared.summary)

    @property
    def key(self) -> str:
        return series_key(self.name, self.labels)

    @property
    def deltas(self) -> list[float]:
        """Change per step; for a counter, a drop is a reset (as in Prometheus): the new value is
        what was counted since. Worked out once per list of values (discovery reads it in every
        balance and comparison; the values are never changed in place)."""
        cached = self.__dict__.get("_deltas")
        if cached is not None and cached[0] is self.values and cached[1] == self.counter:
            return cached[2]
        if self.counter:
            out = [(b - a) if b >= a else b for a, b in pairwise(self.values)]
        else:
            out = [b - a for a, b in pairwise(self.values)]
        self.__dict__["_deltas"] = (self.values, self.counter, out)
        return out


WRITTEN_BY = ("instrument", "machine")   # the labels that say who wrote a series: an instrument, or a machine writing its own


def written_by(s: Series) -> str | None:
    """Who wrote the series into the store, by its labels: the instrument that measured it
    (``instrument``, set by the collectors), else the ``machine`` label of a series a machine (or
    another store) wrote under its own name. Provenance, never attribution: discovery groups a
    writer's series (when it was alive, which counters are its record of a level) and never takes it
    for the machine that sets a flow (AGENTS.md rule 7)."""
    return next((s.labels[k] for k in WRITTEN_BY if s.labels.get(k)), None)


def writer_of(s: Series) -> str | None:
    """Who wrote a series (``written_by``), or, for Orchestra's event counters, the ``source`` that
    emitted the events (``unknown`` is no one)."""
    who = written_by(s) or (s.labels.get("source") or "").partition("/")[0]   # baker/2 is the machine baker
    return who if who and who != "unknown" else None


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


def alive(series: list[Series], start: float, end: float) -> dict[str, list[tuple[float, float]]]:
    """When each writer (``writer_of``) was alive: between any of its writes no further apart than its live limit
    (ten times the interval of its fastest series written on a schedule, at least a minute), and
    from its first write to the end when none of its series is on a schedule. A counter written
    only when it moves is no schedule, even when its events come steadily enough to look like one."""
    by_machine: dict[str, list[Series]] = defaultdict(list)
    for s in series:
        if (m := writer_of(s)) is not None:
            by_machine[m].append(s)
    out = {}
    for m, group in by_machine.items():
        times = sorted({t for s in group for t, _ in s.points})
        limits = [live_limit(u) for s in group if not (s.counter and on_events(s.points)) and (u := usual_interval(s.points))]
        out[m] = stretches(times, min(limits) if limits else None, start, end)
    return out


def mark_live(ser: Series, machine_alive: list[tuple[float, float]] | None, start: float, step: float, n: int) -> Series:
    """Record when the series was live: whenever its machine was, for a counter; from its first
    write in each of the machine's stretches, for a gauge. A machine-less series is live on its
    own schedule, if it has one, else always. A counter's change is also measured in the steps
    before its first write (``before_first_write``), though its machine's time there is not."""
    end = start + n * step
    if machine_alive is not None:
        ser.intervals = machine_alive if ser.counter else held(ser.points, machine_alive, start, end)
    elif usual_interval(ser.points) and not (ser.counter and on_events(ser.points)):
        ser.intervals = live_intervals(ser.points, start, end)
    if ser.intervals is not None:
        ser.live = steps_within(ser.intervals, start, step, n)
        if ser.counter:
            ser.live = sorted(set(ser.live) | set(before_first_write(ser.points, start, step, n)))
    return ser


def sample(dump, start: float, step: float, n: int, kinds: dict[str, Declared] | None = None) -> list[Series]:
    """Every series on the grid, each with its last value held (``sd.resolution``). Leading
    steps before a gauge's first point take its first value; before a counter's first point nothing
    had been counted (a counter written when it moves starts at its first event, and that event
    moved the gauges written beside it), unless it is a counter read from elsewhere, whose first
    sample is a baseline. ``kinds`` (by series key) says what a series is when its definition said
    so; others are told by name and values. A level slower than the grid records the steps it was
    written in (``blocks``), so its balance is judged between its writes."""
    out = []
    times = [start + i * step for i in range(n + 1)]
    for name, labels, pts in dump:
        if not pts:
            continue
        said = (kinds or {}).get(series_key(name, labels))
        counter_named = said.kind == "counter" if said else name.endswith("_total")
        got = dict(step_sample(pts, start, times[-1], step))
        first = (0.0 if counter_named and not (said and said.baseline)
                 else next((v for t, v in pts if t >= start), pts[-1][1]))
        vals, last = [], None
        for t in times:
            last = got.get(t, last)
            vals.append(first if last is None else last)
        counter = said.kind == "counter" if said else _is_counter(name, vals)
        res = measure(pts, counter, said.resolution_s if said else None, counter and on_events(pts))
        ser = Series(name, dict(labels), pts, vals, counter, resolution=res)
        if not counter and steps_of(observed_every(pts, res, said.resolution_s if said else None), step) > 1:
            ser.blocks = block_ends(real_points(pts, res.read), start, step, n)
        if said and said.direction and said.channel:
            ser.traffic = (said.direction, said.channel)
        ser.summary = bool(said and said.summary)
        out.append(ser)
    machines = alive(out, start, times[-1])
    return [mark_live(ser, machines.get(writer_of(ser)), start, step, n) for ser in out]


def sum_instances(series: list[Series]) -> tuple[list[Series], dict[str, str]]:
    """Counters that differ only by instance, summed into one per machine.

    A model is about machines, not their instances: six bakers' counts of one event are one flow.
    Counting each instance apart multiplies the candidates a balance is chosen from (on a busy
    system, past the number of steps, where least squares can no longer tell them apart). An
    instance is an ``instance`` label, or the instance part of a ``source`` (``baker/3``).
    Increments are summed, so one instance's reset does not read as the total going back. The sum
    was live whenever any instance was. Returns the series, and what each summed series
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
        merged = Series(name, dict(labels), points, values, True, members, resolution=members[0].resolution)
        if all(m.intervals is not None for m in members):
            merged.intervals = union([iv for m in members for iv in m.intervals])
            merged.live = sorted({i for m in members for i in m.live})
        out.append(merged)
        made[merged.key] = f"summed over {len(members)} instance{'s' if len(members) != 1 else ''}"
    return out, made
