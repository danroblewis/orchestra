"""Demo 16's system: a discrete-event simulation (DES) of an on-call support flow, not a system dynamics model
(docs/demos/agent-verify.md).

Time is in hours. A heap of timed events drives it; each item (an alert or ticket) is an entity with its own random
draws; nothing here is an equation of stocks and flows.

- Items arrive by a non-homogeneous Poisson process (thinning), busier by day than at night and on weekdays.
- Human on-call engineers (the shift schedule sets how many are on shift each hour) triage one item at a time,
  oldest first; triage takes a lognormal time. 30% of triaged items need a fix: the dev team works fixes in parallel
  (a lognormal time each); the rest are resolved at triage.
- A resolved item may reopen later (5%, after an exponential delay): it goes back to the queue (rework).
- From hour `agent_from` on, an AI agent (a separate program, `Agent`) takes part: it reacts to the same events,
  takes new items when it has a free slot, handles each for a few minutes, and then either resolves it, closes it
  wrongly (a misroute: the item reopens a few hours later), or hands it back to the humans with a triage note that
  shortens their triage. Its actions go into the same event log.

The arrivals, and each item's own draws, come from random streams that do not depend on what happens to other
items, so a run with the agent and the run without it see the same items (common random numbers): the difference
between the two runs is the agent's true effect.

Sampled every `every` hours (a quarter hour by default; what monitoring sees): items queued (waiting for triage, including one the agent is reading),
in triage, in fix, resolved (closed, net of reopens), and the engineers on shift and the new items that hour."""

from __future__ import annotations

import heapq
import math
import random
from dataclasses import dataclass, field

DAY = 24.0

SYSTEM = {
    "arrivals_mean": 4.6,          # new items an hour on a weekday (mean over the day)
    "arrivals_amp": 0.6,           # day/night swing (share of the mean)
    "weekend": 0.6,                # weekend arrivals, share of a weekday's
    "triage_mean": 0.45, "triage_cv": 0.6,   # hours of an engineer's triage (lognormal)
    "fix_share": 0.30,             # share of triaged items that need a fix
    "fix_mean": 4.0, "fix_cv": 0.5,          # hours a fix takes (the dev team works fixes in parallel)
    "reopen_share": 0.05,          # share of resolved items that reopen ...
    "reopen_mean": 24.0,           # ... after this many hours on average (exponential)
}


