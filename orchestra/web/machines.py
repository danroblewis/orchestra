"""The Machines page's data: the machines seen on the event bus, their instances and how they are
engaged, and the network of which machine publishes and which listens for which event types.

Everything here is observed, not declared:
- a **machine** is the machine part of a CloudEvents ``source``; a source ``<machine>/<instance>``
  is one **instance** of it (``baker/1``, ``baker/2``: one machine, two instances). Orchestra's own
  host is a machine too;
- **how it is engaged** (continuous, scheduled or ad hoc) and **what it listens for**: until the
  bus adapters provide subscriptions the backend can list (docs/proposals/empty-orchestra.md §3),
  an instance announces both when it starts, with ``orchestra.machine.started`` (``data.mode``,
  ``data.listens_for``; ``orchestra.machine.subscribed`` with ``data.types`` is read too). The
  latest announcement stands;
- **publishes**: the event types its instances emitted, with counts (all time and the last day);
- **metrics**: the series in the metrics store labelled ``machine=<id>``;
- **recent events**: the last ``RECENT`` events of each machine, by their envelope only (time,
  type, instance, subject, id; never the ``data``, which is the machines' own);
- **logs**: where an instance says its log is (``data.log`` in its announcement). The web server
  reads it only within the project (``machine_logs.py``).

The index reads the bus incrementally: the whole log once, then only what is new, so a refresh
costs one small read however long the log is. Events from before the envelope have no
``source``; they are counted, not attributed."""

from __future__ import annotations

import threading
import time
from collections import Counter, defaultdict, deque

from ..events import HOST, event_time, machine_and_instance

ANNOUNCE = ("orchestra.machine.started", "orchestra.machine.subscribed")
DAY = 86400.0
ACTIVE_S = 120.0
RECENT = 60


class MachineIndex:
    def __init__(self, events):
        self.events = events
        self.offset = 0
        self.total: dict[str, Counter] = defaultdict(Counter)            # machine -> type -> count
        self.recent: dict[tuple[str, str], deque] = defaultdict(deque)   # (machine, type) -> times in the last day
        self.subs: dict[str, set] = defaultdict(set)                     # machine -> types its instances listen for
        self.mode: dict[str, str] = {}
        self.instances: dict[str, dict[str, dict]] = defaultdict(dict)  # machine -> instance -> first/last seen
        self.logs: dict[str, dict[str, str]] = defaultdict(dict)        # machine -> instance -> announced log path
        self.latest: dict[str, deque] = defaultdict(lambda: deque(maxlen=RECENT))  # machine -> its last events' envelopes
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
        machine, instance = machine_and_instance(ev.get("source"))
        if not machine:
            self.unattributed += 1
            return
        t = event_time(ev) or 0.0
        inst = self.instances[machine].setdefault(instance or "", {"first": t, "last": t})
        inst["last"] = max(inst["last"], t)
        if ev.get("type") in ANNOUNCE:
            d = ev.get("data") or {}
            self.subs[machine].update(d.get("listens_for") or d.get("types") or [])
            if d.get("mode"):
                self.mode[machine] = d["mode"]
            if isinstance(d.get("log"), str) and d["log"]:
                self.logs[machine][instance or ""] = d["log"]
            return
        self.total[machine][ev["type"]] += 1
        self.recent[(machine, ev["type"])].append(t)
        self.latest[machine].append({"t": t, "type": ev["type"], "instance": instance, "subject": ev.get("subject"), "id": ev.get("id")})

    def events_of(self, machine: str) -> list[dict]:
        """The machine's last events, newest first (envelopes only)."""
        with self._lock:
            return list(reversed(self.latest.get(machine, ())))

    def log_path(self, machine: str, instance: str | None) -> str | None:
        """Where the instance (or, without one, any instance) said its log is."""
        with self._lock:
            logs = self.logs.get(machine) or {}
            return logs.get(instance or "") if instance is not None else next(iter(logs.values()), None)

    def view(self, series: list[tuple[str, dict]], now: float | None = None) -> dict:
        now = now or time.time()
        with self._lock:
            for q in self.recent.values():
                while q and q[0] < now - DAY:
                    q.popleft()
            metrics: dict[str, set] = defaultdict(set)
            for name, labels in series:
                if labels.get("machine"):
                    extra = ",".join(f'{k}="{v}"' for k, v in sorted(labels.items()) if k not in ("project", "machine", "instance"))
                    metrics[labels["machine"]].add(name + (f"{{{extra}}}" if extra else ""))
            ids = sorted(set(self.total) | set(self.subs) | set(metrics) | set(self.instances) | {HOST}, key=lambda m: (m != HOST, m))
            machines = []
            for m in ids:
                pubs = []
                for ty, n in self.total[m].most_common():
                    q = self.recent.get((m, ty), ())
                    pubs.append({"type": ty, "count": n, "day": len(q),
                                 "per_min_10m": round(sum(1 for t in q if t >= now - 600) / 10, 2)})
                insts = [{"id": i or m, "first_seen": v["first"], "last_seen": v["last"], "active": now - v["last"] < ACTIVE_S}
                         for i, v in sorted(self.instances[m].items())]
                last = max((v["last"] for v in self.instances[m].values()), default=None)
                first = min((v["first"] for v in self.instances[m].values()), default=None)
                machines.append({"id": m, "bootstrap": m == HOST, "mode": self.mode.get(m), "publishes": pubs,
                                 "subscribes": sorted(self.subs.get(m, ())), "metrics": sorted(metrics.get(m, [])),
                                 "logs": sorted(i or m for i in self.logs.get(m, {})),
                                 "instances": [i for i in insts if i["id"] != m] if any(k for k in self.instances[m]) else [],
                                 "first_seen": first, "last_seen": last, "active": bool(last and now - last < ACTIVE_S)})
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
