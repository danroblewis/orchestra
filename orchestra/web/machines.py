"""The Machines page's data: the machines seen on the event bus, and the network of which machine
publishes and which listens for which event types.

Everything here is observed, not declared:
- a **machine** is a CloudEvents ``source`` seen on the bus (plus Orchestra's own host);
- **publishes**: the event types it emitted, with counts (all time and the last 24 hours);
- **listens for**: until the bus adapters provide subscriptions the backend can list
  (docs/proposals/empty-orchestra.md §3), a machine announces its own with an
  ``orchestra.machine.subscribed`` event (``data.types``); the latest announcement stands;
- **metrics**: the series in the metrics store labelled ``machine=<id>``.

The index reads the bus incrementally: the whole log once, then only what is new, so a refresh
costs one small read however long the log is. Events from before the envelope have no
``source``; they are counted, not attributed."""

from __future__ import annotations

import threading
import time
from collections import Counter, defaultdict, deque

from ..events import HOST, event_time

SUBSCRIBED = "orchestra.machine.subscribed"
DAY = 86400.0
ACTIVE_S = 120.0


class MachineIndex:
    def __init__(self, events):
        self.events = events
        self.offset = 0
        self.total: dict[str, Counter] = defaultdict(Counter)            # source -> type -> count
        self.recent: dict[tuple[str, str], deque] = defaultdict(deque)   # (source, type) -> times in the last day
        self.subs: dict[str, list[str]] = {}
        self.first: dict[str, float] = {}
        self.last: dict[str, float] = {}
        self.unattributed = 0
        self._lock = threading.Lock()

    def update(self) -> None:
        """Fold in whatever is new on the bus since the last call."""
        with self._lock:
            end = self.events.end()
            if end <= self.offset:
                return
            # read(since, limit) returns the last `limit` events after `since`: ask for all of them
            evs, end = self.events.read(self.offset, limit=end - self.offset)
            for ev in evs:
                self._fold(ev)
            self.offset = end

    def _fold(self, ev: dict) -> None:
        src = ev.get("source")
        if not src:
            self.unattributed += 1
            return
        t = event_time(ev) or 0.0
        self.first.setdefault(src, t)
        self.last[src] = max(self.last.get(src, 0.0), t)
        if ev.get("type") == SUBSCRIBED:
            self.subs[src] = list((ev.get("data") or {}).get("types") or [])
            return
        self.total[src][ev["type"]] += 1
        self.recent[(src, ev["type"])].append(t)

    def view(self, series: list[tuple[str, dict]], now: float | None = None) -> dict:
        now = now or time.time()
        with self._lock:
            for q in self.recent.values():
                while q and q[0] < now - DAY:
                    q.popleft()
            metrics: dict[str, set] = defaultdict(set)
            for name, labels in series:
                if labels.get("machine"):
                    extra = ",".join(f'{k}="{v}"' for k, v in sorted(labels.items()) if k not in ("project", "machine"))
                    metrics[labels["machine"]].add(name + (f"{{{extra}}}" if extra else ""))
            ids = sorted(set(self.total) | set(self.subs) | set(metrics) | {HOST}, key=lambda m: (m != HOST, m))
            machines = []
            for m in ids:
                pubs = []
                for ty, n in self.total[m].most_common():
                    q = self.recent.get((m, ty), ())
                    pubs.append({"type": ty, "count": n, "day": len(q),
                                 "per_min_10m": round(sum(1 for t in q if t >= now - 600) / 10, 2)})
                machines.append({"id": m, "bootstrap": m == HOST, "publishes": pubs, "subscribes": self.subs.get(m, []),
                                 "metrics": sorted(metrics.get(m, [])), "first_seen": self.first.get(m),
                                 "last_seen": self.last.get(m),
                                 "active": bool(self.last.get(m) and now - self.last[m] < ACTIVE_S)})
            types = sorted({p["type"] for x in machines for p in x["publishes"]} | {t for x in machines for t in x["subscribes"]})
            edges = [{"from": x["id"], "to": p["type"], "kind": "publishes", "count": p["count"], "day": p["day"]}
                     for x in machines for p in x["publishes"]]
            edges += [{"from": t, "to": x["id"], "kind": "subscribes"} for x in machines for t in x["subscribes"]]
            return {"machines": machines, "types": types, "edges": edges, "unattributed_events": self.unattributed}


class _ListBus:
    def __init__(self, evs: list[dict]):
        self.evs = evs

    def end(self) -> int:
        return len(self.evs)

    def read(self, since: int = 0, limit: int = 500) -> tuple[list[dict], int]:
        return self.evs[since:][-limit:], len(self.evs)


def machines_view(events: list[dict], series: list[tuple[str, dict]], now: float | None = None) -> dict:
    """The view over a given list of events (for tests and one-off use)."""
    idx = MachineIndex(_ListBus(events))
    idx.update()
    return idx.view(series, now)
