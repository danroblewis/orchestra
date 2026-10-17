"""A seeded, per-request simulation of a small web shop: 30 gRPC services, 6 message queues and
6 worker pools, over two hours in 1-second steps.

This is the *real system* behind the measured `shop` model. The model is told only what a
Prometheus dashboard shows at the end of every second: requests in flight per service, messages
waiting per queue (consumer lag) and jobs in progress per worker pool. It is never told who calls
whom, who produces into which queue, or what the workers call; that is the answer key
(sdlab/examples/shop/README.md, truth.json).

How it works (discrete events in continuous seconds, cut into 1-second steps):

  external traffic   non-homogeneous Poisson arrivals at the three edge services (a daily cycle
                     compressed into the two hours, a flash sale, a partner-API burst)
  a service          `capacity` requests served at once, FIFO beyond that (the overflow waits
                     inside the service, so "in flight" = being served + queued). Each request
                     takes a lognormal time (mean `latency`, coefficient of variation `cv`).
                     While serving it, the service calls each callee `fan-out` times on average
                     (floor(f) calls plus one more with probability frac(f)), each call at a
                     uniformly random moment of its own service time. Calls do not hold the
                     caller up: a caller's latency already includes the usual wait for its
                     callees, and a slow callee does not slow its callers (no backpressure).
                     When a request finishes, the service may produce one message into a queue.
  a queue            messages wait FIFO until a worker of its pool is free
  a worker pool      N workers (N changes in eras; one outage at N = 0); a worker takes the
                     oldest message, works on it for a lognormal time, calls services while
                     working (as a service does) and may produce into another queue when done.
                     A worker told to stop (scale-down, outage) finishes the job it has first.

The whole graph (calls, produce, consume, worker calls) is acyclic, so `run()` simulates one
node at a time in topological order: every arrival into a node is known before it runs.

`run(seed, steps)` runs any number of seconds. The two hours are a compressed day, and the day
recurs: every 7200 seconds a new day starts with every pool back at its starting size, and the
analytics scale-up, the flash sale (with fulfillment scaled up before it), the partner burst, the
email-workers outage and the search-indexer scale-down come round again, each moved by a few
minutes (drawn from a generator of their own). A long run is simulated a day at a time (each day
in topological order; what is still in flight or waiting carries over), and each later day draws
from its own seeded generator, so the first day is always exactly the original two hours. The
graph and every parameter stay the same at any length.

    python sim.py [seed]          prints a summary of one run
"""

from __future__ import annotations

import bisect
import heapq
import json
import math
import random
import sys
from dataclasses import dataclass, field

STEPS = 7200                          # one step is one second: two hours
SEED = 20261016
PERIOD = STEPS                        # a day, compressed into two hours: the schedule recurs
LONG_STEPS = 6 * STEPS                # six days (12 hours, 43,200 steps): the long run for the discovery test bed

# id: (name, mean latency s, cv, capacity = requests served at once)
SERVICES = {
    "web_frontend": ("web-frontend", 0.30, 0.5, 36),
    "mobile_api": ("mobile-api", 0.25, 0.5, 20),
    "api_gateway": ("api-gateway", 0.08, 0.4, 17),
    "auth": ("auth", 0.06, 0.5, 10),
    "session": ("session", 0.03, 0.4, 9),
    "feature_flags": ("feature-flags", 0.02, 0.3, 4),
    "user_profile": ("user-profile", 0.12, 0.5, 16),
    "catalog": ("catalog", 0.15, 0.5, 32),
    "search": ("search", 0.35, 0.6, 23),
    "pricing": ("pricing", 0.08, 0.4, 25),
    "currency": ("currency", 0.03, 0.3, 5),
    "inventory": ("inventory", 0.10, 0.5, 18),
    "recommendations": ("recommendations", 0.45, 0.6, 21),
    "reviews": ("reviews", 0.20, 0.5, 13),
    "image_service": ("image-service", 0.25, 0.7, 66),
    "cart": ("cart", 0.20, 0.5, 13),
    "checkout": ("checkout", 2.00, 0.4, 18),
    "payment": ("payment", 1.50, 0.5, 9),
    "fraud_check": ("fraud-check", 1.00, 0.6, 9),
    "tax": ("tax", 0.80, 0.4, 8),
    "shipping_quote": ("shipping-quote", 0.80, 0.5, 12),
    "address_validation": ("address-validation", 0.60, 0.5, 10),
    "promotions": ("promotions", 0.06, 0.4, 8),
    "order_service": ("order-service", 1.50, 0.5, 13),
    "loyalty": ("loyalty", 0.60, 0.5, 9),
    "notification": ("notification", 1.00, 0.5, 5),
    "email_gateway": ("email-gateway", 0.60, 0.5, 10),
    "sms_gateway": ("sms-gateway", 2.00, 0.5, 5),
    "analytics_ingest": ("analytics-ingest", 0.05, 0.4, 8),
    "merchant_api": ("merchant-api", 1.50, 0.5, 5),
}
EDGE = ["web_frontend", "mobile_api", "api_gateway"]

