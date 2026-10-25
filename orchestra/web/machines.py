"""The Machines page's data: the machines seen on the event bus, and the graph of which machine
publishes and subscribes to which event types.

Everything here is observed, not declared:
- a **machine** is a CloudEvents ``source`` seen on the bus (plus Orchestra's own host);
- **publishes**: the event types it emitted, with counts;
- **subscribes**: the event types it listens for. Until the bus adapters provide subscriptions
  that the backend can list (docs/proposals/empty-orchestra.md §3), a machine announces its own
  with an ``orchestra.machine.subscribed`` event (``data.types``), and the latest announcement
  stands;
- **metrics**: the series in the metrics store labelled ``machine=<id>``.

Events from before the envelope have no ``source``; they are counted, not attributed."""

from __future__ import annotations

import time
from collections import Counter, defaultdict

from ..events import HOST, event_time

SUBSCRIBED = "orchestra.machine.subscribed"


def machines_view(events: list[dict], series: list[tuple[str, dict]], now: float | None = None) -> dict:
    now = now or time.time()
    pubs: dict[str, Counter] = defaultdict(Counter)
    recent: dict[str, Counter] = defaultdict(Counter)
    subs: dict[str, list[str]] = {}
    first: dict[str, float] = {}
    last: dict[str, float] = {}
    unattributed = 0
    for ev in events:
        src = ev.get("source")
        if not src:
            unattributed += 1
            continue
        t = event_time(ev) or 0.0
        first.setdefault(src, t)
        last[src] = t
        if ev.get("type") == SUBSCRIBED:
            subs[src] = list((ev.get("data") or {}).get("types") or [])
            continue
        pubs[src][ev["type"]] += 1
        if t >= now - 600:
            recent[src][ev["type"]] += 1
    metrics: dict[str, list[str]] = defaultdict(list)
    for name, labels in series:
        if labels.get("machine"):
            metrics[labels["machine"]].append(name + ("{" + ",".join(f'{k}="{v}"' for k, v in sorted(labels.items())
                                                                     if k not in ("project", "machine")) + "}"
                                                     if len(labels) > 2 else ""))
    ids = sorted(set(pubs) | set(subs) | set(metrics) | {HOST}, key=lambda m: (m != HOST, m))
    machines = [{
        "id": m, "bootstrap": m == HOST,
        "publishes": [{"type": t, "count": n, "per_min_10m": round(recent[m][t] / 10, 2)} for t, n in pubs[m].most_common()],
        "subscribes": subs.get(m, []),
        "metrics": sorted(set(metrics.get(m, []))),
        "first_seen": first.get(m), "last_seen": last.get(m),
        "active": bool(last.get(m) and now - last[m] < 120),
    } for m in ids]
    types = sorted({t for m in machines for t in [p["type"] for p in m["publishes"]] + m["subscribes"]})
    edges = [{"from": m["id"], "to": p["type"], "kind": "publishes", "count": p["count"]} for m in machines for p in m["publishes"]]
    edges += [{"from": t, "to": m["id"], "kind": "subscribes"} for m in machines for t in m["subscribes"]]
    return {"machines": machines, "types": types, "edges": edges, "unattributed_events": unattributed}
