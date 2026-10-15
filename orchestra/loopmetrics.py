"""What the event log says about the feedback loops: flows, gains, delays, last closures.

Everything here is a count or a time from the log over a window; nothing is modelled.
The ticket pipeline's flows are the ticket transitions. The three return loops are measured
as a fraction (how many of the tickets that reached a point were sent back) and a round
trip (median time from being sent back to reaching that point again). The delivery
outcomes (commits landed, gate runs by result, staging deploys) are the stocks past the
ticket pipeline: what the work actually produced."""

from __future__ import annotations

import datetime as dt
import statistics
from typing import Any

STATES = ("OPEN", "IN_PROGRESS", "READY_FOR_REVIEW", "IN_REVIEW", "APPROVED", "MERGING", "DONE")

# The return loops, in the order they are lettered on the map: where the ticket was, where it
# went back to, the arrival that counts as "reached the point", and the arrival that closes
# the round trip. A rejection is told apart by where it came from.
RETURNS = {
    "review": {"from": "IN_REVIEW", "to": "REJECTED", "reaches": "READY_FOR_REVIEW", "closes": "READY_FOR_REVIEW", "label": "rejected in review"},
    "gate": {"from": "MERGING", "to": "REJECTED", "reaches": "APPROVED", "closes": "APPROVED", "label": "rejected by the gate"},
    "restart": {"from": "IN_PROGRESS", "to": "OPEN", "reaches": "IN_PROGRESS", "closes": "IN_PROGRESS", "label": "restarted"},
    "blocked": {"from": "IN_PROGRESS", "to": "BLOCKED", "reaches": "IN_PROGRESS", "closes": "IN_PROGRESS", "label": "blocked"},
}


def _ts(e: dict) -> float:
    try:
        return dt.datetime.fromisoformat(e["ts"]).timestamp()
    except (KeyError, ValueError):
        return 0.0


def window(events: list[dict], hours: float = 24.0) -> list[dict]:
    since = (dt.datetime.now(dt.UTC) - dt.timedelta(hours=hours)).isoformat(timespec="seconds")
    return [e for e in events if e.get("ts", "") >= since]


def _median(xs: list[float]) -> float | None:
    return statistics.median(xs) if xs else None


