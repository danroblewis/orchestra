"""Counted traffic on the Machines page: machines, channels and edges known from counts read from
another system's bus (``orchestra.sources.traffic``), never from events.

``summarise`` turns the series the catalogue read (``Catalogue.counted``) into, per channel, what
was produced into it, consumed from it and waits in it, and per machine, what it produced or
consumed; ``merge`` adds them to the Machines view:

- a **machine** a source attributes counted traffic to is a machine, known by observation: marked
  ``counted`` (and ``counted_only`` when it was never seen on the bus). Its last seen is its last
  interval with a nonzero count, and it is active while that is within ``ACTIVE_S``, which allows
  for the store's scrape interval and the minute between reads;
- a **channel** (``rabbit:orders``) is a node like an event type, with its rates and backlog;
- a **counted edge** runs from a producer to its channel, or from a channel to its consumer, with
  its rate; a count no machine is attributed to runs from or to ``unattributed`` (the producers
  a broker cannot name), so the gap shows.

Rates are per minute over the last ``RECENT_S`` of what was read, every series of a source
measured up to that source's last point (a source's ``settle`` puts it before now): a series that
ended earlier (a publisher that disconnected, whose per-channel series the broker drops) counts
nothing for the stretch it is missing. Counts are over the window read."""

from __future__ import annotations

from collections import defaultdict
from itertools import pairwise

RECENT_S = 600.0
ACTIVE_S = 300.0
READ_S = 3600.0        # the window the web server reads counted traffic over
READ_STEP_S = 15.0


def _increase(points: list[tuple[float, float]], since: float) -> tuple[float, float | None]:
    """The counter's increase after ``since`` (a drop is a reset), and when it last rose."""
    total, last = 0.0, None
    for (_, a), (t, b) in pairwise(points):
        d = b - a if b >= a else b
        if d > 0:
            last = t
            if t > since:
                total += d
    return total, last


def summarise(counted: list[dict], now: float) -> dict:
    """``counted``: series with ``direction``, ``channel``, ``machine`` (or None) and ``points``."""
    edges: dict[tuple, dict] = {}
    channels: dict[str, dict] = {}
    ends: dict[str, float] = {}             # each source's last point read: a source that settles ends before now
    for c in counted:
        if c.get("points"):
            ends[c["source"]] = max(ends.get(c["source"], float("-inf")), c["points"][-1][0])
    for c in counted:
        ch = channels.setdefault(c["channel"], {"id": c["channel"], "source": c["source"], "out_per_min": 0.0, "in_per_min": 0.0,
                                                "backlog": None, "series": 0})
        ch["series"] += 1
        who = c.get("machine")
        key = (who, c["channel"], c["direction"])
        e = edges.setdefault(key, {"machine": who, "channel": c["channel"], "direction": c["direction"], "per_min": 0.0,
                                   "window": 0.0, "last": None, "backlog": None, "series": 0})
        e["series"] += 1
        pts = c.get("points") or []
        if c["direction"] == "backlog":
            if pts:
                e["backlog"] = (e["backlog"] or 0.0) + pts[-1][1]
                ch["backlog"] = (ch["backlog"] or 0.0) + pts[-1][1]
            continue
        upto = ends.get(c["source"], now)          # a series that ended (a publisher gone) counts nothing since
        recent, last = _increase(pts, upto - RECENT_S)
        span = min(RECENT_S, upto - pts[0][0]) if pts else RECENT_S
        e["per_min"] += recent / max(span, 60.0) * 60.0
        e["window"] += _increase(pts, float("-inf"))[0]
        if last is not None:
            e["last"] = max(e["last"] or 0.0, last)
        ch[f"{c['direction']}_per_min"] += recent / max(span, 60.0) * 60.0
    machines: dict[str, dict] = defaultdict(lambda: {"traffic": [], "last": None})
    for e in edges.values():
        e["per_min"] = round(e["per_min"], 2)
        if e["machine"]:
            m = machines[e["machine"]]
            m["traffic"].append({k: e[k] for k in ("channel", "direction", "per_min", "window", "backlog")})
            if e["last"]:
                m["last"] = max(m["last"] or 0.0, e["last"])
    for ch in channels.values():
        ch["out_per_min"], ch["in_per_min"] = round(ch["out_per_min"], 2), round(ch["in_per_min"], 2)
    return {"at": now, "channels": sorted(channels.values(), key=lambda x: x["id"]), "edges": list(edges.values()),
            "machines": dict(machines)}


def merge(view: dict, summary: dict | None, now: float) -> None:
    """Counted machines, channels and edges into the Machines view (``MachineIndex.view``)."""
    view["channels"] = (summary or {}).get("channels", [])
    view["counted"] = [{"from": e["machine"] if e["direction"] == "out" else e["channel"],
                        "to": e["channel"] if e["direction"] == "out" else e["machine"], **e}
                       for e in (summary or {}).get("edges", []) if e["direction"] != "backlog"]
    seen = {m["id"]: m for m in view["machines"]}
    for mid, c in sorted((summary or {}).get("machines", {}).items()):
        m = seen.get(mid)
        if m is None:
            m = {"id": mid, "bootstrap": False, "mode": None, "kind": None, "package": None, "about": {}, "publishes": [],
                 "subscribes": [], "metrics": [], "logs": [], "instances": [], "first_seen": None, "last_seen": None,
                 "active": False, "counted_only": True}
            view["machines"].append(m)
        if not m.get("first_seen") and not m.get("publishes"):
            m["counted_only"] = True         # however else it is known (a model's series), never seen on the bus: known by counts
        m["counted"] = sorted(c["traffic"], key=lambda t: (t["channel"], t["direction"]))
        if c["last"] and c["last"] > (m.get("last_seen") or 0.0):
            m["last_seen"] = c["last"]
        m["active"] = bool(m.get("active") or (c["last"] and now - c["last"] < ACTIVE_S))
