"""The Machines page's data: the machines seen on the event bus, their instances and how they are
engaged, and the network of which machine publishes and which listens for which event types.

A machine exists because it shows up on the bus or is counted (AGENTS.md rule 2), or because the
owner declared it (the intended model; declared and measured-never-heard machines are placed by the
declared layer, ``web/intended.py``, ``web/measured.py``): never because a series names it. An instrument (``[[collect]]``, ``[[scrape]]``, ``[[sources]]``) measures the system and is not
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
  these when it starts, with ``orchestra.machine.started`` (its fields, and which are kept per
  instance or per machine, are stated once in SPEC §2, "The announcement"). A group labels machines and
  groups them on the page, never separates them (AGENTS.md rule 4). How it is engaged and what
  kind it is belong to each **instance** (its latest announcement stands): a machine whose
  instances differ says so (``agent ×2, program ×1``), never just the last one to announce. So
  does the rest: each instance's latest announcement stands, so one that drops its name or group
  has none, and the machine shows the package, name and group of the instance that announced one
  latest, and passes what is left of its instances' announcements (the latest instance's over the
  others) to the package's card unread. An instance that announces only what it listens for and
  what it is (a part of a machine implemented elsewhere: a plugin's dispatch acting as one
  of its machines) so never erases what another instance said of the machine;
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
  instance's previous event: the events of one burst (an announcement and the first events at a restart,
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

**Per era** (``sd.eras``): an index may keep only the events of one stretch of time
(``since``, ``until``: an era's start and the next one's), so the map of an era is drawn from
that era's events alone, as its model is discovered from its data alone. An announcement made before
the era still says what a machine is and listens for; it makes no machine active in the era.

The index reads the bus incrementally: the whole log once, then only what is new, so a refresh
costs one small read however long the log is. Events from before the envelope have no
``source``; they are counted, not attributed."""

from __future__ import annotations

import logging
import threading
import time
from collections import Counter, OrderedDict, defaultdict, deque

from ..cadence import BEATS, BURST_S, DAY, active_within, gaps
from ..events import HOST, announcement, event_time, for_an_instrument, machine_and_instance

ANNOUNCE = "orchestra.machine.started"
PAGE = 10_000                     # events folded per read
log = logging.getLogger(__name__)
# records about a declaration (the intended model), not work on their subject: never a hand-off
NOT_WORK = ("orchestra.intent.changed", "orchestra.intent.requested")
# Orchestra's own event type for a request from the pages (sd/intended/requests.py): a source that
# publishes nothing else is the person pressing the pages' controls. It stays a machine (rule 2); its
# card says what it is, since Orchestra knows what its own event type means.
REQUESTED = "orchestra.intent.requested"
ASKER_NOTE = "requests sent from the pages' controls (confirm, discard, kind switch)"
RATE_S = 600         # a publication rate is over the last ten minutes, or over the machine's life when shorter
# the cadence rule (beats, bursts, how long an instance stays active) is orchestra/cadence.py's,
# shared with the host's quiet watch (orchestra/quiet.py)
RECENT = 60
SUBJECTS = 50_000
TRAIL = 4            # a machine's last event types about a subject, kept for crediting the hand-off