def metrics(events: list[dict], hours: float = 24.0, created_at: dict[str, float] | None = None) -> dict[str, Any]:
    """Flows and loop measures over the given events (already windowed). ``created_at`` gives every
    ticket's creation time, so a ticket created before the window still has a lead time."""
    counts: dict[str, int] = {}
    by: dict[str, dict[str, int]] = {}
    messages: dict[tuple[str, str], int] = {}
    last: dict[str, str] = {}
    last_by: dict[str, dict[str, str]] = {}
    flows: dict[str, int] = {}                 # ticket state -> arrivals
    pairs: dict[str, int] = {}                 # "FROM>TO" -> transitions
    per_ticket: dict[str, list[tuple[float, str, str]]] = {}   # ticket -> (ts, from, to)
    created: dict[str, float] = {}
    for e in events:
        t = e["type"]
        counts[t] = counts.get(t, 0) + 1
        last[t] = e.get("ts", "")
        variant = e.get("to") or e.get("probe") or e.get("subject")
        if variant:
            counts[f"{t}:{variant}"] = counts.get(f"{t}:{variant}", 0) + 1
            last[f"{t}:{variant}"] = e.get("ts", "")
        who = e.get("by") or e.get("author")
        if t == "agent_messaged" and who and e.get("agent"):
            messages[(who, e["agent"])] = messages.get((who, e["agent"]), 0) + 1
        elif who and who != "orchestra":
            key = f"{t}:{variant}" if variant else t
            by.setdefault(who, {})[key] = by.get(who, {}).get(key, 0) + 1
            last_by.setdefault(who, {})[key] = e.get("ts", "")
        if t == "ticket_created" and e.get("ticket"):
            created[e["ticket"]] = _ts(e)
        if t == "ticket_transition" and e.get("ticket"):
            flows[e["to"]] = flows.get(e["to"], 0) + 1
            pk = f"{e.get('from') or '?'}>{e['to']}"
            pairs[pk] = pairs.get(pk, 0) + 1
            per_ticket.setdefault(e["ticket"], []).append((_ts(e), e.get("from") or "", e["to"]))
    for seq in per_ticket.values():
        seq.sort()

    def delay(a: str, b_set: set[str]) -> float | None:
        """Median time per ticket from arriving at a to the next arrival at any of b_set."""
        ds = []
        for seq in per_ticket.values():
            for i, (ts_a, _, st) in enumerate(seq):
                if st != a:
                    continue
                nxt = next((ts_b for ts_b, _, sb in seq[i + 1:] if sb in b_set), None)
                if nxt is not None:
                    ds.append(nxt - ts_a)
        return _median(ds)

    returns: dict[str, dict] = {}
    for key, r in RETURNS.items():
        sent = pairs.get(f"{r['from']}>{r['to']}", 0)
        reached = flows.get(r["reaches"], 0)
        trips, closed_at = [], ""
        for seq in per_ticket.values():
            for i, (ts_a, frm, st) in enumerate(seq):
                if not (frm == r["from"] and st == r["to"]):
                    continue
                nxt = next(((ts_b, sb) for ts_b, _, sb in seq[i + 1:] if sb == r["closes"]), None)
                if nxt is not None:
                    trips.append(nxt[0] - ts_a)
        # last closed: the most recent arrival at the closing state that followed a send-back
        for seq in per_ticket.values():
            pending = False
            for ts_a, frm, st in seq:
                if frm == r["from"] and st == r["to"]:
                    pending = True
                elif pending and st == r["closes"]:
                    pending = False
                    closed_at = max(closed_at, dt.datetime.fromtimestamp(ts_a, dt.UTC).isoformat(timespec="seconds"))
        returns[key] = {**r, "sent_back": sent, "reached": reached, "fraction": round(sent / reached, 2) if reached else None,
                        "round_trip": _median(trips), "closed": len(trips), "last_closed": closed_at or None}
    started = flows.get("IN_PROGRESS", 0)
    machines = {
        "worker": {"stock_in": "IN_PROGRESS", "stock_out": "READY_FOR_REVIEW", "cycle": delay("IN_PROGRESS", {"READY_FOR_REVIEW", "BLOCKED", "OPEN"}), "processed": started},
        "reviewer": {"stock_in": "IN_REVIEW", "stock_out": "APPROVED", "cycle": delay("IN_REVIEW", {"APPROVED", "REJECTED"}), "processed": flows.get("IN_REVIEW", 0)},
        "merge_gate": {"stock_in": "MERGING", "stock_out": "DONE", "cycle": delay("MERGING", {"DONE", "REJECTED", "APPROVED"}), "processed": flows.get("MERGING", 0)},
    }
    # delivery outcomes: what left the ticket pipeline and reached the world
    gate_runs = counts.get("gate_started", 0)
    delivery = {
        "landed": counts.get("gate_landed", 0), "gate_runs": gate_runs,
        "gate_outcomes": {k: counts.get(f"gate_{k}", 0) for k in ("landed", "rejected", "conflict", "base_broken", "error")},
        "gate_pass": round(counts.get("gate_landed", 0) / gate_runs, 2) if gate_runs else None,
        "deployed": counts.get("staging_deployed", 0), "staging_failed": counts.get("staging_failed", 0),
        "staging_restarted": counts.get("staging_restarted", 0),
        "last_landed": last.get("gate_landed"), "last_deployed": last.get("staging_deployed"),
    }
    # lead time: from creation to DONE, for tickets that finished in the window
    leads = []
    for tid, seq in per_ticket.items():
        done = next((ts for ts, _, st in seq if st == "DONE"), None)
        made = (created_at or {}).get(tid, created.get(tid))
        if done is not None and made is not None:
            leads.append(done - made)                  # every ticket that finished in the window, wherever it was created (round 32)
    days = max(hours / 24.0, 1e-9)
    headline = {
        "landed_per_day": round(flows.get("DONE", 0) / days, 1), "created_per_day": round(counts.get("ticket_created", 0) / days, 1),
        "lead_time": _median(leads), "cycle_time": delay("IN_PROGRESS", {"DONE"}),
        "restarts_per_day": round(returns["restart"]["sent_back"] / days, 1),
        "turn_timeouts": counts.get("turn_timed_out", 0), "turn_errors": counts.get("turn_error", 0),
    }
    return {"counts": counts, "by": by, "messages": messages, "last": last, "last_by": last_by,
            "flows": flows, "pairs": pairs, "returns": returns, "machines": machines, "delivery": delivery,
            "headline": headline, "turnaround": headline["cycle_time"], "hours": hours,
            # kept for callers that read the two rework gains by their old names
            "rework": {"review": _rework(returns["review"]), "gate": _rework(returns["gate"])}}


def _rework(r: dict) -> dict:
    return {"from": r["from"], "to": "IN_PROGRESS", "rejections": r["sent_back"], "arrivals": r["reached"], "gain": r["fraction"], "delay": r["round_trip"]}