def engineers_at(t: float) -> int:
    """Engineers on shift at hour t (t = 0 is Monday 00:00): 4 by day on weekdays (08-20), 2 by day at weekends,
    1 at night, plus a handover hour (19-20) with one more."""
    day, hour = int(t // DAY) % 7, t % DAY
    weekend = day >= 5
    if 8 <= hour < 20:
        return (2 if weekend else 4) + (1 if 19 <= hour < 20 and not weekend else 0)
    return 1


def arrival_rate(t: float, S: dict = SYSTEM) -> float:
    day, hour = int(t // DAY) % 7, t % DAY
    base = S["arrivals_mean"] * (S["weekend"] if day >= 5 else 1.0)
    return max(0.0, base * (1 + S["arrivals_amp"] * math.sin(2 * math.pi * (hour - 8) / DAY)))


def _lognormal(r: random.Random, mean: float, cv: float) -> float:
    s2 = math.log(1 + cv * cv)
    return r.lognormvariate(math.log(mean) - s2 / 2, math.sqrt(s2))


@dataclass
class Item:
    id: int
    created: float
    passes: int = 0                # how many times it has entered the queue before (0: new)
    noted: bool = False            # the agent left a triage note
    agent_seen: bool = False
    state: str = "queued"
    open_since: float = 0.0
    open_hours: float = 0.0        # time spent open (queued, in triage, in fix), summed over every pass
    closed_at: float | None = None
    misrouted: bool = False
    draws: dict = field(default_factory=dict)


AGENTS = {     # the agent variants (agent_verify.AGENT_VARIANTS has their plain names)
    "good": {"slots": 3, "handle_mean": 0.07, "resolve": 0.35, "misroute": 0.02, "note": 0.7, "misroute_reopen_mean": 6.0},
    "weak": {"slots": 3, "handle_mean": 0.07, "resolve": 0.10, "misroute": 0.02, "note": 0.95, "misroute_reopen_mean": 6.0},
    "misrouting": {"slots": 3, "handle_mean": 0.07, "resolve": 0.20, "misroute": 0.18, "note": 0.7, "misroute_reopen_mean": 6.0},
}


class Agent:
    """The AI agent: a separate program. The simulation tells it about events (`on_new_item`, `on_slot_free`); it
    decides by its own rules and schedules its own events through `sim.schedule`. Its rules: take a new item (never
    a reopened one) whenever a slot is free; read it for a lognormal time (mean `handle_mean` hours); then resolve it
    (share `resolve`), close it wrongly (share `misroute`: it reopens after an exponential delay), or hand it to the
    humans with a note that multiplies their triage time by `note`."""

    def __init__(self, sim: DES, cfg: dict, start: float):
        self.sim, self.cfg, self.start = sim, cfg, start
        self.free = cfg["slots"]
        self.waiting: list[Item] = []          # new items it has not seen yet, oldest first

    def on_new_item(self, it: Item) -> None:
        if self.sim.now < self.start:
            return
        self.waiting.append(it)
        self._take()

    def _take(self) -> None:
        while self.free > 0 and self.waiting:
            it = self.waiting.pop(0)
            if it.state != "queued" or it.agent_seen:
                continue                       # a human took it first
            it.agent_seen = True
            it.state = "with_agent"
            self.free -= 1
            r = it.draws["rng"]
            took = _lognormal(r, self.cfg["handle_mean"], 0.5)
            self.sim.log("agent", "takes", it)
            self.sim.schedule(self.sim.now + took, "agent_done", it)

    def done(self, it: Item) -> None:
        self.free += 1
        u = it.draws["agent_u"]
        c = self.cfg
        if u < c["resolve"]:
            self.sim.log("agent", "resolves", it)
            self.sim.resolve(it, "agent")
        elif u < c["resolve"] + c["misroute"]:
            it.misrouted = True
            self.sim.log("agent", "misroutes", it)
            self.sim.resolve(it, "agent", reopen_after=it.draws["rng"].expovariate(1 / c["misroute_reopen_mean"]))
        else:
            it.noted = True
            it.state = "queued"
            self.sim.log("agent", "hands off", it)
            self.sim.dispatch()
        self._take()


class DES:
    """One run. `run()` returns the hourly samples, the event log and per-item records."""

    def __init__(self, hours: int, seed: int = 16, agent: dict | None = None, agent_from: float = math.inf,
                 system: dict = SYSTEM, log_from: float = 0.0, every: float = 0.25):
        self.hours, self.seed, self.S, self.every = int(hours), int(seed), system, float(every)
        self.now = 0.0
        self.heap: list = []
        self.seq = 0
        self.items: list[Item] = []
        self.queue: list[Item] = []            # waiting for a human, kept by creation time (oldest first)
        self.on_shift = engineers_at(0.0)
        self.busy = 0
        self.events: list[tuple] = []          # (hour, who, what, item id)
        self.log_from = log_from
        self.counts = {"arrived": 0, "reopened": 0, "agent_takes": 0, "agent_resolves": 0, "agent_misroutes": 0,
                       "agent_hands_off": 0, "resolved_by_human": 0, "resolved_by_agent": 0}
        self.agent = Agent(self, agent, agent_from) if agent else None

    # ---- the event machinery ----
    def schedule(self, t: float, kind: str, obj=None) -> None:
        self.seq += 1
        heapq.heappush(self.heap, (t, self.seq, kind, obj))

    def log(self, who: str, what: str, it: Item) -> None:
        key = {"takes": "agent_takes", "resolves": "agent_resolves", "misroutes": "agent_misroutes", "hands off": "agent_hands_off"}
        if who == "agent":
            self.counts[key[what]] += 1
        if self.now >= self.log_from:
            self.events.append((round(self.now, 3), who, what, it.id))

    def _item_rng(self, i: int, p: int) -> random.Random:
        return random.Random(f"{self.seed}/item/{i}/{p}")

    def _new_item(self) -> Item:
        it = Item(id=len(self.items), created=self.now, open_since=self.now)
        self._draw(it)
        self.items.append(it)
        return it

    def _draw(self, it: Item) -> None:
        """The item's own random numbers for this pass (the same whatever happens to other items)."""
        r = self._item_rng(it.id, it.passes)
        S = self.S
        it.draws = {"triage": _lognormal(r, S["triage_mean"], S["triage_cv"]), "fix": r.random() < S["fix_share"],
                    "fix_time": _lognormal(r, S["fix_mean"], S["fix_cv"]), "reopen": r.random() < S["reopen_share"],
                    "reopen_after": r.expovariate(1 / S["reopen_mean"]), "agent_u": r.random(), "rng": r}

    def run(self) -> dict:
        arr = random.Random(f"{self.seed}/arrivals")
        lam_max = max(arrival_rate(h + 0.5, self.S) for h in range(7 * 24)) * 1.1
        t = 0.0
        while True:                                            # thinning: the arrival times, fixed by the seed
            t += arr.expovariate(lam_max)
            if t >= self.hours:
                break
            if arr.random() * lam_max < arrival_rate(t, self.S):
                self.schedule(t, "arrive")
        for h in range(1, self.hours + 1):
            self.schedule(float(h), "shift")
        n_samples = int(round(self.hours / self.every))
        for k in range(1, n_samples + 1):
            self.schedule(k * self.every + 1e-9, "sample")     # after a shift change at the same time
        samples = {k: [] for k in ("queued", "in_triage", "in_fix", "resolved", "engineers", "new_items",
                                   "with_agent", "reopened_total")}
        new_step = 0
        eng_time = 0.0
        last = 0.0
        while self.heap:
            t, _, kind, obj = heapq.heappop(self.heap)
            eng_time += self.on_shift * (t - last)
            last = self.now = t
            if kind == "arrive":
                it = self._new_item()
                self.counts["arrived"] += 1
                new_step += 1
                self.log("source", "opens", it)
                self.queue.append(it)
                if self.agent:
                    self.agent.on_new_item(it)
                self.dispatch()
            elif kind == "triage_done":
                self.busy -= 1
                it = obj
                if it.draws["fix"]:
                    it.state = "in_fix"
                    self.log("engineer", "sends to fix", it)
                    self.schedule(self.now + it.draws["fix_time"], "fix_done", it)
                else:
                    self.log("engineer", "resolves", it)
                    self.resolve(it, "human")
                self.dispatch()
            elif kind == "fix_done":
                self.log("dev team", "fixes", obj)
                self.resolve(obj, "human")
            elif kind == "reopen":
                it = obj
                it.passes += 1
                self._draw(it)
                it.state, it.noted, it.closed_at = "queued", False, None
                it.open_since = self.now
                self.counts["reopened"] += 1
                self.log("customer", "reopens", it)
                self.queue.append(it)
                self.queue.sort(key=lambda x: x.created)
                self.dispatch()
            elif kind == "agent_done":
                self.agent.done(obj)
            elif kind == "shift":
                self.on_shift = engineers_at(self.now)
                self.dispatch()
            elif kind == "sample":
                n = {"queued": 0, "with_agent": 0, "in_triage": 0, "in_fix": 0, "resolved": 0}
                for it in self.items:
                    n[it.state if it.state in n else "resolved"] += 1
                samples["queued"].append(n["queued"] + n["with_agent"])
                samples["with_agent"].append(n["with_agent"])
                samples["in_triage"].append(n["in_triage"])
                samples["in_fix"].append(n["in_fix"])
                samples["resolved"].append(n["resolved"])
                samples["engineers"].append(eng_time / self.every)     # the mean on shift over the step
                samples["new_items"].append(new_step)
                samples["reopened_total"].append(self.counts["reopened"])
                new_step, eng_time = 0, 0.0
                if len(samples["queued"]) >= n_samples:
                    break
        return {"t": list(range(1, n_samples + 1)), "every": self.every, "samples": samples, "events": self.events, "counts": dict(self.counts),
                "items": [{"id": it.id, "created": it.created, "open_hours": it.open_hours + (self.now - it.open_since if it.state != "resolved" else 0.0),
                           "closed": it.state == "resolved", "passes": it.passes, "agent_seen": it.agent_seen,
                           "misrouted": it.misrouted} for it in self.items]}

    def dispatch(self) -> None:
        """Free engineers take the oldest waiting items (an item the agent is reading is not waiting)."""
        while self.busy < self.on_shift:
            it = next((x for x in self.queue if x.state == "queued"), None)
            if it is None:
                return
            self.queue.remove(it)
            it.state = "in_triage"
            self.busy += 1
            took = it.draws["triage"] * (self.agent.cfg["note"] if it.noted and self.agent else 1.0)
            self.log("engineer", "triages" + (" (with the agent's note)" if it.noted else ""), it)
            self.schedule(self.now + took, "triage_done", it)

    def resolve(self, it: Item, by: str, reopen_after: float | None = None) -> None:
        if it in self.queue:
            self.queue.remove(it)
        it.state = "resolved"
        it.closed_at = self.now
        it.open_hours += self.now - it.open_since
        self.counts["resolved_by_" + by] += 1
        if reopen_after is None and it.draws["reopen"]:
            reopen_after = it.draws["reopen_after"]
        if reopen_after is not None:
            self.schedule(self.now + reopen_after, "reopen", it)


def run(hours: int, seed: int = 16, agent: str | None = None, agent_from: float = math.inf, log_from: float = 0.0,
        every: float = 0.25) -> dict:
    cfg = AGENTS[agent] if agent else None
    return DES(hours, seed=seed, agent=cfg, agent_from=agent_from, log_from=log_from, every=every).run()