class MachineIndex:
    def __init__(self, events, since: float | None = None, until: float | None = None):
        self.events = events
        self.since, self.until = since, until               # only the events in [since, until): one era
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
        self.skipped = 0                                                  # events that could not be read
        self.last_on: OrderedDict[str, tuple[str, list[str]]] = OrderedDict()  # subject -> (machine, its last event types) that last acted on it
        self.handoffs: Counter = Counter()                               # (from machine, its event type or None, to machine) -> count
        self.recent_handoffs: dict[tuple[str, str, str], deque] = defaultdict(deque)
        self._lock = threading.Lock()

    def update(self) -> None:
        """Fold in whatever is new on the bus since the last call."""
        with self._lock:
            while self.events.end() > self.offset:
                evs, nxt = self.events.page(self.offset, PAGE)        # forward, bounded: nothing pushed out
                for ev in evs:
                    self._fold_one(ev)
                if nxt <= self.offset:
                    break
                self.offset = nxt

    def _fold_one(self, ev: dict) -> None:
        """Fold one event; one that cannot be read (a malformed line written past the endpoint's
        checks) is skipped and counted, never fatal, so the index never sticks at its offset."""
        try:
            self._fold(ev)
        except Exception as e:  # noqa: BLE001 - one bad event must not stop the index
            self.skipped += 1
            if self.skipped == 1:
                log.warning("machines: skipped an event that could not be read (%s: %s); later ones are counted in skipped",
                            type(e).__name__, e)

    def _fold(self, ev: dict) -> None:
        if self.since is not None or self.until is not None:
            t = event_time(ev)
            if t is None or (self.until is not None and t >= self.until):
                return
            if self.since is not None and t < self.since:
                # before the era: an announcement still says what a machine is and listens for,
                # but is no activity in the era
                machine, instance = machine_and_instance(ev.get("source"))
                if machine and ev.get("type") == ANNOUNCE and not for_an_instrument(ev):
                    self._announced(ev, machine, instance)
                return
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
        if ev.get("type") == ANNOUNCE:
            self._announced(ev, machine, instance)
            return
        subject = ev.get("subject")
        if subject and ev.get("type") not in NOT_WORK:
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

    def _announced(self, ev: dict, machine: str, instance: str | None) -> None:
        """What an instance says of itself: what it listens for, how it is engaged, its kind,
        and its card (package, name, group, details), kept per instance so one that says less
        erases nothing another said; and its log."""
        key = instance or ""
        d = announcement(ev)
        self.subs[machine].update(d["listens_for"])
        for field, into in (("mode", self.mode), ("kind", self.kind)):
            if isinstance(d.get(field), str) and d[field]:
                into[machine][key] = d[field]
        card = self.cards[machine].pop(key, {})
        self.cards[machine][key] = card                     # the latest to announce comes last
        if isinstance(d.get("package"), str) and d["package"]:
            card["package"] = d["package"]
        # the instance's latest says its name and group, or that there are none
        card["name"] = d.get("name") if isinstance(d.get("name"), str) and d["name"] else None
        card["group"] = next((d[k] for k in ("group", "team") if isinstance(d.get(k), str) and d[k]), None)
        card["about"] = {k: v for k, v in d.items() if k not in ("mode", "listens_for", "log", "package", "kind", "name", "group", "team")
                         and isinstance(v, str | int | float | bool | type(None) | list)}
        if isinstance(d.get("log"), str) and d["log"]:
            self.logs[machine][instance or ""] = d["log"]

    def bus_since(self) -> float | None:
        """When the bus was first heard: the earliest any instance was first seen, or None."""
        with self._lock:
            return min((v["first"] for insts in self.instances.values() for v in insts.values()), default=None)

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
            # (in an era, only those active in it: an announcement before it describes, it does not make one)
            seen = set(self.total) | set(self.instances) | ({HOST} if self.since is not None else set(self.subs) | {HOST})
            ids = sorted(seen, key=lambda m: (m != HOST, m))
            machines = []
            for m in ids:
                pubs = []
                first = min((v["first"] for v in self.instances[m].values()), default=None)
                # over the last ten minutes, or the time since the machine was first seen when that is
                # shorter (a minute at least): a machine 50 s old publishing 10 events is 10 a minute, not 1
                minutes = max(1.0, min(RATE_S, now - first) / 60) if first is not None else RATE_S / 60
                for ty, n in self.total[m].most_common():
                    q = self.recent.get((m, ty), ())
                    n_10m = sum(1 for t in q if t >= now - RATE_S)
                    # ``n_10m``: the count the rate is of, over ``window_s`` (ten minutes, or since first seen)
                    pubs.append({"type": ty, "count": n, "day": len(q), "n_10m": n_10m, "window_s": round(minutes * 60),
                                 "per_min_10m": round(n_10m / minutes, 2)})
                insts, alive = [], False
                for i, v in sorted(self.instances[m].items()):
                    cadence = gaps(self.beats[m].get(i, ()))
                    active = now - v["last"] < active_within(cadence)
                    alive = alive or active
                    insts.append({"id": i or m, "first_seen": v["first"], "last_seen": v["last"], "active": active,
                                  "cadence_s": cadence, "kind": self.kind[m].get(i), "mode": self.mode[m].get(i)})
                last = max((v["last"] for v in self.instances[m].values()), default=None)
                kinds = Counter(self.kind[m].values())
                n_inst = len(self.instances[m])
                asker = bool(self.total[m]) and set(self.total[m]) == {REQUESTED} and not kinds
                cards = list(self.cards[m].values()) if m in self.cards else []
                said = {f: next((c[f] for c in reversed(cards) if c.get(f)), None) for f in ("package", "name", "group")}
                about = {k: v for c in cards for k, v in c.get("about", {}).items()}
                machines.append({"id": m, "bootstrap": m == HOST, "mode": of_instances(Counter(self.mode[m].values())),
                                 "kind": of_instances(kinds, n_inst) or ("program" if m == HOST else "person" if asker else None), "kinds": dict(kinds),
                                 **({"note": ASKER_NOTE} if asker else {}),
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


def of_instances(counts: Counter, instances: int | None = None) -> str | None:
    """What instances announced (their kind, or how they are engaged), in one phrase: the one
    value when they agree, else each with how many say it (``agent ×2, program ×1``). With
    ``instances`` (how many there are), the ones that announced nothing are counted too, so the
    phrase adds up: ``agent ×2, program ×1, 1 unannounced``."""
    quiet = max(0, (instances or 0) - sum(counts.values()))
    if not counts:
        return None
    if len(counts) == 1 and not quiet:
        return next(iter(counts))
    said = ", ".join(f"{v} ×{n}" for v, n in sorted(counts.items(), key=lambda x: (-x[1], x[0])))
    return said + (f", {quiet} unannounced" if quiet else "")


def model_parts(model) -> dict:
    """The latest model's stocks and flows as the pages name them (sd-graph.js names): ids, ends,
    and the series and counters their names come from. Nothing else of the model."""
    if model is None:
        return {"stocks": [], "flows": []}

    def ref(r):
        return {"name": r.name, "labels": dict(r.labels)} if r is not None else None
    return {"stocks": [{"id": s.id, "name": s.name, "series": ref(s.series)} for s in model.stocks],
            "flows": [{"id": f.id, "name": f.name, "from": f.src, "to": f.dst, "counter": ref(f.counter),
                       "measured_by": [ref(c) for c in f.measured_by], "evidence": {k: v for k, v in (f.evidence or {}).items() if k == "same_as"}}
                      for f in model.flows]}


def flow_hypotheses(model) -> dict[str, list[dict]]:
    """The flows of a discovered model each machine is hypothesised to be associated with
    (``flow.evidence["machines"]``, ``sd.attribute``), best first: what a machine's card says of
    its part in the model. A model saved before 2026-10-27 named machines by a label, not a
    hypothesis, and gives none."""
    out: dict[str, list[dict]] = defaultdict(list)
    for f in (model.flows if model is not None else []):
        for h in ((f.evidence or {}).get("machines") or {}).get("hypotheses") or []:
            if h.get("machine"):
                out[h["machine"]].append({"flow": f.id, "name": f.name, "from": f.src, "to": f.dst, "confidence": h.get("confidence"), "by": h.get("by"),
                                          "events": h.get("events"), "why": h.get("why"), "hypothesis": True})
    return {m: sorted(hs, key=lambda h: (-(h["confidence"] or 0), h["flow"])) for m, hs in out.items()}


class _ListBus:
    def __init__(self, evs: list[dict]):
        self.evs = evs

    def end(self) -> int:
        return len(self.evs)

    def read(self, since: int = 0, limit: int = 500) -> tuple[list[dict], int]:
        return self.evs[since:][-limit:], len(self.evs)

    def page(self, since: int = 0, limit: int = 500) -> tuple[list[dict], int]:
        if since >= len(self.evs):
            return [], len(self.evs)
        bound = min(since + max(1, limit), len(self.evs))
        return self.evs[since:bound], bound


def machines_view(events: list[dict], now: float | None = None, flows: dict[str, list[dict]] | None = None,
                  since: float | None = None, until: float | None = None) -> dict:
    """The view over a given list of events (for tests and one-off use), within [since, until)."""
    idx = MachineIndex(_ListBus(events), since, until)
    idx.update()
    return idx.view(now, flows)