# external requests per second at the edge, at the day's average (see external_rate)
EXTERNAL = {"web_frontend": 30.0, "mobile_api": 20.0, "api_gateway": 4.0}

# (caller, callee, fan-out: calls per request the caller serves)
CALLS = [
    ("web_frontend", "api_gateway", 1.0),
    ("web_frontend", "session", 1.0),
    ("web_frontend", "feature_flags", 0.5),
    ("web_frontend", "image_service", 2.0),
    ("web_frontend", "analytics_ingest", 1.0),
    ("mobile_api", "api_gateway", 1.0),
    ("mobile_api", "session", 1.0),
    ("mobile_api", "feature_flags", 1.0),
    ("mobile_api", "analytics_ingest", 0.5),
    ("api_gateway", "auth", 0.8),
    ("api_gateway", "catalog", 0.6),
    ("api_gateway", "search", 0.3),
    ("api_gateway", "recommendations", 0.3),
    ("api_gateway", "cart", 0.25),
    ("api_gateway", "user_profile", 0.2),
    ("api_gateway", "checkout", 0.04),
    ("api_gateway", "merchant_api", 0.012),
    ("auth", "session", 0.5),
    ("auth", "user_profile", 0.3),
    ("search", "catalog", 0.5),
    ("search", "pricing", 0.5),
    ("recommendations", "catalog", 0.8),
    ("recommendations", "user_profile", 0.5),
    ("merchant_api", "catalog", 1.0),
    ("catalog", "pricing", 1.0),
    ("catalog", "inventory", 0.5),
    ("catalog", "image_service", 0.5),
    ("catalog", "reviews", 0.3),
    ("reviews", "user_profile", 0.2),
    ("cart", "pricing", 1.0),
    ("cart", "inventory", 1.0),
    ("cart", "promotions", 0.5),
    ("checkout", "cart", 1.0),
    ("checkout", "payment", 1.0),
    ("checkout", "tax", 1.0),
    ("checkout", "shipping_quote", 1.0),
    ("checkout", "address_validation", 0.8),
    ("checkout", "promotions", 1.0),
    ("checkout", "order_service", 0.9),
    ("payment", "fraud_check", 1.0),
    ("payment", "currency", 0.5),
    ("pricing", "currency", 0.4),
    ("pricing", "promotions", 0.3),
    ("shipping_quote", "address_validation", 0.5),
    ("order_service", "inventory", 1.0),
    ("order_service", "notification", 0.5),
    ("order_service", "loyalty", 0.5),
    ("notification", "sms_gateway", 0.5),
]

# id: name
QUEUES = {
    "order_placed": "order-placed",
    "payment_captured": "payment-captured",
    "email_requested": "email-requested",
    "product_changed": "product-changed",
    "profile_updated": "profile-updated",
    "clickstream": "clickstream",
}

