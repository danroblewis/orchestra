"""The fleet's design: namespaces, services, the call graph, topics, and scheduled changes.

Everything here is decided up front from the seed; `simulate.py` then runs it.
Times are step indices (0..n-1) into the shared sample grid.
"""

import math
import random
from dataclasses import dataclass, field

TEAMS = [
    "payments",
    "checkout",
    "catalog",
    "search",
    "identity",
    "notifications",
    "ledger",
    "shipping",
    "inventory",
    "pricing",
    "reviews",
    "recommendations",
    "media",
    "messaging",
    "billing",
    "fraud",
    "analytics",
    "ads",
    "support",
    "geo",
]
NOUNS = [
    "account",
    "order",
    "cart",
    "price",
    "quote",
    "session",
    "token",
    "profile",
    "invoice",
    "refund",
    "stock",
    "media",
    "thumbnail",
    "index",
    "query",
    "rank",
    "feature",
    "event",
    "audit",
    "notify",
    "email",
    "sms",
    "push",
    "address",
    "route",
    "rate",
    "tax",
    "coupon",
    "wallet",
    "balance",
    "risk",
    "score",
    "report",
    "export",
    "sync",
    "cache",
    "config",
    "flag",
    "catalog",
    "review",
    "payment",
    "ledger",
    "shipment",
    "label",
    "carrier",
    "user",
    "consent",
    "device",
    "content",
    "upload",
    "image",
    "video",
    "chat",
    "inbox",
]
SUFFIXES = ["service", "api", "worker", "store", "reader", "writer", "manager", "resolver"]
EDGE_NAMES = ["gateway", "frontend", "bff", "public-api", "web", "mobile-api"]
TOPIC_VERBS = ["created", "updated", "completed", "failed", "requested", "changed", "indexed"]


@dataclass
class Service:
    name: str
    namespace: str
    tier: int
    edge: bool
    per_replica_rps: float
    latency: float  # seconds per request when not queued
    cpu_per_req: float  # cpu-seconds per request
    mem_base: float  # bytes per pod
    mem_per_inflight: float  # bytes per active request
    mem_limit: float  # bytes per pod
    base_rps: float = 0.0  # external traffic at the daily peak (edges only)
    peak_hour: float = 0.0
    replicas: int = 2
    under_provisioned: bool = False
    leak_rate: float = 0.0  # bytes/s leaked across the deployment
    database: str | None = None
    db_queries_per_req: float = 0.0
    db_latency: float = 0.0
    cpu_per_msg: float = 0.0005
    # (step, replicas) and (step, per_replica_rps) change points, step 0 first
    replica_plan: list = field(default_factory=list)
    capacity_plan: list = field(default_factory=list)
    deploys: list = field(default_factory=list)  # steps


@dataclass
class Edge:
    caller: int
    callee: int
    fanout: float
    plan: list = field(default_factory=list)  # (step, fanout) change points, step 0 first


@dataclass
class Consumer:
    group: str
    service: int
    capacity: float = 0.0  # messages/s, set by the simulation from real production
    latency: float = 0.0  # seconds of production it trails by when keeping up
    hidden: bool = False


@dataclass
class Topic:
    name: str
    producers: list  # (service index, events per served request)
    consumers: list  # Consumer


@dataclass
class Fleet:
    start: int
    step: int
    n: int
    services: list  # in call order: every caller comes before its callees
    edges: list
    topics: list
    events: list  # change events as dicts with "step"
    traffic_spikes: list  # (namespace, step0, step1, factor)
    outage: dict | None = None  # {"topic", "group", "step0", "step1"}

    def ts(self, j: int) -> int:
        return self.start + j * self.step


def _lognormal(rng, median, sigma):
    return median * math.exp(rng.gauss(0, sigma))


def _poisson(rng, lam):
    k, p, limit = 0, 1.0, math.exp(-lam)
    while True:
        p *= rng.random()
        if p <= limit:
            return k
        k += 1


def _names(rng, count, ns, taken):
    edges = rng.sample(EDGE_NAMES, k=min(len(EDGE_NAMES), max(1, count)))
    out = []
    for i in range(count):
        if i < len(edges) and i < max(1, min(4, round(count * 0.15))):
            base = f"{ns}-{edges[i]}"
        else:
            base = f"{rng.choice(NOUNS)}-{rng.choice(SUFFIXES)}"
            if base in taken:
                base = f"{ns}-{base}"
        while base in taken:
            base = f"{base}-{rng.randint(2, 9)}"
        taken.add(base)
        out.append(base)
    return out


