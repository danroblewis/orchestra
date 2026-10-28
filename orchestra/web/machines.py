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
  instances differ says so (``agent ×2, program ×1``), never just the last one to announce. So
  does the rest: each instance's latest announcement stands, so one that drops its name or group
  has none, and the machine shows the package, name and group of the instance that announced one
  latest, and passes what is left of its instances' announcements (the latest instance's over the
  others) to the package's card unread. An instance that announces only what it listens for and
  what it is (a part of a machine implemented elsewhere: a plugin's dispatch acting as the
  coordinator) so never erases what another instance said of the machine;
- **publishes**: the event types its instances emitted, with counts (all time and the last day);
- **flows**: the flows of the latest discovery the machine is hypothesised to be associated with
  (``sd.attribute``: its events match a flow's counter in time), each with its confidence and
  why. A hypothesis, never a fact; a series, whoever wrote it or whatever it is labelled, never
  belongs to a machine and is not listed (AGENTS.md rule 7);
- **when it was last seen**: its latest event on the bus (an announcement, a publication, a
  heartbeat: any event with its ``source``), and nothing else. A machine does not produce metrics
  (AGENTS.md rules 2 and 7): a write to a series labelled ``machine=<id>`` says nothing of whether
  the machine is there, and a series so labelled makes no machine and no instance. Never in the
  future: an event stamped ahead counts as seen when it was read;
- **whether it is active**: an instance is active while its last event is within ``ACTIVE_MARGIN``
  times the **cadence** of its events (a cadence over a day counts as a day), and never less than
  ``ACTIVE_FLOOR_S``. A cadence is observed, never taken from what a machine says of itself
  (AGENTS.md rule 2): the median gap between its last ``BEATS`` **beats**. A beat is an event
  (an announcement, a publication, a heartbeat) that comes more than ``BURST_S`` after the
  instance's previous event: the events of one burst (``started`` and ``subscribed`` at a restart,
  the few events of one run of a job) are one beat, so they never shrink the cadence. ``BURST_S``
  is ``ACTIVE_FLOOR_S / ACTIVE_MARGIN``, below which a cadence would not change the answer anyway:
  a machine whose events come faster has no cadence and is active within the floor. So a machine
  that publishes rarely (a scheduled job run every hour, which announces itself and publishes a
  few events each run) is active between its runs by its own rhythm, and a machine that stops is
  quiet after a few of its own beats. A machine is active while any of its instances is;
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

from ..events import HOST, event_time, for_an_instrument, machine_and_instance