# (producer: a service or a worker pool, queue, probability of one message per request/job finished)
PRODUCES = [
    ("checkout", "order_placed", 0.85),
    ("payment", "payment_captured", 0.8),
    ("order_service", "email_requested", 1.0),
    ("merchant_api", "product_changed", 0.9),
    ("user_profile", "profile_updated", 0.015),
    ("analytics_ingest", "clickstream", 0.08),
    ("fulfillment_workers", "email_requested", 1.0),
    ("loyalty_workers", "email_requested", 0.2),
    ("profile_sync_workers", "email_requested", 0.3),
]

# id: (name, queue it consumes, mean job s, cv, [(service, fan-out per job)])
POOLS = {
    "fulfillment_workers": ("fulfillment-workers", "order_placed", 4.0, 0.4, [("inventory", 1.0), ("shipping_quote", 1.0)]),
    "loyalty_workers": ("loyalty-workers", "payment_captured", 1.0, 0.5, [("loyalty", 1.0)]),
    "email_workers": ("email-workers", "email_requested", 1.0, 0.5, [("email_gateway", 1.0)]),
    "search_indexer": ("search-indexer", "product_changed", 3.0, 0.5, [("catalog", 1.0), ("image_service", 1.0), ("search", 1.0)]),
    "profile_sync_workers": ("profile-sync-workers", "profile_updated", 2.0, 0.5, [("loyalty", 1.0)]),
    "analytics_workers": ("analytics-workers", "clickstream", 1.0, 0.4, []),
}

# eras: (first second, {pool: workers from then on}, label). The first entry sets every pool.
SCALING = [
    (0, {"fulfillment_workers": 10, "loyalty_workers": 3, "email_workers": 12, "search_indexer": 3,
         "profile_sync_workers": 2, "analytics_workers": 6}, "Start"),
    (1200, {"analytics_workers": 9}, "analytics-workers scaled up to 9"),
    (2400, {"fulfillment_workers": 16}, "fulfillment-workers scaled up to 16 for the flash sale"),
    (4800, {"email_workers": 0}, "email-workers outage (0 workers)"),
    (5700, {"email_workers": 12}, "email-workers restored (12 workers)"),
    (6000, {"search_indexer": 1}, "search-indexer scaled down to 1"),
]
OUTAGE = {"pool": "email_workers", "from": 4800, "to": 5700}

FLASH_SALE = (3600, 4200, 2.0)        # web and mobile traffic x2 (ramping up over a minute)
PARTNER_BURST = (5000, 5100, 5.0)     # partner traffic at the api-gateway x5

MEASURED_STOCKS = [*SERVICES, *QUEUES, *POOLS]
NEW_DAY = "A new day: every pool back to its starting size"


def schedule(seed: int, k: int) -> dict:
    """Day k's events in absolute seconds: the scaling eras [(second, {pool: workers}, label)], the
    flash sale, the partner burst and the outage. Day 0 is the original schedule; later days
    start with every pool back at its starting size and move each event by a few minutes."""
    if k == 0:
        return {"scaling": list(SCALING), "flash": FLASH_SALE, "burst": PARTNER_BURST, "outage": dict(OUTAGE)}
    r, off = random.Random(seed * 1_000_003 + k), k * PERIOD
    analytics = 1200 + r.randint(-300, 300)
    flash = 3600 + r.randint(-600, 600)
    down = 4800 + r.randint(-300, 300)
    up = down + 900 + r.randint(-300, 300)
    indexer = up + 300 + r.randint(0, 300)
    burst = r.randint(4000, 6400)
    _, *rest = SCALING
    at = [analytics, flash - 1200, down, up, indexer]
    return {"scaling": [(off, SCALING[0][1], NEW_DAY)] + [(off + t, sizes, label) for t, (_, sizes, label) in zip(at, rest)],
            "flash": (off + flash, off + flash + FLASH_SALE[1] - FLASH_SALE[0], FLASH_SALE[2]),
            "burst": (off + burst, off + burst + PARTNER_BURST[1] - PARTNER_BURST[0], PARTNER_BURST[2]),
            "outage": {"pool": OUTAGE["pool"], "from": off + down, "to": off + up}}


