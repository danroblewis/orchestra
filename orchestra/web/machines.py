"""The Machines page's data: the machines seen on the event bus, their instances and how they are
engaged, and the network of which machine publishes and which listens for which event types.

Everything here is observed, or announced by the machine itself:
- a **machine** is the machine part of a CloudEvents ``source``; a source ``<machine>/<instance>``
  is one **instance** of it (``baker/1``, ``baker/2``: one machine, two instances). Orchestra's own
  host is a machine too;
- **how it is engaged** (continuous, scheduled or ad hoc), **what it listens for**, **what kind
  of thing it is** (a program, an AI agent, a person, a service) and **which package** it belongs
  to: until the bus adapters provide subscriptions the backend can list
  (docs/proposals/empty-orchestra.md §3), an instance announces these when it starts, with
  ``orchestra.machine.started`` (``data.mode``, ``data.listens_for``, ``data.kind``,
  ``data.package``; ``orchestra.machine.subscribed`` with ``data.types`` is read too). The latest
  announcement stands; the rest of it is passed to the package's card unread;
- **publishes**: the event types its instances emitted, with counts (all time and the last day);
- **metrics**: the series in the metrics store labelled ``machine=<id>``;
- **when it was last seen**: its latest event or its latest write to a series labelled with it
  (``instance=<n>`` too, for an instance), whichever is later, so a machine that announces itself
  once and then only writes measurements stays active while its writes keep coming;
- **recent events**: the last ``RECENT`` events of each machine, by their envelope only (time,
  type, instance, subject, id; never the ``data``, which is the machines' own);
- **logs**: where an instance says its log is (``data.log`` in its announcement). The web server
  reads it only within the project (``machine_logs.py``);
- **hand-offs**: when one machine acts on a subject (an event's ``subject``: an order, an issue)
  and then a different machine acts on the same subject, the work passed from the first to the
  second, following one of the first one's events about it (its type): the latest of its last
  few that the second machine announced it listens for; when it announced nothing, the last one,
  which the second machine is then inferred to listen for; when it announced a list and none of
  them is in it, no type (the hand-off is counted, and the map draws no event edge for it: an
  announcement is not overruled by a guess). Inferred from the envelope alone, so it shows how
  machines connect even when none announces what it listens for (a system brought in from
  outside, whose log says who changed what but never who reads). The last machine and its last
  ``TRAIL`` event types per subject are kept for the latest ``SUBJECTS``.

The index reads the bus incrementally: the whole log once, then only what is new, so a refresh
costs one small read however long the log is. Events from before the envelope have no
``source``; they are counted, not attributed."""

from __future__ import annotations

import threading
import time
from collections import Counter, OrderedDict, defaultdict, deque

from ..events import HOST, event_time, machine_and_instance

ANNOUNCE = ("orchestra.machine.started", "orchestra.machine.subscribed")
DAY = 86400.0
ACTIVE_S = 120.0
RECENT = 60
SUBJECTS = 50_000
TRAIL = 4            # a machine's last event types about a subject, kept for crediting the hand-off


