"""Collectors: measurements that become series in the metrics store.

Orchestra's own collector is generic and knows nothing about what events mean. It counts every
event on the bus by its type and the machine that emitted it:

- ``orchestra_events_total{project, type, source}``: a cumulative counter per event type and
  source. ``source`` is the CloudEvents source; events from before the envelope have none and are
  counted under ``source="unknown"``.

Whether a counter is a flow, and of what, is the model generator's business, not the
collector's: collectors expose plain series, and the generator relates them (docs/proposals/
empty-orchestra.md §8). The metrics store is filled by instruments directly (``orchestra.collect``:
scripts and scrapes, which measure the system); this count of the bus is the one series derived
from the event log, and is secondary. Discovery reads it to associate machines with flows, as
hypotheses (``sd.attribute``).

Events carry millisecond timestamps, but older ones have one-second timestamps, and several events
can share an instant. Stores don't agree on the order of points that share one (the file keeps
it, VictoriaMetrics doesn't), so only the last value of each series at each instant is written
(``collapse``)."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from .events import event_time
from .metrics import MetricsStore, Point

EVENTS = "orchestra_events_total"
LEGACY = ("orchestra_stock", "orchestra_flow_total", "orchestra_stock_sampled")    # names before 2026-10-25


def collapse(points: list[Point]) -> list[Point]:
    """Keep only the last point of each series at each timestamp, in time order."""
    last: dict[tuple, Point] = {}
    for p in points:
        last[(p.key(), p.ts)] = p                 # later points overwrite; dicts keep first-insert order
    return sorted(last.values(), key=lambda p: p.ts)


@dataclass
class EventCollector:
    """Counts events by (type, source). Feed it events in log order with ``observe``; it keeps
    the running totals, so it can follow a live bus after a replay."""

    project: str
    counts: Counter = field(default_factory=Counter)

    def observe(self, ev: dict) -> list[Point]:
        ts = event_time(ev)
        if ts is None or "type" not in ev:
            return []
        key = (ev["type"], str(ev.get("source") or "unknown"))
        self.counts[key] += 1
        return [Point(EVENTS, self.counts[key], ts, {"project": self.project, "type": key[0], "source": key[1]})]


@dataclass
class BackfillReport:
    events: int
    points: int
    first: float | None
    last: float | None
    types: dict[str, int]


def backfill(events: list[dict], *, project: str, store: MetricsStore, replace: bool = True) -> BackfillReport:
    """Replay a whole event log into the metrics store."""
    col = EventCollector(project)
    points: list[Point] = []
    for ev in events:
        points += col.observe(ev)
    points = collapse(points)
    if replace:
        for name in (EVENTS, *LEGACY):
            store.delete(name, {"project": project})
    store.write(points)
    stamps = [t for t in (event_time(e) for e in events) if t is not None]
    types = Counter()
    for (ty, _), n in col.counts.items():
        types[ty] += n
    return BackfillReport(len(events), len(points), min(stamps, default=None), max(stamps, default=None), dict(types))