def counter_ids() -> list[str]:
    """Every per-step counter the recording has (none of them is in the model)."""
    out = [f"external__{e}" for e in EDGE]
    out += [f"handled__{s}" for s in SERVICES]
    out += [f"calls__{a}__{b}" for a, b, _ in CALLS]
    out += [f"calls__{p}__{s}" for p, (_, _, _, _, calls) in POOLS.items() for s, _ in calls]
    out += [f"produced__{p}__{q}" for p, q, _ in PRODUCES]
    out += [f"produced__{q}" for q in QUEUES] + [f"consumed__{q}" for q in QUEUES]
    out += [f"done__{p}" for p in POOLS]
    return out


COUNTERS = counter_ids()


def external_rate(edge: str, t: float, sched: dict | None = None) -> float:
    """External requests per second arriving at an edge service at second t, under the schedule
    of t's day (the original two hours by default)."""
    sched = sched or schedule(SEED, 0)
    day = 1 - 0.5 * math.cos(2 * math.pi * t / STEPS) + 0.08 * math.sin(6 * math.pi * t / STEPS)   # quiet, busy, quiet
    r = EXTERNAL[edge] * day
    a, b, x = sched["flash"]
    if edge in ("web_frontend", "mobile_api") and a <= t < b:
        r *= 1 + (x - 1) * min(1.0, (t - a) / 60, (b - t) / 60)
    a, b, x = sched["burst"]
    if edge == "api_gateway" and a <= t < b:
        r *= x
    return r


def pool_size(pool: str, t: float, scaling: list | None = None) -> int:
    n = 0
    for t0, sizes, _ in scaling or SCALING:
        if t >= t0 and pool in sizes:
            n = sizes[pool]
    return n


def topo_order() -> list[str]:
    """Services, queues and pools in an order where every node comes after all that feed it."""
    feeds: dict[str, list[str]] = {n: [] for n in MEASURED_STOCKS}
    for a, b, _ in CALLS:
        feeds[a].append(b)
    for p, q, _ in PRODUCES:
        feeds[p].append(q)
    for p, (_, q, _, _, calls) in POOLS.items():
        feeds[q].append(p)
        feeds[p] += [s for s, _ in calls]
    indeg = {n: 0 for n in feeds}
    for n in feeds:
        for m in feeds[n]:
            indeg[m] += 1
    ready = [n for n in MEASURED_STOCKS if indeg[n] == 0]
    order = []
    while ready:
        n = ready.pop(0)
        order.append(n)
        for m in feeds[n]:
            indeg[m] -= 1
            if indeg[m] == 0:
                ready.append(m)
    assert len(order) == len(feeds), "the graph has a cycle"
    return order


def depths() -> dict[str, int]:
    """Longest path from the edge, counting a queue and its pool as further steps."""
    d = {n: 0 for n in MEASURED_STOCKS}
    for n in topo_order():
        for a, b, _ in CALLS:
            if a == n:
                d[b] = max(d[b], d[n] + 1)
        for p, q, _ in PRODUCES:
            if p == n:
                d[q] = max(d[q], d[n] + 1)
        for p, (_, q, _, _, calls) in POOLS.items():
            if q == n:
                d[p] = max(d[p], d[n] + 1)
            if p == n:
                for s, _ in calls:
                    d[s] = max(d[s], d[n] + 1)
    return d


def lognormal_params(mean: float, cv: float) -> tuple[float, float]:
    s2 = math.log(1 + cv * cv)
    return math.log(mean) - s2 / 2, math.sqrt(s2)


