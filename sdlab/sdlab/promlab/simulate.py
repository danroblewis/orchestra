"""Run the fleet step by step and write its metrics.

Services are simulated one at a time in call order (callers before callees), each
over the whole time range: a service's arrivals are its external traffic plus
fan-out times what its callers actually served, so overload upstream starves
downstream. Queues, consumer lag and leaked memory are stocks that integrate
their flows. Counters start at a random uptime offset and reset to 0 when the
service restarts (deploys and OOM kills).
"""

import math
import random
from array import array
from itertools import accumulate

from .fleet import Fleet

METRICS = [
    (
        "grpc_server_handled_total",
        "counter",
        "Total number of RPCs completed on the server, regardless of success or failure.",
    ),
    ("grpc_server_inflight_requests", "gauge", "Requests in flight on the server: being handled or queued."),
    ("grpc_client_handled_total", "counter", "Total number of RPCs completed by the client, by callee service."),
    ("container_memory_working_set_bytes", "gauge", "Current working set of the deployment's containers in bytes."),
    (
        "container_cpu_usage_seconds_total",
        "counter",
        "Cumulative cpu time consumed by the deployment's containers in seconds.",
    ),
    ("db_connections_in_use", "gauge", "Database connections currently checked out of the pool."),
    ("db_queries_total", "counter", "Total database queries issued."),
    ("kafka_topic_messages_in_total", "counter", "Messages produced to the topic."),
    ("kafka_consumergroup_lag", "gauge", "Messages produced to the topic and not yet consumed by the group."),
    ("kafka_consumergroup_consumed_total", "counter", "Messages consumed from the topic by the group."),
    ("kube_deployment_spec_replicas", "gauge", "Number of desired pods for a deployment."),
]

BASE_DEADLINE = 0.0005  # fraction of served requests that time out even when healthy


def expand(plan, n):
    """Change points [(step, value), ...] to one value per step."""
    out = []
    for k, (j, v) in enumerate(plan):
        nxt = plan[k + 1][0] if k + 1 < len(plan) else n
        out.extend([v] * (nxt - j))
    return out


def cumulate(incs, resets, initial):
    """Running total of `incs`, starting at `initial`, back to 0 at each reset step."""
    out = array("f")
    bounds = [0] + sorted(j for j in resets if 0 < j < len(incs)) + [len(incs)]
    for k in range(len(bounds) - 1):
        seg = incs[bounds[k] : bounds[k + 1]]
        out.extend(accumulate(seg, initial=initial if k == 0 else 0.0))
        out.pop(len(out) - len(seg) - 1)  # drop the `initial` seed itself
    return out