ANNOUNCE = ("orchestra.machine.started", "orchestra.machine.subscribed")
DAY = 86400.0
ACTIVE_FLOOR_S = 120.0     # active within at least this, however fast its cadence
ACTIVE_MARGIN = 2.5        # ... and within this many beats of its cadence: a round may be late, or one missed
BEATS = 9                  # the last times kept to observe a cadence
BURST_S = ACTIVE_FLOOR_S / ACTIVE_MARGIN   # an event this soon after the instance's previous one is in the same burst, not a new beat
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
        # machine -> instance -> its package, name, group (group, or else team) and the rest of its
        # latest announcement (opaque), in the order of the instances' latest announcements
        self.cards: dict[str, OrderedDict[str, dict]] = defaultdict(OrderedDict)
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
        if for_an_instrument(ev):
            return                    # the host announcing an instrument, before instruments were told apart
        t = event_time(ev) or 0.0
        seen = min(t, time.time())          # stamped ahead: seen when read, never in the future
        key = instance or ""
        inst = self.instances[machine].get(key)
        burst = inst is not None and seen - inst["last"] <= BURST_S    # the rest of a burst: a restart, or one run's events
        inst = self.instances[machine].setdefault(key, {"first": seen, "last": seen})
        inst["last"] = max(inst["last"], seen)
        beats = self.beats[machine].setdefault(key, deque(maxlen=BEATS))
        if not burst and (not beats or seen > beats[-1]):
            beats.append(seen)
        if ev.get("type") in ANNOUNCE:
            d = ev.get("data") or {}
            self.subs[machine].update(d.get("listens_for") or d.get("types") or [])
            for field, into in (("mode", self.mode), ("kind", self.kind)):
                if isinstance(d.get(field), str) and d[field]:
                    into[machine][key] = d[field]
            card = self.cards[machine].pop(key, {})
            self.cards[machine][key] = card                     # the latest to announce comes last
            if isinstance(d.get("package"), str) and d["package"]:
                card["package"] = d["package"]
            if ev["type"] == "orchestra.machine.started":       # the instance's latest says its name and group, or that there are none
                card["name"] = d.get("name") if isinstance(d.get("name"), str) and d["name"] else None
                card["group"] = next((d[k] for k in ("group", "team") if isinstance(d.get(k), str) and d[k]), None)
            card["about"] = {k: v for k, v in d.items() if k not in ("mode", "listens_for", "types", "log", "package", "kind", "name", "group")
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

    def view(self, now: float | None = None, flows: dict[str, list[dict]] | None = None) -> dict:
        """``flows``: each machine's hypothesised flows (``flow_hypotheses``). Everything else is
        from the bus alone."""
        now = now or time.time()
        flows = flows or {}
        with self._lock:
            for q in [*self.recent.values(), *self.recent_handoffs.values()]:
                while q and q[0] < now - DAY:
                    q.popleft()
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
                for i, v in sorted(self.instances[m].items()):
                    cadence = gaps(self.beats[m].get(i, ()))
                    active = now - v["last"] < active_within(cadence)
                    alive = alive or active
                    insts.append({"id": i or m, "first_seen": v["first"], "last_seen": v["last"], "active": active,
                                  "cadence_s": cadence, "kind": self.kind[m].get(i), "mode": self.mode[m].get(i)})
                last = max((v["last"] for v in self.instances[m].values()), default=None)
                first = min((v["first"] for v in self.instances[m].values()), default=None)
                kinds = Counter(self.kind[m].values())
                cards = list(self.cards[m].values()) if m in self.cards else []
                said = {f: next((c[f] for c in reversed(cards) if c.get(f)), None) for f in ("package", "name", "group")}
                about = {k: v for c in cards for k, v in c.get("about", {}).items()}
                machines.append({"id": m, "bootstrap": m == HOST, "mode": of_instances(Counter(self.mode[m].values())),
                                 "kind": of_instances(kinds) or ("program" if m == HOST else None), "kinds": dict(kinds),
                                 **said, "about": about, "publishes": pubs,
                                 "subscribes": sorted(self.subs.get(m, ())), "flows": flows.get(m, []),
                                 "logs": sorted(i or m for i in self.logs.get(m, {})),
                                 "instances": [i for i in insts if i["id"] != m] if any(k for k in self.instances[m]) else [],
                                 "first_seen": first, "last_seen": last, "active": alive})
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


def flow_hypotheses(model) -> dict[str, list[dict]]:
    """The flows of a discovered model each machine is hypothesised to be associated with
    (``flow.evidence["machines"]``, ``sd.attribute``), best first: what a machine's card says of
    its part in the model. A model saved before 2026-10-27 named machines by a label, not a
    hypothesis, and gives none."""
    out: dict[str, list[dict]] = defaultdict(list)
    for f in (model.flows if model is not None else []):
        for h in ((f.evidence or {}).get("machines") or {}).get("hypotheses") or []:
            if h.get("machine"):
                out[h["machine"]].append({"flow": f.id, "name": f.name, "confidence": h.get("confidence"), "by": h.get("by"),
                                          "events": h.get("events"), "why": h.get("why"), "hypothesis": True})
    return {m: sorted(hs, key=lambda h: (-(h["confidence"] or 0), h["flow"])) for m, hs in out.items()}


class _ListBus:
    def __init__(self, evs: list[dict]):
        self.evs = evs

    def end(self) -> int:
        return len(self.evs)

    def read(self, since: int = 0, limit: int = 500) -> tuple[list[dict], int]:
        return self.evs[since:][-limit:], len(self.evs)


def machines_view(events: list[dict], now: float | None = None, flows: dict[str, list[dict]] | None = None) -> dict:
    """The view over a given list of events (for tests and one-off use)."""
    idx = MachineIndex(_ListBus(events))
    idx.update()
    return idx.view(now, flows)