@dataclass
class Result:
    seed: int
    levels: dict[str, list[int]] = field(default_factory=dict)     # stock -> level at the end of each step 1..STEPS
    counters: dict[str, list[int]] = field(default_factory=dict)   # counter -> count in each step
    eras: list[dict] = field(default_factory=list)                 # [{t, label}] t = first step of the era
    service_time: dict[str, float] = field(default_factory=dict)   # realised mean time in system (queueing included), s
    job_time: dict[str, float] = field(default_factory=dict)       # realised mean job time per pool, s
    queue_wait: dict[str, float] = field(default_factory=dict)     # realised mean wait in each queue, s
    requests: int = 0
    messages: int = 0
    scaling: list[tuple] = field(default_factory=list)              # every scaling era (second, {pool: workers}, label)
    days: list[dict] = field(default_factory=list)                  # each day's flash sale, partner burst and outage


def run(seed: int = SEED, steps: int = STEPS) -> Result:
    assert steps >= 1
    H = float(steps)
    res = Result(seed=seed, counters={c: [0] * steps for c in COUNTERS})
    C = res.counters
    days = [schedule(seed, k) for k in range(-(-steps // PERIOD))]
    scaling = [x for d in days for x in d["scaling"]]
    # day 0 draws from the simulation's generator, as it always has; each later day from its own
    rngs = [random.Random(seed)] + [random.Random(seed * 1_000_003 + 500_000 + k) for k in range(1, len(days) + 1)]
    arrivals: dict[str, list[float]] = {n: [] for n in MEASURED_STOCKS}   # arrival times into every node, not yet simulated
    calls_out: dict[str, list[tuple[str, float, list[int], list[float]]]] = {n: [] for n in MEASURED_STOCKS}
    for a, b, f in CALLS:
        calls_out[a].append((b, f, C[f"calls__{a}__{b}"], arrivals[b]))
    for p, (_, _, _, _, calls) in POOLS.items():
        for s, f in calls:
            calls_out[p].append((s, f, C[f"calls__{p}__{s}"], arrivals[s]))
    produces: dict[str, list[tuple[float, list[int], list[int], list[float]]]] = {n: [] for n in MEASURED_STOCKS}
    for p, q, prob in PRODUCES:
        produces[p].append((prob, C[f"produced__{p}__{q}"], C[f"produced__{q}"], arrivals[q]))

    def spawn(node: str, start: float, dur: float, rand) -> None:
        """The calls a request or job makes while it is being served, at random moments of it."""
        for _, f, cnt, out in calls_out[node]:
            n = int(f) + (rand() < f - int(f))
            for _ in range(n):
                t = start + rand() * dur
                if t < H:
                    out.append(t)
                    cnt[int(t)] += 1

    def produce(node: str, end: float, rand, later) -> None:
        """A finished request or job may publish a message; one finishing after the day draws
        from the next day's generator."""
        if end >= H:
            return
        for prob, cnt_edge, cnt_q, out in produces[node]:
            if prob >= 1 or (rand() if end < day_end else later()) < prob:
                out.append(end)
                k = int(end)
                cnt_edge[k] += 1
                cnt_q[k] += 1

    def level(inc: list[int], dec: list[int]) -> list[int]:
        lv, x = [], 0
        for a, b in zip(inc, dec):
            x += a - b
            lv.append(x)
        return lv

    order = topo_order()
    inc = {n: [0] * steps for n in SERVICES}                          # requests arriving per step
    slots = {n: [0.0] * SERVICES[n][3] for n in SERVICES}            # when each service slot is next free
    workers = {}                                                     # when each worker is next free
    sums = {n: [0, 0.0, 0.0] for n in MEASURED_STOCKS}               # requests (jobs), time in system (job), wait
    segs = {}
    for node in POOLS:
        sg = [(t0, sizes[node]) for t0, sizes, _ in scaling if node in sizes]
        segs[node] = [(t0, sg[i + 1][0] if i + 1 < len(sg) else math.inf, n) for i, (t0, n) in enumerate(sg)]
        workers[node] = [0.0] * max(n for _, _, n in segs[node])

    for k, day in enumerate(days):
        rng, day_end = rngs[k], min(H, float((k + 1) * PERIOD))
        rand, lognorm, later = rng.random, rng.lognormvariate, rngs[k + 1].random

        # external traffic: thinning of each edge's non-homogeneous Poisson process
        for e in EDGE:
            lam_max = EXTERNAL[e] * 1.6 * max(FLASH_SALE[2], PARTNER_BURST[2])
            cnt, out, t = C[f"external__{e}"], arrivals[e], float(k * PERIOD)
            while True:
                t += rng.expovariate(lam_max)
                if t >= day_end:
                    break
                if rand() < external_rate(e, t, day) / lam_max:
                    out.append(t)
                    cnt[int(t)] += 1

        for node in order:
            if node in SERVICES:
                _, mean, cv, cap = SERVICES[node]
                mu, sg = lognormal_params(mean, cv)
                pending = arrivals[node]
                pending.sort()
                cut = bisect.bisect_left(pending, day_end)
                arr = pending[:cut]
                del pending[:cut]                              # later arrivals wait for their day
                ninc, done, free, tot = inc[node], C[f"handled__{node}"], slots[node], sums[node]
                total = 0.0
                for a in arr:
                    ninc[int(a)] += 1
                    f = heapq.heappop(free)
                    s = a if a > f else f
                    d = lognorm(mu, sg)
                    e = s + d
                    heapq.heappush(free, e)
                    total += e - a
                    if e < H:
                        done[int(e)] += 1
                    spawn(node, s, d, rand)
                    produce(node, e, rand, later)
                tot[0] += len(arr)
                tot[1] += total
            elif node in QUEUES:
                pass                                       # its consumer pool does the work (the pool follows it in the order)
            else:
                _, q, mean, cv, _ = POOLS[node]
                mu, sg = lognormal_params(mean, cv)
                msgs, consumed, done = arrivals[q], C[f"consumed__{q}"], C[f"done__{node}"]
                msgs.sort()
                sgs, free, tot = segs[node], workers[node], sums[node]
                nmax = len(free)

                def next_active(j: int, t: float) -> float:
                    for t0, t1, n in sgs:
                        if n > j and t1 > t:
                            return t if t > t0 else t0
                    return math.inf

                started, total_job, total_wait = 0, 0.0, 0.0
                for a in msgs:
                    best, bj = math.inf, -1
                    for j in range(nmax):
                        s = next_active(j, a if a > free[j] else free[j])
                        if s < best:
                            best, bj = s, j
                    if best >= day_end:
                        break                              # nobody takes it today: it is still waiting
                    d = lognorm(mu, sg)
                    e = best + d
                    free[bj] = e
                    consumed[int(best)] += 1
                    started += 1
                    total_job += d
                    total_wait += best - a
                    if e < H:
                        done[int(e)] += 1
                    spawn(node, best, d, rand)
                    produce(node, e, rand, later)
                del msgs[:started]
                tot[0] += started
                tot[1] += total_job
                tot[2] += total_wait

    for node in order:
        n, total, wait = sums[node]
        if node in SERVICES:
            res.levels[node] = level(inc[node], C[f"handled__{node}"])
            res.service_time[node] = round(total / max(1, n), 4)
            res.requests += n
        elif node in POOLS:
            q = POOLS[node][1]
            res.levels[q] = level(C[f"produced__{q}"], C[f"consumed__{q}"])
            res.levels[node] = level(C[f"consumed__{q}"], C[f"done__{node}"])
            res.job_time[node] = round(total / max(1, n), 4)
            res.queue_wait[q] = round(wait / max(1, n), 4)
            res.messages += sum(C[f"produced__{q}"])

    res.levels = {s: res.levels[s] for s in MEASURED_STOCKS}
    res.scaling = [x for x in scaling if x[0] < H]
    res.days = [{"flash_sale": d["flash"], "partner_burst": d["burst"], "outage": d["outage"]} for d in days]
    res.eras = [{"t": t0 + 1, "label": label} for t0, _, label in res.scaling]
    return res


def measured(seed: int = SEED, steps: int = STEPS) -> dict:
    """What SD Lab sees of a run: the dashboard's levels every second, and the eras."""
    res = cached(seed) if steps == STEPS else run(seed, steps)
    return {"t": list(range(1, steps + 1)), "levels": {s: list(v) for s, v in res.levels.items()},
            "eras": [{"start": e["t"], "label": e["label"]} for e in res.eras],
            "counters": {k: list(v) for k, v in res.counters.items()}}


def driven_inflows(res: Result) -> list[dict]:
    """Every information link a perfect discovery would report: arrivals into a stock from
    outside at k x the level of the stock that drives them (k realised from the run as total
    arrivals / Σ the driver's level over the steps before)."""
    def k_real(counter: str, driver: str) -> float:
        lv = res.levels[driver]
        return round(sum(res.counters[counter][1:]) / max(1, sum(lv[:-1])), 4)

    out = []
    for a, b, f in CALLS:
        w = SERVICES[a][1]
        out.append({"kind": "call", "driver": a, "into": b, "fan_out": f, "driver_mean_latency_s": w,
                    "k_nominal": round(f / w, 4), "k_realised": k_real(f"calls__{a}__{b}", a), "counter": f"calls__{a}__{b}"})
    for p, (_, _, mean, _, calls) in POOLS.items():
        for s, f in calls:
            out.append({"kind": "worker call", "driver": p, "into": s, "fan_out": f, "driver_mean_job_s": mean,
                        "k_nominal": round(f / mean, 4), "k_realised": k_real(f"calls__{p}__{s}", p), "counter": f"calls__{p}__{s}"})
    for p, q, prob in PRODUCES:
        w = SERVICES[p][1] if p in SERVICES else POOLS[p][2]
        out.append({"kind": "produce", "driver": p, "into": q, "probability": prob, "driver_mean_time_s": w,
                    "k_nominal": round(prob / w, 4), "k_realised": k_real(f"produced__{p}__{q}", p), "counter": f"produced__{p}__{q}"})
    return out


def ground_truth(res: Result) -> dict:
    """Everything the model is not told, in one JSON-able dict (summaries; per-step series are in
    the recording and the test fixture)."""
    mean = lambda xs: round(sum(xs) / len(xs), 3)   # noqa: E731
    lv = res.levels
    steps = len(lv[MEASURED_STOCKS[0]])
    d = depths()
    links = driven_inflows(res)
    flows = []                                       # the real stock-to-stock and stock-to-outside flows
    for s, (_, w, _, _) in SERVICES.items():
        flows.append({"from": s, "to": None, "what": "requests finish", "form": "proportional",
                      "k_nominal": round(1 / w, 4), "k_realised": round(sum(res.counters[f"handled__{s}"][1:]) / max(1, sum(lv[s][:-1])), 4),
                      "counter": f"handled__{s}"})
    for p, (_, q, m, _, _) in POOLS.items():
        flows.append({"from": q, "to": p, "what": "a worker takes a message: it becomes a job",
                      "form": "capacity-limited: min(free workers, messages waiting) per job time; at most workers / mean job time per second",
                      "counter": f"consumed__{q}"})
        flows.append({"from": p, "to": None, "what": "jobs finish", "form": "proportional",
                      "k_nominal": round(1 / m, 4), "k_realised": round(sum(res.counters[f"done__{p}"][1:]) / max(1, sum(lv[p][:-1])), 4),
                      "counter": f"done__{p}"})
    inflow_equations = {}
    for n in MEASURED_STOCKS:
        if n in POOLS:
            continue
        terms = [{"driver": x["driver"], "k_nominal": x["k_nominal"], "k_realised": x["k_realised"], "kind": x["kind"]} for x in links if x["into"] == n]
        inflow_equations[n] = {"external_mean_per_s": round(sum(res.counters[f"external__{n}"]) / steps, 3) if n in EDGE else 0, "terms": terms}
    return {
        "seed": res.seed,
        "steps": steps,
        "step": "1 second",
        "requests": res.requests,
        "messages": res.messages,
        "sizes": {"services": len(SERVICES), "queues": len(QUEUES), "pools": len(POOLS), "calls": len(CALLS),
                  "worker_calls": sum(len(v[4]) for v in POOLS.values()), "produces": len(PRODUCES)},
        "services": {s: {"name": n, "latency_mean_s": w, "latency_cv": cv, "capacity": c, "depth": d[s],
                         "external_per_s_average": EXTERNAL.get(s, 0), "realised_mean_time_in_system_s": res.service_time[s]}
                     for s, (n, w, cv, c) in SERVICES.items()},
        "queues": {q: {"name": n, "depth": d[q], "consumer": next(p for p, v in POOLS.items() if v[1] == q),
                       "producers": [p for p, qq, _ in PRODUCES if qq == q], "realised_mean_wait_s": res.queue_wait[q]}
                   for q, n in QUEUES.items()},
        "pools": {p: {"name": n, "consumes": q, "job_mean_s": m, "job_cv": cv, "depth": d[p],
                      "calls": [{"service": s, "fan_out": f} for s, f in calls],
                      "produces": [{"queue": qq, "probability": pr} for pp, qq, pr in PRODUCES if pp == p],
                      "workers": [{"from_t": t0 + 1, "workers": sz[p]} for t0, sz, _ in SCALING if p in sz],
                      "realised_mean_job_s": res.job_time[p]}
                  for p, (n, q, m, cv, calls) in POOLS.items()},
        "calls": [{"caller": a, "callee": b, "fan_out": f} for a, b, f in CALLS],
        "worker_calls": [{"pool": p, "service": s, "fan_out": f} for p, v in POOLS.items() for s, f in v[4]],
        "produces": [{"producer": p, "queue": q, "probability": pr} for p, q, pr in PRODUCES],
        "consumes": [{"queue": v[1], "pool": p} for p, v in POOLS.items()],
        "traffic": {"edge": EDGE, "external_per_s_average": EXTERNAL,
                    "daily_cycle": "x(1 - 0.5 cos(2 pi t / 7200) + 0.08 sin(6 pi t / 7200)): quiet at the start and end, busiest at t = 3600",
                    "flash_sale": {"from_s": FLASH_SALE[0], "to_s": FLASH_SALE[1], "factor": FLASH_SALE[2], "edges": ["web_frontend", "mobile_api"], "ramp_s": 60},
                    "partner_burst": {"from_s": PARTNER_BURST[0], "to_s": PARTNER_BURST[1], "factor": PARTNER_BURST[2], "edges": ["api_gateway"]}},
        "eras": res.eras,
        "outage": OUTAGE,
        "sd_structure": {
            "note": "In SD Lab terms. 'flows' move things between stocks (or to outside); 'driven_inflows' are information links: "
                    "outside -> `into` at k x level of `driver` per second (nothing leaves the driver). A stock with several drivers "
                    "has one linear inflow: external + sum of k x level of each driver (inflow_equations). k_nominal = fan-out (or "
                    "probability) / the driver's mean latency or job time (Little's law); k_realised = what the run gives, which is "
                    "lower for drivers that queue (their in-flight includes requests waiting for a slot).",
            "flows": flows,
            "driven_inflows": links,
            "inflow_equations": inflow_equations,
        },
        "mean_levels": {s: mean(lv[s]) for s in MEASURED_STOCKS},
        "max_levels": {s: max(lv[s]) for s in MEASURED_STOCKS},
    }


_cache: dict[int, Result] = {}


def cached(seed: int = SEED) -> Result:
    if seed not in _cache:
        _cache[seed] = run(seed)
    return _cache[seed]


if __name__ == "__main__":
    r = run(int(sys.argv[1]) if len(sys.argv) > 1 else SEED)
    print(json.dumps({"requests": r.requests, "messages": r.messages,
                      "mean_levels": {s: round(sum(v) / len(v), 2) for s, v in r.levels.items()},
                      "max_levels": {s: max(v) for s, v in r.levels.items()}}, indent=1))
