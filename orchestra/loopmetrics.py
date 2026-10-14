"""What the event log says about the feedback loops: flows, gains, delays, last fired.

Everything here is a count or a time from the log over a window; nothing is modelled.
The ticket pipeline's flows are the ticket transitions, the two rework gains are rejections
over arrivals, delays are medians per ticket between the states, and an agent's action
rate is how often the log shows it causing an event."""

from __future__ import annotations

import datetime as dt
import statistics
from typing import Any

STATES = ("OPEN", "IN_PROGRESS", "READY_FOR_REVIEW", "IN_REVIEW", "APPROVED", "MERGING", "DONE")


def _ts(e: dict) -> float:
    try:
        return dt.datetime.fromisoformat(e["ts"]).timestamp()
    except (KeyError, ValueError):
        return 0.0


def window(events: list[dict], hours: float = 24.0) -> list[dict]:
    since = (dt.datetime.now(dt.UTC) - dt.timedelta(hours=hours)).isoformat(timespec="seconds")
    return [e for e in events if e.get("ts", "") >= since]


def metrics(events: list[dict]) -> dict[str, Any]:
    """Flows and loop measures over the given events (already windowed)."""
    counts: dict[str, int] = {}
    by: dict[str, dict[str, int]] = {}
    messages: dict[tuple[str, str], int] = {}
    last: dict[str, str] = {}
    last_by: dict[str, dict[str, str]] = {}
    flows: dict[str, int] = {}                 # ticket state -> arrivals
    per_ticket: dict[str, list[tuple[float, str]]] = {}
    gate_rejects = 0
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
        if t == "ticket_transition" and e.get("ticket"):
            flows[e["to"]] = flows.get(e["to"], 0) + 1
            per_ticket.setdefault(e["ticket"], []).append((_ts(e), e["to"]))
        if t == "gate_rejected":
            gate_rejects += len(e.get("tickets") or [])
    # delays: per ticket, time from entering one state to the next arrival at another
    def median_delay(a: str, b_set: set[str]) -> float | None:
        ds = []
        for seq in per_ticket.values():
            seq.sort()
            for i, (ts_a, st) in enumerate(seq):
                if st != a:
                    continue
                nxt = next(((ts_b, sb) for ts_b, sb in seq[i + 1:] if sb in b_set), None)
                if nxt:
                    ds.append(nxt[0] - ts_a)
        return statistics.median(ds) if ds else None
    ready = flows.get("READY_FOR_REVIEW", 0)
    approved = flows.get("APPROVED", 0)
    rejected = flows.get("REJECTED", 0)
    review_rejects = max(0, rejected - gate_rejects)
    rework = {
        "review": {"from": "IN_REVIEW", "to": "IN_PROGRESS", "rejections": review_rejects, "arrivals": ready,
                   "gain": round(review_rejects / ready, 2) if ready else None,
                   "delay": median_delay("READY_FOR_REVIEW", {"APPROVED", "REJECTED"})},
        "gate": {"from": "MERGING", "to": "IN_PROGRESS", "rejections": gate_rejects, "arrivals": approved,
                 "gain": round(gate_rejects / approved, 2) if approved else None,
                 "delay": median_delay("APPROVED", {"DONE", "REJECTED"})},
    }
    return {"counts": counts, "by": by, "messages": messages, "last": last, "last_by": last_by,
            "flows": flows, "rework": rework, "turnaround": median_delay("IN_PROGRESS", {"DONE"}),
            "hours": 24}
