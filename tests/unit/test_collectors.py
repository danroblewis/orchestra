"""The ticket collector: event log in, stock levels and flow counters out, anchored to the store."""

from __future__ import annotations

from orchestra import collectors
from orchestra.collectors import FLOW, SAMPLED, STOCK, TicketCollector, anchor, backfill
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
    return [p.value for p in points if p.series == STOCK and p.labels["stock"] == stock]


def test_events_become_levels_and_counters():
    col = TicketCollector("p")
    pts = [p for e in LOG for p in col.observe(e)]
    assert levels(pts, "OPEN") == [1, 2, 1, 0]
    assert levels(pts, "IN_PROGRESS") == [1, 0, 1]
    assert col.flows == {"outside>OPEN": 2, "OPEN>IN_PROGRESS": 2, "IN_PROGRESS>READY_FOR_REVIEW": 1}
    assert col.events["session_started"] == 1
    flow_pts = [p.value for p in pts if p.series == FLOW and p.labels["flow"] == "OPEN>IN_PROGRESS"]
    assert flow_pts == [1, 2], "a flow is a cumulative counter"


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
    assert [v for _, v in store.raw(STOCK, {"project": "p", "stock": "OPEN"})] == [2, 3, 2, 1], "rerun replaced, not doubled"
    assert store.latest(SAMPLED, {"project": "p", "stock": "OPEN"}) == (1_800_000_000.0, 1)
    assert store.latest(collectors.EVENTS, {"project": "p", "type": "ticket_created"})[1] == 2