def _working_steps(start, step, n):
    """Steps on weekdays between 14:00 and 22:00 UTC: when people deploy."""
    out = []
    for j in range(1, n):
        t = start + j * step
        hour = (t % 86400) / 3600
        weekday = (t // 86400 + 3) % 7  # 0 = Monday
        if weekday < 5 and 14 <= hour < 22:
            out.append(j)
    return out or list(range(1, n))


def design(services: int, start: int, step: int, n: int, seed: int) -> Fleet:
    rng = random.Random(seed)
    days = n * step / 86400
    n_ns = max(2, min(len(TEAMS), services // 20))
    namespaces = TEAMS[:n_ns]

    # Split services across namespaces unevenly (teams differ in size), at least 3 each.
    weights = [rng.uniform(0.5, 1.6) for _ in namespaces]
    sizes = [max(3, int(services * w / sum(weights))) for w in weights]
    while sum(sizes) > services:
        sizes[sizes.index(max(sizes))] -= 1
    while sum(sizes) < services:
        sizes[rng.randrange(n_ns)] += 1

    taken: set[str] = set()
    svcs: list[Service] = []
    for ns, size in zip(namespaces, sizes):
        n_edge = max(1, min(4, round(size * 0.15)))
        for i, name in enumerate(_names(rng, size, ns, taken)):
            edge = i < n_edge
            tier = 0 if edge else rng.choices([1, 2, 3, 4], weights=[4, 4, 3, 2])[0]
            mem_base = _lognormal(rng, 300e6, 0.5)
            s = Service(
                name=name,
                namespace=ns,
                tier=tier,
                edge=edge,
                per_replica_rps=_lognormal(rng, 60, 0.7),
                latency=_lognormal(rng, 0.03, 0.8),
                cpu_per_req=_lognormal(rng, 0.004, 0.8),
                mem_base=mem_base,
                mem_per_inflight=_lognormal(rng, 2e6, 0.5),
                mem_limit=mem_base * rng.uniform(2.2, 3.0),
            )
            if edge:
                s.base_rps = _lognormal(rng, 120, 0.8)
                s.peak_hour = (15 + rng.uniform(-3, 4) + 0.0) % 24
            svcs.append(s)

    # Call order: by tier, so every edge goes from an earlier service to a later one (a DAG).
    order = sorted(range(len(svcs)), key=lambda i: (svcs[i].tier, rng.random()))
    svcs = [svcs[i] for i in order]
    by_ns: dict[str, list[int]] = {}
    for i, s in enumerate(svcs):
        by_ns.setdefault(s.namespace, []).append(i)

    edges: list[Edge] = []
    pairs = set()

    def link(a, b):
        if (a, b) in pairs or a == b:
            return
        pairs.add((a, b))
        edges.append(Edge(a, b, round(min(4.0, _lognormal(rng, 0.8, 0.7)), 3)))

    for i, s in enumerate(svcs):
        if s.edge:
            continue
        for _ in range(rng.choices([1, 2, 3], weights=[5, 3, 1])[0]):
            if rng.random() < 0.88:
                pool = [k for k in by_ns[s.namespace] if svcs[k].tier < s.tier]
            else:
                pool = [k for k in range(len(svcs)) if svcs[k].tier < s.tier and svcs[k].namespace != s.namespace]
            if pool:
                link(rng.choice(pool), i)
    edges.sort(key=lambda e: (e.caller, e.callee))

    # Size capacity from the demand each service will see at its peak.
    peak = [0.0] * len(svcs)
    for i, s in enumerate(svcs):
        if s.edge:
            peak[i] = s.base_rps * 1.1
    for e in sorted(edges, key=lambda e: e.caller):
        peak[e.callee] += e.fanout * peak[e.caller]
    internal = [i for i, s in enumerate(svcs) if not s.edge]
    under = set(rng.sample(internal, k=max(1, round(len(svcs) * 0.04))))
    for i, s in enumerate(svcs):
        if i in under:
            s.under_provisioned = True
            util = rng.uniform(1.1, 1.3)
        else:
            util = rng.uniform(0.45, 0.8)
        s.replicas = max(2, math.ceil(peak[i] / (s.per_replica_rps * util)))
        if s.replicas > 60:  # keep pods plausible: very busy services get faster pods
            s.per_replica_rps *= s.replicas / 60
            s.replicas = 60

    # Databases: about one service in seven owns one.
    for i in rng.sample(range(len(svcs)), k=max(1, round(len(svcs) * 0.15))):
        s = svcs[i]
        s.database = s.name.replace("-", "_")
        s.db_queries_per_req = round(rng.uniform(0.5, 6.0), 2)
        s.db_latency = _lognormal(rng, 0.004, 0.6)

    # Leaky services: memory creeps up until the pods are OOM-killed, roughly daily.
    for i in rng.sample(internal, k=2 if len(svcs) >= 40 else 1):
        s = svcs[i]
        headroom = s.replicas * (s.mem_limit - s.mem_base) * 0.8
        s.leak_rate = headroom / (rng.uniform(16, 30) * 3600)

    for s in svcs:
        s.replica_plan = [(0, s.replicas)]
        s.capacity_plan = [(0, s.per_replica_rps)]
    for e in edges:
        e.plan = [(0, e.fanout)]

    # Change events: deploys in working hours, some change speed or fan-out; replica scaling.
    events = []
    work = _working_steps(start, step, n)
    for i, s in enumerate(svcs):
        for j in sorted(rng.sample(work, k=min(len(work), _poisson(rng, days / 8)))):
            ev = {"step": j, "kind": "deploy", "service": s.name, "namespace": s.namespace}
            s.deploys.append(j)
            r = rng.random()
            if r < 0.2:
                new = round(s.capacity_plan[-1][1] * rng.uniform(0.75, 1.25), 3)
                ev["per_replica_rps"] = [round(s.capacity_plan[-1][1], 3), new]
                s.capacity_plan.append((j, new))
            elif r < 0.3:
                out = [e for e in edges if e.caller == i]
                if out:
                    e = rng.choice(out)
                    new = round(e.plan[-1][1] * rng.uniform(0.5, 1.6), 3)
                    ev["fanout"] = {"callee": svcs[e.callee].name, "from": e.plan[-1][1], "to": new}
                    e.plan.append((j, new))
            events.append(ev)
    scalers = rng.sample(range(len(svcs)), k=max(2, round(len(svcs) * 0.2)))
    for i in scalers:
        s = svcs[i]
        j = rng.randrange(n // 10, n)
        old = s.replica_plan[-1][1]
        if s.under_provisioned:
            new = math.ceil(old * rng.uniform(1.3, 1.6))  # someone notices and fixes it
        else:
            new = max(1, old + rng.choice([-2, -1, 1, 1, 2, 3]))
        if new != old:
            s.replica_plan.append((j, new))
            events.append(
                {"step": j, "kind": "scale", "service": s.name, "namespace": s.namespace, "replicas": [old, new]}
            )
    events.sort(key=lambda ev: ev["step"])

    # Marketing pushes: a namespace's edge traffic doubles for a couple of hours.
    spikes = []
    for _ in range(max(1, round(days / 10))):
        ns = rng.choice(namespaces)
        j0 = rng.randrange(n // 5, n - n // 10)
        spikes.append((ns, j0, j0 + int(rng.uniform(1.5, 3) * 3600 / step), round(rng.uniform(1.6, 2.4), 2)))

    topics = _topics(rng, svcs, services)
    return Fleet(start, step, n, svcs, edges, topics, events, spikes)


def _topics(rng, svcs, services):
    count = max(3, round(60 * services / 400))
    names = set()
    topics = []
    for _ in range(count):
        p = rng.randrange(len(svcs))
        own = svcs[p].name.removeprefix(f"{svcs[p].namespace}-").split("-")[0]
        noun = rng.choice(NOUNS) if svcs[p].edge else own
        name = f"{svcs[p].namespace}.{noun}-{rng.choice(TOPIC_VERBS)}"
        while name in names:
            name = f"{name}-v{rng.randint(2, 4)}"
        names.add(name)
        producers = [(p, round(rng.uniform(0.05, 1.5), 3))]
        if rng.random() < 0.2:
            q = rng.randrange(len(svcs))
            if q != p:
                producers.append((q, round(rng.uniform(0.05, 1.0), 3)))
        others = [k for k in range(len(svcs)) if k not in {pp for pp, _ in producers}]
        consumers = [Consumer(svcs[c].name, c) for c in rng.sample(others, k=rng.choices([1, 2, 3], [5, 3, 2])[0])]
        topics.append(Topic(name, producers, consumers))
    return topics