class MachineIndex:
    def __init__(self, events):
        self.events = events
        self.offset = 0
        self.total: dict[str, Counter] = defaultdict(Counter)            # machine -> type -> count
        self.recent: dict[tuple[str, str], deque] = defaultdict(deque)   # (machine, type) -> times in the last day
        self.subs: dict[str, set] = defaultdict(set)                     # machine -> types its instances listen for
        self.mode: dict[str, str] = {}
        self.kind: dict[str, str] = {}                                   # machine -> what it announced it is (program, agent, person, service)
        self.package: dict[str, str] = {}                                # machine -> the package it announced it belongs to
        self.about: dict[str, dict] = {}                                 # machine -> the rest of its last announcement (opaque)
        self.instances: dict[str, dict[str, dict]] = defaultdict(dict)  # machine -> instance -> first/last seen
        self.logs: dict[str, dict[str, str]] = defaultdict(dict)        # machine -> instance -> announced log path
        self.latest: dict[str, deque] = defaultdict(lambda: deque(maxlen=RECENT))  # machine -> its last events' envelopes
        self.unattributed = 0
        self.last_on: OrderedDict[str, tuple[str, list[str]]] = OrderedDict()  # subject -> (machine, its last event types) that last acted on it
        self.handoffs: Counter = Counter()                               # (from machine, its event type or None, to machine) -> count
        self.recent_handoffs: dict[tuple[str, str, str], deque] = defaultdict(deque)
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
            for field, into in (("kind", self.kind), ("package", self.package)):
                if isinstance(d.get(field), str) and d[field]:
                    into[machine] = d[field]
            self.about[machine] = {k: v for k, v in d.items() if k not in ("mode", "listens_for", "types", "log", "package", "kind")
                                   and isinstance(v, str | int | float | bool | type(None) | list)}
            if isinstance(d.get("log"), str) and d["log"]:
                self.logs[machine][instance or ""] = d["log"]
            return
        subject = ev.get("subject")
        if subject:
            prev = self.last_on.pop(subject, None)
            if prev and prev[0] == machine:
                trail = [*prev[1][-(TRAIL - 1):], ev["type"]]
            else:
                if prev:
                    subs = self.subs.get(machine)
                    via = next((ty for ty in reversed(prev[1]) if ty in subs), None) if subs else prev[1][-1]
                    self.handoffs[(prev[0], via, machine)] += 1
                    self.recent_handoffs[(prev[0], via, machine)].append(t)
                trail = [ev["type"]]
            self.last_on[subject] = (machine, trail)
            if len(self.last_on) > SUBJECTS:
                self.last_on.popitem(last=False)
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

    def view(self, series: list[tuple[str, dict]], now: float | None = None,
             written: dict[tuple[str, str], float] | None = None) -> dict:
        """``written``: the latest write of each (machine, instance) (``last_writes``)."""
        now = now or time.time()
        written = written or {}
        with self._lock:
            for q in [*self.recent.values(), *self.recent_handoffs.values()]:
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
                insts = []
                for i, v in sorted(self.instances[m].items()):
                    seen = max(v["last"], written.get((m, i), 0.0))
                    insts.append({"id": i or m, "first_seen": v["first"], "last_seen": seen, "active": now - seen < ACTIVE_S})
                wrote = [t for (wm, _), t in written.items() if wm == m]
                last = max([v["last"] for v in self.instances[m].values()] + wrote, default=None)
                first = min((v["first"] for v in self.instances[m].values()), default=None)
                machines.append({"id": m, "bootstrap": m == HOST, "mode": self.mode.get(m), "kind": self.kind.get(m) or ("program" if m == HOST else None),
                                 "package": self.package.get(m), "about": self.about.get(m, {}), "publishes": pubs,
                                 "subscribes": sorted(self.subs.get(m, ())), "metrics": sorted(metrics.get(m, [])),
                                 "logs": sorted(i or m for i in self.logs.get(m, {})),
                                 "instances": [i for i in insts if i["id"] != m] if any(k for k in self.instances[m]) else [],
                                 "first_seen": first, "last_seen": last, "active": bool(last and now - last < ACTIVE_S)})
            types = sorted({p["type"] for x in machines for p in x["publishes"]} | {t for x in machines for t in x["subscribes"]})
            edges = [{"from": x["id"], "to": p["type"], "kind": "publishes", "count": p["count"], "day": p["day"]}
                     for x in machines for p in x["publishes"]]
            edges += [{"from": t, "to": x["id"], "kind": "subscribes"} for x in machines for t in x["subscribes"]]
            handoffs = [{"from": a, "via": ty, "to": b, "count": n, "day": len(self.recent_handoffs.get((a, ty, b), ()))}
                        for (a, ty, b), n in self.handoffs.most_common()]
            return {"machines": machines, "types": types, "edges": edges, "handoffs": handoffs, "unattributed_events": self.unattributed}


def last_writes(dumped: list[tuple[str, dict, list[tuple[float, float]]]]) -> dict[tuple[str, str], float]:
    """The latest write of each (machine, instance) among dumped series (``MetricsStore.dump``),
    from their ``machine`` and ``instance`` labels."""
    out: dict[tuple[str, str], float] = {}
    for _, labels, pts in dumped:
        if labels.get("machine") and pts:
            key = (labels["machine"], labels.get("instance") or "")
            out[key] = max(out.get(key, 0.0), pts[-1][0])
    return out


class _ListBus:
    def __init__(self, evs: list[dict]):
        self.evs = evs

    def end(self) -> int:
        return len(self.evs)

    def read(self, since: int = 0, limit: int = 500) -> tuple[list[dict], int]:
        return self.evs[since:][-limit:], len(self.evs)


def machines_view(events: list[dict], series: list[tuple[str, dict]], now: float | None = None,
                  written: dict[tuple[str, str], float] | None = None) -> dict:
    """The view over a given list of events (for tests and one-off use)."""
    idx = MachineIndex(_ListBus(events))
    idx.update()
    return idx.view(series, now, written)
