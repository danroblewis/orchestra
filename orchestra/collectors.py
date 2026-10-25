"""Collectors: measurements that become stock levels and flow counts.

The first collector reads Orchestra's own event log. Every ticket event is a flow observation:
``ticket_created`` moves a ticket from outside into OPEN, and ``ticket_transition`` moves it from
one state to another. Replaying the log gives:

- ``orchestra_tickets{project, state}``: how many tickets are in each state, written at every
  change;
- ``orchestra_tickets_created_total{project}``: how many tickets have been created, a cumulative
  counter whose differences are rates;
- ``orchestra_ticket_transitions_total{project, from, to}``: how many tickets have moved from one
  state to another, counted the same way;
- ``orchestra_events_total{project, type}``: every event type, counted the same way;
- ``orchestra_tickets_sampled{project, state}``: the ticket store's own count, read directly.

Series are named for what they measure, not for the model: summing across a label must mean
something (all tickets, all transitions). Whether a series is a stock or a flow is the model's
business: it binds its stocks and flows to series by name and labels (``sd.model.SeriesRef``),
so any series, Orchestra's own Core measurements included, can become part of it.

Events carry one-second timestamps, and a ticket often enters and leaves a state within the same
second, which would put two values of one series at one instant. Stores don't agree on the order
of such points (the file keeps it, VictoriaMetrics doesn't), so the collector writes only the
last value of each series at each instant (``collapse``). A zero-length visit adds nothing to a
level's integral and a counter's last value is its count, so nothing is lost.

Integrated levels drift when an event is missing (tickets created before the log began, a lost
line), so after a replay each stock's series is **anchored**: shifted so that its final level
equals the count sampled from the ticket store. The size of each shift is reported, because it is
a measure of how much the log misses.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime

from .metrics import MetricsStore, Point

TICKETS = "orchestra_tickets"
CREATED = "orchestra_tickets_created_total"
TRANSITIONS = "orchestra_ticket_transitions_total"
EVENTS = "orchestra_events_total"
SAMPLED = "orchestra_tickets_sampled"
SERIES = (TICKETS, CREATED, TRANSITIONS, EVENTS, SAMPLED)
LEGACY = ("orchestra_stock", "orchestra_flow_total", "orchestra_stock_sampled")    # names before 2026-10-25
OUTSIDE = "outside"


def ts_of(ev: dict) -> float:
    return datetime.fromisoformat(ev["ts"]).timestamp()


@dataclass
class TicketCollector:
    project: str
    state: dict[str, str] = field(default_factory=dict)        # ticket -> its state, as far as the log shows
    levels: Counter = field(default_factory=Counter)
    flows: Counter = field(default_factory=Counter)            # (from, to), with OUTSIDE for creation
    events: Counter = field(default_factory=Counter)

    def _move(self, ts: float, src: str, dst: str) -> list[Point]:
        out = []
        lab = {"project": self.project}
        if src != OUTSIDE:
            self.levels[src] -= 1
            out.append(Point(TICKETS, self.levels[src], ts, {**lab, "state": src}))
        if dst != OUTSIDE:
            self.levels[dst] += 1
            out.append(Point(TICKETS, self.levels[dst], ts, {**lab, "state": dst}))
        self.flows[(src, dst)] += 1
        n = self.flows[(src, dst)]
        if src == OUTSIDE:
            out.append(Point(CREATED, n, ts, lab))
        else:
            out.append(Point(TRANSITIONS, n, ts, {**lab, "from": src, "to": dst}))
        return out

    def observe(self, ev: dict) -> list[Point]:
        """The points one event produces (none for events that move nothing but its type count)."""
        ts = ts_of(ev)
        self.events[ev["type"]] += 1
        out = [Point(EVENTS, self.events[ev["type"]], ts, {"project": self.project, "type": ev["type"]})]
        if ev["type"] == "ticket_created":
            self.state[ev["ticket"]] = "OPEN"
            out += self._move(ts, OUTSIDE, "OPEN")
        elif ev["type"] == "ticket_transition":
            self.state[ev["ticket"]] = ev["to"]
            out += self._move(ts, ev["from"], ev["to"])
        return out


def anchor(points: list[Point], sampled: dict[str, int]) -> tuple[list[Point], dict[str, int]]:
    """Shift each stock's series so its last value equals the sampled count. Returns the shifted
    points and each stock's shift (sampled minus integrated)."""
    final: dict[str, float] = {}
    for p in points:
        if p.series == TICKETS:
            final[p.labels["state"]] = p.value
    shift = {s: int(sampled.get(s, 0) - v) for s, v in final.items()}
    for s in sampled:
        shift.setdefault(s, 0)
    out = [Point(p.series, p.value + shift[p.labels["state"]], p.ts, p.labels) if p.series == TICKETS else p for p in points]
    return out, shift


def collapse(points: list[Point]) -> list[Point]:
    """Keep only the last point of each series at each timestamp, in time order."""
    last: dict[tuple, Point] = {}
    for p in points:
        last[(p.key(), p.ts)] = p                 # later points overwrite; dicts keep first-insert order
    return sorted(last.values(), key=lambda p: p.ts)


@dataclass
class BackfillReport:
    events: int
    points: int
    first: float | None
    last: float | None
    shifts: dict[str, int]
    flows: dict[str, int]


def backfill(events: list[dict], *, project: str, store: MetricsStore, sampled: dict[str, int],
             sampled_at: float, replace: bool = True) -> BackfillReport:
    """Replay a whole event log into the metrics store."""
    col = TicketCollector(project)
    points: list[Point] = []
    for ev in events:
        if "ts" in ev and "type" in ev:
            points += col.observe(ev)
    points, shifts = anchor(collapse(points), sampled)
    points += [Point(SAMPLED, n, sampled_at, {"project": project, "state": s}) for s, n in sampled.items()]
    if replace:
        for name in SERIES + LEGACY:
            store.delete(name, {"project": project})
    store.write(points)
    stamps = [ts_of(e) for e in events if "ts" in e]
    return BackfillReport(len(events), len(points), stamps[0] if stamps else None, stamps[-1] if stamps else None,
                          shifts, {f"{a}>{b}": n for (a, b), n in col.flows.items()})
