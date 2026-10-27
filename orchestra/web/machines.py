"""The Machines page's data: the machines seen on the event bus, their instances and how they are
engaged, and the network of which machine publishes and which listens for which event types.

A machine exists because it shows up on the bus (AGENTS.md rule 2): never because a series names
it. An instrument (``[[collect]]``, ``[[scrape]]``, ``[[sources]]``) measures the system and is not
a machine (rule 7): it is on the Instruments page, not here. Announcements the host made on an
instrument's behalf before 2026-10-27 (``orchestra.machine.started`` with ``data.collector``) are
left out, so a detector seen then is not a machine now.

Everything here is observed, or announced by the machine itself:
- a **machine** is the machine part of a CloudEvents ``source``; a source ``<machine>/<instance>``
  is one **instance** of it (``baker/1``, ``baker/2``: one machine, two instances). Orchestra's own
  host is a machine too;
- **how it is engaged** (continuous, scheduled or ad hoc), **what it listens for**, **what kind
  of thing it is** (a program, an agent, a service, a person), **which package** it belongs to, the **name**
  to show it by and the **group** it belongs to (a team): until the bus adapters provide
  subscriptions the backend can list (docs/proposals/empty-orchestra.md §3), an instance announces
  these when it starts, with ``orchestra.machine.started`` (``data.mode``, ``data.listens_for``,
  ``data.kind``, ``data.package``, ``data.name``, ``data.group`` or else ``data.team``;
  ``orchestra.machine.subscribed`` with ``data.types`` is read too). A group labels machines and
  groups them on the page, never separates them (AGENTS.md rule 4). How it is engaged and what
  kind it is belong to each **instance** (its latest announcement stands): a machine whose
  instances differ says so (``agent ×2, program ×1``), never just the last one to announce. For the
  rest the machine's latest announcement stands, and what is left of it is passed to the
  package's card unread;
- **publishes**: the event types its instances emitted, with counts (all time and the last day);
- **metrics**: the series in the metrics store labelled ``machine=<id>`` (shown on a machine's card
  when it is a machine; a series alone never makes one), and the series read from
  another store (``[[sources]]``) that the latest discovery found labelled with it: such a
  machine is marked ``from_source`` (the source's name), read from the discovery record, never by
  querying the source from the page;
- **when it was last seen**: its latest event or its latest write to a series labelled with it
  (``instance=<n>`` too, for an instance), whichever is later, so a machine that announces itself
  once and then only writes measurements stays active while its writes keep coming. Never in the
  future: an event stamped ahead counts as seen when it was read, and a point stamped more than
  ``FUTURE_SKEW_S`` ahead is not counted (the stores refuse such points now; older ones remain);
- **whether it is active**: an instance is active while its last event is within ``ACTIVE_MARGIN``
  times the **cadence** of its events, or its last write within that many of its writes', and
  never less than ``ACTIVE_FLOOR_S``. A cadence is observed, never taken from what a machine says
  of itself (AGENTS.md rule 2): the median gap between its last few events (announcements, which
  come in bursts at a restart, left out) or its last few writes. So a collector run every 15
  minutes is active between its rounds, and a machine that stops is quiet after a few of its own
  beats. A machine is active while any of its instances is;
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
from itertools import pairwise
from statistics import median

from ..events import HOST, event_time, machine_and_instance
from ..metrics import FUTURE_SKEW_S

ANNOUNCE = ("orchestra.machine.started", "orchestra.machine.subscribed")
DAY = 86400.0
ACTIVE_FLOOR_S = 120.0     # active within at least this, however fast its cadence
ACTIVE_MARGIN = 2.5        # ... and within this many beats of its cadence: a round may be late, or one missed
BEATS = 9                  # the last times kept to observe a cadence
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
        self.mode: dict[str, dict[str, str]] = defaultdict(dict)        # machine -> instance -> how it said it is engaged
        self.kind: dict[str, dict[str, str]] = defaultdict(dict)        # machine -> instance -> what it said it is (program, agent, person, ...)
        self.beats: dict[str, dict[str, deque]] = defaultdict(dict)     # machine -> instance -> its last event times
        self.package: dict[str, str] = {}                                # machine -> the package it announced it belongs to
        self.name: dict[str, str] = {}                                   # machine -> the name it announced, to show it by
        self.group: dict[str, str] = {}                                  # machine -> the group it announced (group, or else team)
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
        if ev.get("type") == "orchestra.machine.started" and "collector" in (ev.get("data") or {}):
            return                    # the host announcing an instrument, before instruments were told apart
        t = event_time(ev) or 0.0
        seen = min(t, time.time())          # stamped ahead: seen when read, never in the future
        key = instance or ""
        inst = self.instances[machine].setdefault(key, {"first": seen, "last": seen})
        inst["last"] = max(inst["last"], seen)
        if ev.get("type") not in ANNOUNCE:           # announcements come in bursts at a restart: not a beat
            beats = self.beats[machine].setdefault(key, deque(maxlen=BEATS))
            if not beats or seen > beats[-1]:
                beats.append(seen)
        if ev.get("type") in ANNOUNCE:
            d = ev.get("data") or {}
            self.subs[machine].update(d.get("listens_for") or d.get("types") or [])
            for field, into in (("mode", self.mode), ("kind", self.kind)):
                if isinstance(d.get(field), str) and d[field]:
                    into[machine][key] = d[field]
            if isinstance(d.get("package"), str) and d["package"]:
                self.package[machine] = d["package"]
            if ev["type"] == "orchestra.machine.started":       # the latest says the name and group, or that there are none
                name = d.get("name") if isinstance(d.get("name"), str) and d["name"] else None
                group = next((d[k] for k in ("group", "team") if isinstance(d.get(k), str) and d[k]), None)
                for value, into in ((name, self.name), (group, self.group)):
                    if value:
                        into[machine] = value
                    else:
                        into.pop(machine, None)
            self.about[machine] = {k: v for k, v in d.items() if k not in ("mode", "listens_for", "types", "log", "package", "kind", "name", "group")
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
             written: dict[tuple[str, str], float] | None = None, remote: list[tuple[str, dict, str]] | None = None,
             write_beats: dict[tuple[str, str], float] | None = None) -> dict:
        """``written``: the latest write of each (machine, instance) (``last_writes``);
        ``remote``: series read from other stores, with their source (``remote_series``);
        ``write_beats``: the gap each (machine, instance) is observed to write at (``write_cadence``)."""
        now = now or time.time()
        written = written or {}
        write_beats = write_beats or {}
        with self._lock:
            for q in [*self.recent.values(), *self.recent_handoffs.values()]:
                while q and q[0] < now - DAY:
                    q.popleft()
            metrics: dict[str, set] = defaultdict(set)
            from_source: dict[str, str] = {}
            for name, labels, source in [*((n, lab, None) for n, lab in series), *(remote or [])]:
                if labels.get("machine"):
                    extra = ",".join(f'{k}="{v}"' for k, v in sorted(labels.items()) if k not in ("project", "machine", "instance"))
                    metrics[labels["machine"]].add(name + (f"{{{extra}}}" if extra else ""))
                    if source:
                        from_source.setdefault(labels["machine"], source)
            # machines are what the bus shows; a series labelled with a name makes no machine
            ids = sorted(set(self.total) | set(self.subs) | set(self.instances) | {HOST}, key=lambda m: (m != HOST, m))
            machines = []
            for m in ids:
                pubs = []
                for ty, n in self.total[m].most_common():
                    q = self.recent.get((m, ty), ())
                    pubs.append({"type": ty, "count": n, "day": len(q),
                                 "per_min_10m": round(sum(1 for t in q if t >= now - 600) / 10, 2)})
                insts, alive = [], False
                keys = set(self.instances[m]) | {i for (wm, i) in written if wm == m}
                for i in sorted(keys):
                    v = self.instances[m].get(i)
                    said, wrote_at = (v["last"] if v else 0.0), written.get((m, i), 0.0)
                    by_events, by_writes = gaps(self.beats[m].get(i, ())), write_beats.get((m, i))
                    # each rhythm judged by its own cadence: events every few seconds and a write an hour
                    active = (bool(v) and now - said < active_within(by_events)) or (wrote_at > 0 and now - wrote_at < active_within(by_writes))
                    alive = alive or active
                    if v:
                        insts.append({"id": i or m, "first_seen": v["first"], "last_seen": max(said, wrote_at), "active": active,
                                      "cadence_s": {"events": by_events, "writes": by_writes},
                                      "kind": self.kind[m].get(i), "mode": self.mode[m].get(i)})
                wrote = [t for (wm, _), t in written.items() if wm == m]
                last = max([v["last"] for v in self.instances[m].values()] + wrote, default=None)
                first = min((v["first"] for v in self.instances[m].values()), default=None)
                kinds = Counter(self.kind[m].values())
                machines.append({"id": m, "bootstrap": m == HOST, "mode": of_instances(Counter(self.mode[m].values())),
                                 "kind": of_instances(kinds) or ("program" if m == HOST else None), "kinds": dict(kinds),
                                 "package": self.package.get(m), "name": self.name.get(m), "group": self.group.get(m),
                                 "about": self.about.get(m, {}), "publishes": pubs,
                                 "subscribes": sorted(self.subs.get(m, ())), "metrics": sorted(metrics.get(m, [])),
                                 "logs": sorted(i or m for i in self.logs.get(m, {})),
                                 "instances": [i for i in insts if i["id"] != m] if any(k for k in self.instances[m]) else [],
                                 "first_seen": first, "last_seen": last, "active": alive,
                                 **({"from_source": from_source[m]} if m in from_source else {})})
            types = sorted({p["type"] for x in machines for p in x["publishes"]} | {t for x in machines for t in x["subscribes"]})
            edges = [{"from": x["id"], "to": p["type"], "kind": "publishes", "count": p["count"], "day": p["day"]}
                     for x in machines for p in x["publishes"]]
            edges += [{"from": t, "to": x["id"], "kind": "subscribes"} for x in machines for t in x["subscribes"]]
            handoffs = [{"from": a, "via": ty, "to": b, "count": n, "day": len(self.recent_handoffs.get((a, ty, b), ()))}
                        for (a, ty, b), n in self.handoffs.most_common()]
            return {"machines": machines, "types": types, "edges": edges, "handoffs": handoffs, "unattributed_events": self.unattributed}


def active_within(cadence: float | None) -> float:
    """How long after it was last seen an instance with this cadence is still active (a cadence
    longer than a day counts as a day)."""
    return max(ACTIVE_FLOOR_S, ACTIVE_MARGIN * min(cadence, DAY)) if cadence else ACTIVE_FLOOR_S


def gaps(times) -> float | None:
    """The median gap between the last ``BEATS`` distinct times, or ``None`` with fewer than two."""
    ts = sorted(set(times))[-BEATS:]
    return median(b - a for a, b in pairwise(ts)) if len(ts) > 1 else None


def of_instances(counts: Counter) -> str | None:
    """What instances announced (their kind, or how they are engaged), in one phrase: the one
    value when they agree, else each with how many say it (``agent ×2, program ×1``)."""
    if len(counts) <= 1:
        return next(iter(counts), None)
    return ", ".join(f"{v} ×{n}" for v, n in sorted(counts.items(), key=lambda x: (-x[1], x[0])))


def remote_series(model) -> list[tuple[str, dict, str]]:
    """The series of another store (``[[sources]]``) a discovered model is bound to and that name
    a machine (its stocks', its flows' and its machines' series), with their source: what the
    Machines page knows of remote machines, read from the discovery record."""
    if model is None:
        return []
    refs = [s.series for s in model.stocks] + [r for f in model.flows for r in [f.counter, *f.measured_by]]
    refs += [r for m in model.machines for r in m.observed_by]
    seen, out = set(), []
    for r in refs:
        if r is not None and r.source not in (None, "own") and r.labels.get("machine"):
            key = (r.name, tuple(sorted(r.labels.items())))
            if key not in seen:
                seen.add(key)
                out.append((r.name, dict(r.labels), r.source))
    return out


def _writes(dumped, now: float | None):
    """Each dumped series' (machine, instance) and its points' times, without those stamped more
    than ``FUTURE_SKEW_S`` past ``now``."""
    limit = (now or time.time()) + FUTURE_SKEW_S
    for _, labels, pts in dumped:
        if labels.get("machine") and pts:
            yield (labels["machine"], labels.get("instance") or ""), [t for t, _ in pts[-BEATS * 4:] if t <= limit]


def last_writes(dumped: list[tuple[str, dict, list[tuple[float, float]]]], now: float | None = None) -> dict[tuple[str, str], float]:
    """The latest write of each (machine, instance) among dumped series (``MetricsStore.dump``),
    from their ``machine`` and ``instance`` labels; a point stamped in the future is not a write."""
    out: dict[tuple[str, str], float] = {}
    for key, ts in _writes(dumped, now):
        if ts:
            out[key] = max(out.get(key, 0.0), ts[-1])
    return out


def write_cadence(dumped: list[tuple[str, dict, list[tuple[float, float]]]], now: float | None = None) -> dict[tuple[str, str], float]:
    """The gap each (machine, instance) is observed to write at: the median gap between the last
    times any of its series was written (``gaps``)."""
    times: dict[tuple[str, str], set] = defaultdict(set)
    for key, ts in _writes(dumped, now):
        times[key].update(ts)
    return {key: g for key, ts in times.items() if (g := gaps(ts))}


class _ListBus:
    def __init__(self, evs: list[dict]):
        self.evs = evs

    def end(self) -> int:
        return len(self.evs)

    def read(self, since: int = 0, limit: int = 500) -> tuple[list[dict], int]:
        return self.evs[since:][-limit:], len(self.evs)


def machines_view(events: list[dict], series: list[tuple[str, dict]], now: float | None = None,
                  written: dict[tuple[str, str], float] | None = None, remote: list[tuple[str, dict, str]] | None = None,
                  write_beats: dict[tuple[str, str], float] | None = None) -> dict:
    """The view over a given list of events (for tests and one-off use)."""
    idx = MachineIndex(_ListBus(events))
    idx.update()
    return idx.view(series, now, written, remote, write_beats)
