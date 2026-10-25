"""The ticket collector: event log in, stock levels and flow counters out, anchored to the store."""

from __future__ import annotations

from orchestra import collectors
from orchestra.collectors import (
    CREATED,
    SAMPLED,
    TICKETS,
    TRANSITIONS,
    TicketCollector,
    anchor,
    backfill,
)
from orchestra.metrics.file import FileMetrics


def ev(t, type, **kw):
    return {"ts": f"2026-10-20T10:00:{t:02d}+00:00", "type": type, **kw}


LOG = [
    ev(0, "ticket_created", ticket="A-1"),
    ev(1, "ticket_created", ticket="A-2"),
    ev(2, "ticket_transition", ticket="A-1", **{"from": "OPEN", "to": "IN_PROGRESS"}),
    ev(3, "session_started", kind="worker", session="s1"),
    ev(4, "ticket_transition", ticket="A-1", **{"from": "IN_PROGRESS", "to": "READY_FOR_REVIEW"}),
    ev(5, "ticket_transition", ticket="A-3", **{"from": "OPEN", "to": "IN_PROGRESS"}),   # created before the log began
]


def levels(points, stock):
    return [p.value for p in points if p.series == TICKETS and p.labels["state"] == stock]


def test_events_become_levels_and_counters():
    col = TicketCollector("p")
    pts = [p for e in LOG for p in col.observe(e)]
    assert levels(pts, "OPEN") == [1, 2, 1, 0]
    assert levels(pts, "IN_PROGRESS") == [1, 0, 1]
    assert col.flows == {("outside", "OPEN"): 2, ("OPEN", "IN_PROGRESS"): 2, ("IN_PROGRESS", "READY_FOR_REVIEW"): 1}
    assert col.events["session_started"] == 1
    flow_pts = [p.value for p in pts if p.series == TRANSITIONS and (p.labels["from"], p.labels["to"]) == ("OPEN", "IN_PROGRESS")]
    assert flow_pts == [1, 2], "a flow is a cumulative counter"
    assert [p.value for p in pts if p.series == CREATED] == [1, 2], "creation has its own counter"
    assert all(set(p.labels) == {"project"} for p in pts if p.series == CREATED)


def test_anchor_shifts_integrated_levels_to_the_sampled_counts():
    col = TicketCollector("p")
    pts = [p for e in LOG for p in col.observe(e)]
    # the store knows A-3 existed: OPEN really ends at 1, not 0
    shifted, shift = anchor(pts, {"OPEN": 1, "IN_PROGRESS": 1, "READY_FOR_REVIEW": 1})
    assert shift == {"OPEN": 1, "IN_PROGRESS": 0, "READY_FOR_REVIEW": 0}
    assert levels(shifted, "OPEN") == [2, 3, 2, 1]


def test_backfill_writes_everything_and_replaces_on_rerun(tmp_path):
    store = FileMetrics(tmp_path / "m.jsonl")
    for _ in range(2):
        rep = backfill(LOG, project="p", store=store, sampled={"OPEN": 1, "IN_PROGRESS": 1, "READY_FOR_REVIEW": 1},
                       sampled_at=1_800_000_000.0)
    assert rep.shifts["OPEN"] == 1 and rep.events == len(LOG)
    assert [v for _, v in store.raw(TICKETS, {"project": "p", "state": "OPEN"})] == [2, 3, 2, 1], "rerun replaced, not doubled"
    assert store.latest(SAMPLED, {"project": "p", "state": "OPEN"}) == (1_800_000_000.0, 1)
    assert store.latest(collectors.EVENTS, {"project": "p", "type": "ticket_created"})[1] == 2


def test_one_value_per_series_per_instant(tmp_path):
    """A ticket entering and leaving a state in the same second must not leave two values at one
    instant: stores order those differently, and the level after the second would be ambiguous."""
    log = [ev(0, "ticket_created", ticket="A-1"),
           ev(5, "ticket_transition", ticket="A-1", **{"from": "OPEN", "to": "IN_PROGRESS"}),
           ev(5, "ticket_transition", ticket="A-1", **{"from": "IN_PROGRESS", "to": "BLOCKED"})]
    store = FileMetrics(tmp_path / "m.jsonl")
    backfill(log, project="p", store=store, sampled={"BLOCKED": 1}, sampled_at=1_800_000_000.0)
    stamp = TicketCollector("p")
    t5 = [p for e in log for p in stamp.observe(e)][-1].ts
    assert store.raw(TICKETS, {"project": "p", "state": "IN_PROGRESS"}) == [(t5, 0)]
    pts = collectors.collapse([p for e in log for p in TicketCollector("p").observe(e)])
    keys = [(p.key(), p.ts) for p in pts]
    assert len(keys) == len(set(keys))