def _edge_traffic(rng, fleet, s, spikes):
    n, step, start = fleet.n, fleet.step, fleet.start
    tau = 2 * math.pi / 86400
    ph = s.peak_hour * 3600
    out = array("d", bytes(8 * n))
    ar = 0.0
    gauss = rng.gauss
    for j in range(n):
        t = start + j * step
        x = tau * (t % 86400 - ph)
        daily = 0.55 + 0.42 * math.cos(x) + 0.06 * math.cos(2 * x)
        weekly = 0.72 if (t // 86400 + 3) % 7 >= 5 else 1.0
        ar = 0.92 * ar + gauss(0, 0.035)
        out[j] = s.base_rps * daily * weekly * math.exp(ar) * step
    for ns, j0, j1, factor in spikes:
        if ns == s.namespace:
            for j in range(max(0, j0), min(n, j1)):
                out[j] *= factor
    return out


def run(fleet: Fleet, writer, seed: int) -> dict:
    rng = random.Random(seed * 7919 + 1)
    n, dt = fleet.n, fleet.step
    svcs = fleet.services
    for name, kind, help_text in METRICS:
        writer.declare(name, kind, help_text)

    arrivals = [array("d", bytes(8 * n)) for _ in svcs]
    served = [None] * len(svcs)
    cpu_inc = [None] * len(svcs)
    resets = [None] * len(svcs)
    restarts = [[] for _ in svcs]
    out_edges = [[] for _ in svcs]
    for e in fleet.edges:
        out_edges[e.caller].append(e)

    for i, s in enumerate(svcs):
        if s.edge:
            arrivals[i] = _edge_traffic(rng, fleet, s, fleet.traffic_spikes)
        sv_arr, reset_steps = _service(rng, fleet, i, s, arrivals[i], writer, restarts[i])
        arrivals[i] = None
        served[i] = sv_arr
        resets[i] = reset_steps
        uptime = rng.uniform(0.2, 4) * 86400 / dt  # steps since the last restart before the data starts
        mean_sv = sum(sv_arr) / n
        for e in out_edges[i]:
            fan = expand(e.plan, n)
            calls = [f * x for f, x in zip(fan, sv_arr)]
            dst = arrivals[e.callee]
            arrivals[e.callee] = array("d", [a + c for a, c in zip(dst, calls)])
            writer.add(
                "grpc_client_handled_total",
                {"namespace": s.namespace, "service": s.name, "grpc_service": svcs[e.callee].name},
                cumulate(calls, reset_steps, uptime * mean_sv * e.fanout),
            )
        reps = expand(s.replica_plan, n)
        cpu_inc[i] = array("d", [x * s.cpu_per_req + r * 0.015 * dt for x, r in zip(sv_arr, reps)])
        if s.database:
            _database(rng, s, sv_arr, reps, dt, reset_steps, uptime * mean_sv * s.db_queries_per_req, writer)
        writer.add("kube_deployment_spec_replicas", {"namespace": s.namespace, "deployment": s.name}, reps)

    topics = _kafka(rng, fleet, served, cpu_inc, writer)

    for i, s in enumerate(svcs):
        mean_cpu = sum(cpu_inc[i]) / n
        writer.add(
            "container_cpu_usage_seconds_total",
            {"namespace": s.namespace, "service": s.name},
            cumulate(cpu_inc[i], resets[i], rng.uniform(0.2, 4) * 86400 / dt * mean_cpu),
        )
    return {
        "restarts": restarts,
        "mean_rps": [sum(x) / (n * dt) for x in served],
        "topics": topics,
    }


def _service(rng, fleet, i, s, arr, writer, restarts):
    n, dt = fleet.n, fleet.step
    reps = expand(s.replica_plan, n)
    cap = expand(s.capacity_plan, n)
    deploys = set(s.deploys)
    rand, gauss = rng.random, rng.gauss
    sv_arr = array("d", bytes(8 * n))
    ok_inc = array("d", bytes(8 * n))
    de_inc = array("d", bytes(8 * n))
    un_inc = array("d", bytes(8 * n))
    inflight = array("f", bytes(4 * n))
    memory = array("f", bytes(4 * n))
    reset_steps = []
    q = 0.0
    leaked = 0.0
    restart_next = False
    lat0, mem_base, per_inflight, limit = s.latency, s.mem_base, s.mem_per_inflight, s.mem_limit
    leak = s.leak_rate * dt
    for j in range(n):
        r = reps[j]
        mu = r * cap[j] * dt
        if restart_next or j in deploys:
            reset_steps.append(j)
            mu *= 0.7 if restart_next else 0.85  # pods coming back up
            restart_next = False
            leaked = 0.0
        avail = q + arr[j]
        sv = avail if avail < mu else mu
        q = avail - sv
        qmax = mu * 0.4  # about two minutes of work; beyond that, requests are rejected
        if q > qmax:
            un_inc[j] = q - qmax
            q = qmax
        wait = q * dt / mu if mu > 0 else 0.0
        de = sv * (BASE_DEADLINE * (0.5 + rand()) + 0.8 * wait / (wait + 60))
        sv_arr[j] = sv
        ok_inc[j] = sv - de
        de_inc[j] = de
        util = sv / mu if mu > 0 else 0.0
        active = sv / dt * lat0 * (1 + 3 * util**4)
        inflight[j] = active + q
        leaked += leak
        mem = (r * mem_base + per_inflight * active + 2e3 * q + leaked) * (1 + gauss(0, 0.008))
        memory[j] = mem
        if mem > r * limit:
            restarts.append({"step": j, "cause": "OOMKilled"})
            restart_next = True
    for j in s.deploys:
        restarts.append({"step": j, "cause": "deploy"})
    restarts.sort(key=lambda x: x["step"])

    labels = {"namespace": s.namespace, "service": s.name}
    uptime = rng.uniform(0.2, 4) * 86400 / dt
    mean = sum(sv_arr) / n
    for code, inc, share in (
        ("OK", ok_inc, 1.0),
        ("DeadlineExceeded", de_inc, BASE_DEADLINE),
        ("Unavailable", un_inc, 0.0),
    ):
        writer.add(
            "grpc_server_handled_total",
            {**labels, "grpc_code": code},
            cumulate(inc, reset_steps, uptime * mean * share),
        )
    writer.add("grpc_server_inflight_requests", labels, inflight)
    writer.add("container_memory_working_set_bytes", labels, memory)
    return sv_arr, reset_steps


def _database(rng, s, sv_arr, reps, dt, reset_steps, initial, writer):
    labels = {"namespace": s.namespace, "service": s.name, "database": s.database}
    queries = [x * s.db_queries_per_req for x in sv_arr]
    gauss = rng.gauss
    conns = array("f")
    for qn, r in zip(queries, reps):
        pool = r * 10
        busy = qn / dt * s.db_latency
        want = r + busy * (1 + (busy / pool) ** 2) * (1 + gauss(0, 0.05))
        conns.append(min(pool, max(0.0, round(want))))
    writer.add("db_connections_in_use", labels, conns)
    writer.add("db_queries_total", labels, cumulate(queries, reset_steps, initial))


def _kafka(rng, fleet, served, cpu_inc, writer):
    n, dt = fleet.n, fleet.step
    svcs = fleet.services
    prods = []
    for t in fleet.topics:
        prod = [0.0] * n
        for p, ratio in t.producers:
            prod = [a + ratio * x for a, x in zip(prod, served[p])]
        prods.append(prod)

    def peak_rate(prod):
        """98th percentile of hourly production rate (so a one-off spike doesn't count)."""
        w = max(1, 3600 // dt)
        if n <= w:
            return max(prod) / dt
        acc = list(accumulate(prod, initial=0.0))
        hourly = sorted((acc[j + w] - acc[j]) / (w * dt) for j in range(0, n - w + 1, w))
        return hourly[int(len(hourly) * 0.98)]

    stats = [(sum(p) / (n * dt), peak_rate(p)) for p in prods]
    # The outage hits a busy-enough topic's first consumer group.
    ranked = sorted(range(len(fleet.topics)), key=lambda k: stats[k][0])
    out_t = ranked[len(ranked) * 2 // 3]
    out_c = fleet.topics[out_t].consumers[0]
    j0 = int(n * rng.uniform(0.45, 0.6))
    j1 = min(n - 1, j0 + int(rng.uniform(4, 8) * 3600 / dt))
    fleet.outage = {"topic": fleet.topics[out_t].name, "group": out_c.group, "step0": j0, "step1": j1}

    groups = []
    for k, t in enumerate(fleet.topics):
        mean, peak = stats[k]
        for c in t.consumers:
            if c is out_c:  # drains the outage backlog in a few hours
                c.capacity = max(mean * rng.uniform(1.7, 2.0), peak * 1.05)
            elif rng.random() < 0.35:  # falls behind at the daily peak, catches up overnight
                c.capacity = max(1.2 * mean, peak * rng.uniform(0.7, 0.95))
            else:
                c.capacity = max(1.25 * mean, peak * rng.uniform(1.1, 3.0))
            c.latency = rng.lognormvariate(math.log(5), 0.8)  # seconds behind even when keeping up
            groups.append((k, c))
    want = max(1, round(5 * len(fleet.topics) / 60))
    candidates = [(k, c) for k, c in groups if c is not out_c]
    busy = [g for g in candidates if g[1].capacity < stats[g[0]][1]]  # lag moves daily: worth discovering
    rng.shuffle(busy)
    rest = [g for g in candidates if g not in busy]
    rng.shuffle(rest)
    for _, c in (busy + rest)[:want]:
        c.hidden = True

    gauss = rng.gauss
    out = []
    for k, t in enumerate(fleet.topics):
        prod = prods[k]
        writer.add(
            "kafka_topic_messages_in_total",
            {"topic": t.name},
            cumulate(prod, [], rng.uniform(5, 60) * 86400 * stats[k][0]),
        )
        for c in t.consumers:
            lag = array("f", bytes(4 * n))
            took = [0.0] * n
            level = 0.0
            per_step = c.capacity * dt
            behind = c.latency / dt
            down = (j0, j1) if c is out_c else (n, n)
            for j in range(n):
                level += prod[j]
                if down[0] <= j < down[1]:
                    got = 0.0
                else:
                    got = per_step * (1 + gauss(0, 0.05))
                    floor = prod[j] * behind * (1 + gauss(0, 0.3))
                    if got > level - floor:
                        got = max(0.0, level - floor)
                level -= got
                took[j] = got
                lag[j] = level
            writer.add("kafka_consumergroup_lag", {"topic": t.name, "consumergroup": c.group}, lag)
            if not c.hidden:
                writer.add(
                    "kafka_consumergroup_consumed_total",
                    {"topic": t.name, "consumergroup": c.group},
                    cumulate(took, [], rng.uniform(5, 60) * 86400 * stats[k][0]),
                )
            inc = cpu_inc[c.service]
            cpu_inc[c.service] = array("d", [a + x * svcs[c.service].cpu_per_msg for a, x in zip(inc, took)])
        out.append({"mean_rate": stats[k][0], "peak_hour_rate": stats[k][1]})
    return out
