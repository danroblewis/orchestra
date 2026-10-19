"""Builds the Kubernetes ground-truth examples from a compact service catalogue.

    uv run python sdlab/examples/k8s/build.py                 # every catalogue in this folder
    uv run python sdlab/examples/k8s/build.py small.yaml      # one

A catalogue (platform.yaml, small.yaml) names the services, their tiers, resources, dependencies,
databases, queues, node pools, the traffic and the events. This script turns it into an sd-* example:

    sdlab/examples/<id>.json                    the page: the measured stocks only (no flows)
    sdlab/examples/<id>/truth.model.json        the truth: every stock and flow with its equation
    sdlab/examples/<id>/truth.json              the answer key (sdlab.sdtruth.write_truth)
    sdlab/examples/<id>/truth.py, machines/     the usual simulator, history and live-feed programs

It is deterministic (no randomness, insertion-ordered JSON), so a re-run with the same catalogue
writes the same bytes. Everything is expressed in the current model format (MODEL.md): constant,
proportional and linear rates floored at 0, linear and table effects, a ceiling, schedules,
injections and a measured input. docs/research/k8s-model.md explains each mechanism, the
approximations, and which Prometheus metric each measured stock stands for.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
EXAMPLES = HERE.parent
DAY, WEEK = 1440, 10080

HPA_TARGET = 0.7              # CPU utilisation the HPA aims at (of the request)
HPA_UP_BAND, HPA_DOWN_BAND = 1.1, 0.9      # the HPA's 10% tolerance: scale up above 110%, down below 90%
HPA_DOWN_RATE = 0.5           # scale-down closes half the gap a minute, after the stabilisation window
STABILISE = 5                 # minutes: the scale-down stabilisation window (a SMOOTH of the CPU)
IDLE_CPU = 10                 # millicores a ready pod uses doing nothing
CPU_WINDOW = 0.5              # the CPU gauge is rate(...[2m]): it moves half way to the new load a minute
MEM_WINDOW = 0.5              # working set follows the load with a 2-minute lag (GC, page cache)
LB_CAPACITY = 2.5             # a pod accepts up to 2.5x its target load a minute before the LB queues
LB_TIMEOUT = 0.5              # half the requests queued beyond capacity time out each minute
BASE_ERRORS = 0.002           # 0.2% of requests fail (5xx) at any load
RETRY_SHARE = 0.6             # clients retry 60% of failed requests a minute later; 40% give up
WORKER_PULL = 1.2             # a worker pod pulls up to 120% of its CPU request's worth of messages
CA_DOWN_RATE = 0.05           # underused nodes are removed at 5% of the pool a minute
CA_UNNEEDED = 10              # minutes: the cluster autoscaler's scale-down-unneeded-time (a SMOOTH)
NODE_DELAY = 4                # minutes from the autoscaler's request to a Ready node (a DELAY3)
POD_GRACE = 1.0               # terminating pods are gone within a minute
ROLLOUT_RATE = 0.15           # a rolling update replaces 15% of the ready pods a minute (pausing at maxUnavailable)
ROLLOUT_MINUTES = 15
INV_POINTS = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 12, 14, 16, 18, 20, 23, 26, 30, 35, 40, 45, 50, 60, 70, 80, 100, 120, 150, 200]


# ---- helpers ----

def sid(name: str) -> str:
    return name.replace("-", "_")


def r6(x: float) -> float:
    return float(f"{x:.6g}")


def table(stock: str, points) -> dict:
    return {"stock": stock, "shape": "table", "points": [[r6(a), r6(b)] for a, b in points]}


def inverse(stock: str, top: int) -> dict:
    """1 / level as a table: exact at the whole numbers listed (replica and node counts), linear between."""
    pts = [x for x in INV_POINTS if x <= top] + [x for x in INV_POINTS if x > top][:1]
    return table(stock, [(x, 1 / x) for x in pts])


def times(stock: str, top: float) -> dict:
    """x level (a linear effect with normal 1, never clamped below `top`)."""
    return {"stock": stock, "shape": "linear", "normal": 1, "max": r6(top)}


def lin(c: float = 0.0, **terms: float) -> dict:
    return {"form": "linear", "c": r6(c), "terms": [{"stock": s, "k": r6(k)} for s, k in terms.items()]}


def prop(stock: str, k: float) -> dict:
    return {"form": "proportional", "stock": stock, "k": r6(k)}


def const(v: float) -> dict:
    return {"form": "constant", "value": r6(v)}


class Builder:
    def __init__(self, cat: dict):
        self.cat = cat
        self.stocks: list[dict] = []
        self.flows: list[dict] = []
        self.ids: set[str] = set()

    def stock(self, id_: str, name: str, unit: str, initial: float, measured: bool, row: int, col: int, query: str | None = None, **extra) -> str:
        assert id_ not in self.ids, id_
        self.ids.add(id_)
        s = {"id": id_, "name": name, "unit": unit, "initial": int(round(initial)), "x": 80 + 190 * col, "y": 60 + 110 * row}
        if not measured:
            s["measured"] = False
        if query:
            s["query"] = query
        s.update(extra)
        self.stocks.append(s)
        return id_

    def flow(self, id_: str, name: str, frm: str | None, to: str | None, rate: dict, effects: list | None = None, exact: bool = False, **extra) -> None:
        assert id_ not in self.ids, id_
        self.ids.add(id_)
        f = {"id": id_, "name": name, "from": frm, "to": to, "rate": rate, "machine": "environment"}
        if effects:
            f["effects"] = effects
        if exact:
            f["exact"] = True
        f.update(extra)
        self.flows.append(f)


# ---- traffic ----

def traffic_spec(tr: dict) -> dict:
    m = float(tr["mean"])
    terms = [{"fn": "constant", "value": m},
             {"fn": "sin", "amplitude": r6(tr["daily"] * m), "period": DAY, "phase": tr["peak_hour"] * 60 - DAY / 4},
             {"fn": "sin", "amplitude": r6(tr["half_daily"] * m), "period": DAY / 2, "phase": 420},
             {"fn": "pulse_train", "height": r6(-tr["weekend"] * m), "first": 5 * DAY + 1, "width": 2 * DAY, "every": WEEK}]
    sp = tr.get("spike")
    if sp:
        terms.append({"fn": "pulse_train", "height": r6(sp["height"] * m), "first": sp["day"] * DAY + sp["hour"] * 60 + 1,
                      "width": sp["minutes"], "every": WEEK})
    return {"terms": terms}


def traffic_at(spec: dict, tau: float) -> float:
    from sdlab.sdtruth import _term_value
    return sum(_term_value(t, tau) for t in spec["terms"])


# ---- the catalogue: loads and sizes ----

class Service:
    def __init__(self, name: str, spec: dict, tiers: dict):
        d = {**tiers[spec["tier"]], **spec}
        self.name, self.id, self.tier = name, sid(name), spec["tier"]
        self.cms, self.cpu_req, self.cpu_lim = float(d["cms"]), float(d["cpu_req"]), float(d["cpu_lim"])
        self.mem_req, self.mem_lim, self.mem_base = float(d["mem_req"]), float(d["mem_lim"]), float(d["mem_base"])
        self.mem_load, self.leak, self.startup = float(d["mem_load"]), float(d.get("leak") or 0), float(d["startup"])
        self.pool, self.headroom, self.fixed = d["pool"], float(d.get("headroom", 1.6)), d.get("replicas")
        self.min_override = d.get("min")
        self.calls = {k: float(v) for k, v in (d.get("calls") or {}).items()}
        self.db = {k: {"q": float(v.get("q", 0)), "w": float(v.get("w", 0)), "r": float(v.get("r", 0))} for k, v in (d.get("db") or {}).items()}
        self.produces = {k: float(v) for k, v in (d.get("produces") or {}).items()}
        self.consumes = d.get("consumes")


def loads(cat: dict, services: dict[str, Service], edge: float) -> dict[str, float]:
    """Requests (or messages) per minute each service handles when `edge` arrive at the edge, at steady state."""
    load = {n: 0.0 for n in services}
    queue = {q: 0.0 for q in cat.get("queues") or []}
    for _ in range(100):
        new = {n: edge * float(cat["ingress"].get(n, 0)) for n in services}
        nq = {q: 0.0 for q in queue}
        for n, s in services.items():
            for d, k in s.calls.items():
                new[d] += k * load[n]
            for q, k in s.produces.items():
                nq[q] += k * load[n]
        for n, s in services.items():
            if s.consumes:
                new[n] += nq[s.consumes]
        if all(abs(new[n] - load[n]) < 1e-9 for n in load):
            break
        load, queue = new, nq
    return load


def pods_for(s: Service, load: float) -> float:
    return (s.cms / 60 * load) / (s.cpu_req * HPA_TARGET - IDLE_CPU)


def build(path: Path) -> dict:
    cat = yaml.safe_load(path.read_text())
    tiers = cat["tiers"]
    services = {n: Service(n, spec, tiers) for n, spec in cat["services"].items()}
    for n, s in services.items():
        for d in s.calls:
            assert d in services, f"{n} calls {d}, which is not a service"
        for db in s.db:
            assert db in (cat.get("databases") or {}), f"{n} queries {db}, which is not a database"
    tr = traffic_spec(cat["traffic"])
    steps, long_steps = int(cat["days"]) * DAY, int(cat["long_days"]) * DAY
    weekday = [traffic_at({"terms": [t for t in tr["terms"] if t["fn"] != "pulse_train"]}, tau) for tau in range(1, DAY + 1)]
    peak_edge, trough_edge = max(weekday), min(weekday) - cat["traffic"]["weekend"] * cat["traffic"]["mean"]
    start_edge = traffic_at(tr, 1)
    peak, trough, start = loads(cat, services, peak_edge), loads(cat, services, trough_edge), loads(cat, services, start_edge)

    # sizes: replicas, LB capacity, memory per unit of load
    for n, s in services.items():
        if s.fixed:
            s.min = s.max = int(s.fixed)
        else:
            s.max = max(3, math.ceil(pods_for(s, peak[n]) * s.headroom))
            s.min = int(s.min_override or max(2, min(s.max - 1, math.floor(pods_for(s, trough[n])))))
        s.target_load = (s.cpu_req * HPA_TARGET - IDLE_CPU) * 60 / s.cms          # per pod per minute at the HPA's target
        s.lb_cap = LB_CAPACITY * s.target_load
        s.pull = WORKER_PULL * s.cpu_req * 60 / s.cms
        s.mem_a = s.mem_load * s.mem_base / s.target_load                          # MiB per (request a minute per pod)
        s.r0 = int(min(s.max, max(s.min, math.ceil(pods_for(s, start[n]) * HPA_UP_BAND))))
        s.top = s.max + 2

    b = Builder(cat)
    b.stock("ingress", "Edge load balancer: requests this minute", "requests", start_edge, True, 0, 0,
            query="sum(increase(nginx_ingress_controller_requests[1m]))")
    b.flow("traffic_in", "Users' requests reach the edge load balancer", None, "ingress", prop("traffic", 1.0))

    # ---- node pools (stocks first: services read them) ----
    pools = cat["pools"]
    pool_svcs = {p: [s for s in services.values() if s.pool == p] for p in pools}
    nodes0 = {}
    for p, ps in pool_svcs.items():
        spec = pools[p]
        req = sum(s.cpu_req * s.r0 for s in ps)
        nodes0[p] = int(min(spec["max"], max(spec["min"], math.ceil(req / (spec["cpu"] * (0.70 - spec["daemonsets"] / 100))))))

    row = 1
    queues = cat.get("queues") or []
    for i, q in enumerate(queues):
        prod = sum(k * start[n] for n, s in services.items() for qq, k in s.produces.items() if qq == q)
        b.stock(f"mq_{sid(q)}", f"Queue {q}: messages waiting", "messages", prod, True, row, 1 + i,
                query=f'sum(kafka_consumergroup_lag{{topic="{q}"}})')
    row += 1

    # ---- services ----
    srow = {}
    for n, s in services.items():
        srow[n] = row
        row += 1
    for n, s in services.items():
        i, r, L0 = s.id, srow[n], start[n]
        lab = s.name
        worker = bool(s.consumes)
        R0 = s.r0
        cpu0 = s.cms / 60 * L0 + IDLE_CPU * R0
        if not worker:
            b.stock(f"{i}_lbq", f"{lab}: queued at its load balancer", "requests", L0, False, r, 0)
        b.stock(f"{i}_inflight", f"{lab}: requests in flight", "requests", L0, True, r, 1,
                query=f'sum(increase(http_server_requests_total{{service="{lab}"}}[1m]))')
        b.stock(f"{i}_retry", f"{lab}: failed requests waiting to be retried", "requests", 0, False, r, 2)
        b.stock(f"{i}_cpu", f"{lab}: CPU used", "millicores", cpu0, True, r, 3,
                query=f'1000 * sum(rate(container_cpu_usage_seconds_total{{container="{lab}"}}[2m]))')
        b.stock(f"{i}_cpu_pod", f"{lab}: CPU per ready pod", "millicores", cpu0 / R0, False, r, 4)
        if not s.fixed:
            b.stock(f"{i}_cpu_slow", f"{lab}: CPU over the HPA's stabilisation window", "millicores", cpu0, False, r, 5)
        # the cgroup limit caps the working set: a ceiling of limit x (1 + MEM_WINDOW), because a stock
        # drained at k a step under a ceiling settles at max / (1 + k) (MODEL.md), which is the limit
        b.stock(f"{i}_mem", f"{lab}: memory working set per pod", "MiB", s.mem_base + s.mem_a * L0 / R0, True, r, 6,
                query=f'avg(container_memory_working_set_bytes{{container="{lab}"}}) / 2^20', max=r6(s.mem_lim * (1 + MEM_WINDOW)))
        if s.leak:
            b.stock(f"{i}_leak", f"{lab}: memory leaked per pod", "MiB", 0, False, r, 7)
        if not s.fixed:
            b.stock(f"{i}_desired", f"{lab}: desired replicas (HPA)", "pods", R0, True, r, 8, max=s.max,
                    query=f'kube_horizontalpodautoscaler_status_desired_replicas{{horizontalpodautoscaler="{lab}"}}')
        b.stock(f"{i}_pending", f"{lab}: pods pending", "pods", 0, False, r, 9)
        b.stock(f"{i}_starting", f"{lab}: pods starting", "pods", 0, False, r, 10)
        b.stock(f"{i}_ready", f"{lab}: ready replicas", "pods", R0, True, r, 11,
                query=f'kube_deployment_status_replicas_ready{{deployment="{lab}"}}')
        b.stock(f"{i}_terminating", f"{lab}: pods terminating", "pods", 0, False, r, 12)
        b.stock(f"{i}_oom", f"{lab}: pods restarting after an OOM kill", "pods", 0, True, r, 13,
                query=f'sum(increase(kube_pod_container_status_restarts_total{{container="{lab}"}}[1m]) and on(pod) kube_pod_container_status_last_terminated_reason{{reason="OOMKilled"}})')

    dbs = cat.get("databases") or {}
    db_info = {}
    for j, (dname, spec) in enumerate(dbs.items()):
        d = sid(dname)
        q_peak = sum(v["q"] * peak[n] for n, s in services.items() for dd, v in s.db.items() if dd == dname)
        q0 = sum(v["q"] * start[n] for n, s in services.items() for dd, v in s.db.items() if dd == dname)
        cap = spec["headroom"] * q_peak
        L = spec["latency_ms"] / 60000
        db_info[dname] = {"cap": cap, "q_peak": q_peak, "L": L}
        b.stock(f"{d}_queue", f"{dname}: queries queued or running this minute", "queries", q0, False, row, 0)
        b.stock(f"{d}_conn", f"{dname}: connections in use (primary)", "connections", L * q0, True, row, 1,
                query=f'sum(pg_stat_activity_count{{datname="{dname}",state="active"}})')
        if spec.get("replica"):
            r_peak = sum(v["r"] * peak[n] for n, s in services.items() for dd, v in s.db.items() if dd == dname)
            w_peak = sum(v["w"] * peak[n] for n, s in services.items() for dd, v in s.db.items() if dd == dname)
            r0 = sum(v["r"] * start[n] for n, s in services.items() for dd, v in s.db.items() if dd == dname)
            w0 = sum(v["w"] * start[n] for n, s in services.items() for dd, v in s.db.items() if dd == dname)
            Lr = 0.4 * spec["replica_pool"] / max(1.0, r_peak)              # the replica's latency: 40% of its pool busy at peak
            apply_s = spec["lag_at_peak"] * 60 / max(1.0, w_peak)           # replica seconds to apply one write
            db_info[dname].update(Lr=Lr, apply=apply_s)
            b.stock(f"{d}_replica_conn", f"{dname}: connections in use (replica)", "connections", Lr * r0, True, row, 2,
                    query=f'sum(pg_stat_activity_count{{datname="{dname}",state="active",instance=~".*replica.*"}})')
            b.stock(f"{d}_lag", f"{dname}: replication lag", "seconds", w0 * apply_s, True, row, 3,
                    query=f'max(pg_replication_lag_seconds{{datname="{dname}"}})')
        row += 1

    for j, (p, spec) in enumerate(pools.items()):
        ps = pool_svcs[p]
        occ0 = spec["daemonsets"] + sum(100 * s.cpu_req * s.r0 for s in ps) / (spec["cpu"] * nodes0[p])
        mocc0 = spec["daemonsets"] + sum(100 * s.mem_req * s.r0 for s in ps) / (spec["mem"] * nodes0[p])
        b.stock(f"nodes_{p}", f"Node pool {p}: ready nodes", "nodes", nodes0[p], True, row, 0,
                query=f'sum(kube_node_status_condition{{condition="Ready",status="true",node=~".*{p}.*"}})')
        b.stock(f"cpu_requested_{p}", f"Node pool {p}: CPU requested", "% of allocatable", occ0, True, row, 1,
                query=f'100 * sum(kube_pod_container_resource_requests{{resource="cpu",node=~".*{p}.*"}}) / sum(kube_node_status_allocatable{{resource="cpu",node=~".*{p}.*"}})')
        b.stock(f"mem_requested_{p}", f"Node pool {p}: memory requested", "% of allocatable", mocc0, True, row, 2,
                query=f'100 * sum(kube_pod_container_resource_requests{{resource="memory",node=~".*{p}.*"}}) / sum(kube_node_status_allocatable{{resource="memory",node=~".*{p}.*"}})')
        b.stock(f"cpu_requested_slow_{p}", f"Node pool {p}: CPU requested over the autoscaler's unneeded time", "% of allocatable", occ0, False, row, 3)
        for k in (1, 2, 3):
            b.stock(f"provisioning_{p}_{k}", f"Node pool {p}: nodes provisioning (stage {k} of 3)", "nodes", 0, False, row, 3 + k)
        row += 1

    # ---- flows: the edge ----
    for n, share in cat["ingress"].items():
        b.flow(f"route_{sid(n)}", f"Edge load balancer routes to {n}", "ingress", f"{sid(n)}_lbq", prop("ingress", share))

    def work_effects(s: Service) -> list:
        """What slows a service's work: CPU throttling at its limit, and waiting on a saturated
        dependency (its two busiest synchronous calls' load-balancer queues, and its databases' queues)."""
        e = [table(f"{s.id}_cpu_pod", [(0, 1), (0.85 * s.cpu_lim, 1), (s.cpu_lim, 0.7), (1.5 * s.cpu_lim, 0.4), (3 * s.cpu_lim, 0.2)])]
        for d, _ in sorted(s.calls.items(), key=lambda kv: -kv[1])[:2]:
            ds = services[d]
            if ds.consumes:
                continue
            e.append(table(f"{ds.id}_lbq", [(1.6 * peak[d], 1), (4 * peak[d], 0.4)]))
        for dname in s.db:
            c = db_info[dname]["cap"]
            e.append(table(f"{sid(dname)}_queue", [(1.2 * c, 1), (3 * c, 0.4)]))
        return e

    def unavailable(s: Service) -> dict:
        """maxUnavailable 25%: a rolling update pauses while a quarter of the replicas are still starting."""
        q = max(1.0, 0.25 * (s.fixed or min(s.max, pods_for(s, peak[s.name]))))      # a quarter of the replicas at the weekday peak
        return table(f"{s.id}_starting", [(0, 1), (q, 0)])

    def oom_table(s: Service, stock: str) -> dict:
        return table(stock, [(0.92 * s.mem_lim, 0), (s.mem_lim, 0.25), (1.1 * s.mem_lim, 0.8)])

    schedule_changes = []
    for n, s in services.items():
        i, W = s.id, work_effects(s)
        thr = W[0]
        inf, retry, ready = f"{i}_inflight", f"{i}_retry", f"{i}_ready"
        # requests: the load balancer queue (hidden) spreads requests over the ready pods
        if s.consumes:
            q = f"mq_{sid(s.consumes)}"
            b.flow(f"{i}_pull", f"{n} pulls messages from {s.consumes}", q, inf, lin(**{ready: s.pull}), [thr])
            resend = q
        else:
            lbq = f"{i}_lbq"
            b.flow(f"{i}_dispatch", f"{n}'s load balancer sends requests to ready pods", lbq, inf, lin(**{ready: s.lb_cap}))
            b.flow(f"{i}_lb_timeout", f"{n}: requests time out at its load balancer", lbq, retry, lin(**{lbq: LB_TIMEOUT, ready: -LB_TIMEOUT * s.lb_cap}))
            resend = lbq
        b.flow(f"{i}_done", f"{n} completes requests", inf, None, prop(inf, 1.0), W)
        b.flow(f"{i}_errors", f"{n}: requests fail (5xx)", inf, retry, prop(inf, BASE_ERRORS))
        b.flow(f"{i}_timeouts", f"{n}: requests time out while it is throttled", inf, retry, prop(inf, 0.3),
               [table(f"{i}_cpu_pod", [(s.cpu_lim, 0), (1.5 * s.cpu_lim, 1)])])
        b.flow(f"{i}_oom_lost", f"{n}: requests lost when a pod is OOM-killed", inf, retry, prop(inf, 1.0), [oom_table(s, f"{i}_mem")])
        b.flow(f"{i}_retried", f"Clients retry {n}", retry, resend, prop(retry, RETRY_SHARE))
        b.flow(f"{i}_given_up", f"Clients give up on {n}", retry, None, prop(retry, 1 - RETRY_SHARE))
        # calls downstream, messages produced, queries: made while the work is done (the same effects)
        for d, k in s.calls.items():
            b.flow(f"{i}_calls_{sid(d)}", f"{n} calls {d}", None, f"{sid(d)}_lbq", prop(inf, k), W)
        for qn, k in s.produces.items():
            b.flow(f"{i}_produces_{sid(qn)}", f"{n} publishes to {qn}", None, f"mq_{sid(qn)}", prop(inf, k), W)
        for dname, v in s.db.items():
            d = sid(dname)
            if v["q"]:
                b.flow(f"{i}_queries_{d}", f"{n} queries {dname}", None, f"{d}_queue", prop(inf, v["q"]), W)
            if v["r"] and "Lr" in db_info[dname]:
                b.flow(f"{i}_reads_{d}", f"{n} reads from {dname}'s replica", None, f"{d}_replica_conn", prop(inf, v["r"] * db_info[dname]["Lr"]), W)
            if v["w"] and "apply" in db_info[dname]:
                b.flow(f"{i}_writes_{d}", f"{n}'s writes to {dname} reach the replica's backlog", None, f"{d}_lag", prop(inf, v["w"] * db_info[dname]["apply"]), W)
        # CPU: used by the work done (throttled at the limit) and by idle pods; the gauge is a 2-minute rate
        cpu, cpu_pod = f"{i}_cpu", f"{i}_cpu_pod"
        b.flow(f"{i}_cpu_work", f"{n}: CPU used by requests", None, cpu, prop(inf, CPU_WINDOW * s.cms / 60), W)
        b.flow(f"{i}_cpu_idle", f"{n}: CPU used by idle pods", None, cpu, prop(ready, CPU_WINDOW * IDLE_CPU))
        b.flow(f"{i}_cpu_window", f"{n}: CPU reading moves on", cpu, None, prop(cpu, CPU_WINDOW))
        b.flow(f"{i}_cpu_pod_in", f"{n}: CPU per ready pod (CPU / ready replicas)", None, cpu_pod, prop(cpu, 1.0), [inverse(ready, s.top)], exact=True)
        b.flow(f"{i}_cpu_pod_out", f"{n}: CPU per ready pod is re-read", cpu_pod, None, prop(cpu_pod, 1.0), exact=True)
        # memory: base + load per pod + leaked; the working set follows with a 2-minute lag
        mem = f"{i}_mem"
        base = {"c": MEM_WINDOW * s.mem_base}
        terms = {f"{i}_leak": MEM_WINDOW} if s.leak else {}
        b.flow(f"{i}_mem_base", f"{n}: memory a pod needs at rest" + (" plus what it has leaked" if s.leak else ""), None, mem, lin(base["c"], **terms))
        b.flow(f"{i}_mem_load", f"{n}: memory for the requests a pod holds", None, mem, prop(inf, MEM_WINDOW * s.mem_a), [inverse(ready, s.top)])
        b.flow(f"{i}_mem_freed", f"{n}: memory freed", mem, None, prop(mem, MEM_WINDOW))
        if s.leak:
            leak = f"{i}_leak"
            b.flow(f"{i}_leaks", f"{n} leaks memory", None, leak, const(s.leak))
            b.flow(f"{i}_leak_oom", f"{n}: an OOM-killed pod restarts with no leak", leak, None, prop(leak, 1.0), [oom_table(s, mem)])
            b.flow(f"{i}_leak_new_pods", f"{n}: new pods start with no leak", leak, None, prop(leak, 1 / s.startup),
                   [times(f"{i}_starting", s.top), inverse(ready, s.top)])
            b.flow(f"{i}_leak_rollout", f"{n}: a rolling update replaces leaky pods", leak, None, const(0), [unavailable(s)])
        # pods: the Deployment controller, the scheduler, startup, OOM kills, termination
        desired = f"{i}_desired"
        pend, start, term, oom = f"{i}_pending", f"{i}_starting", f"{i}_terminating", f"{i}_oom"
        pool = s.pool
        want = {desired: 1.0} if not s.fixed else {}
        c = 0.0 if not s.fixed else float(s.fixed)
        b.flow(f"{i}_create", f"Deployment creates {n} pods", None, pend, lin(c, **want, **{pend: -1, start: -1, ready: -1, oom: -1}), exact=True)
        b.flow(f"{i}_delete_pending", f"Deployment deletes pending {n} pods", pend, None, lin(-c, **{k: -v for k, v in want.items()}, **{pend: 1, start: 1, ready: 1, oom: 1}), exact=True)
        b.flow(f"{i}_delete_ready", f"Deployment scales {n} down", ready, term, lin(-c, **{k: -v for k, v in want.items()}, **{start: 1, ready: 1, oom: 1}), exact=True)
        b.flow(f"{i}_scheduled", f"Scheduler places {n} pods on nodes", pend, start, prop(pend, 1.0),
               [table(f"cpu_requested_{pool}", [(88, 1), (97, 0)]), table(f"mem_requested_{pool}", [(88, 1), (97, 0)])])
        b.flow(f"{i}_started", f"{n} pods pass their readiness probe", start, ready, prop(start, 1 / s.startup))
        b.flow(f"{i}_oom_kill", f"{n} pods are OOM-killed", ready, oom, prop(ready, 1.0), [oom_table(s, mem)])
        b.flow(f"{i}_restart", f"OOM-killed {n} containers restart", oom, start, prop(oom, 1.0))
        b.flow(f"{i}_rollout", f"Rolling update replaces {n} pods", ready, term, const(0), [unavailable(s)])
        b.flow(f"{i}_gone", f"Terminating {n} pods are gone", term, None, prop(term, POD_GRACE))
        # the HPA: desired replicas follow CPU / (request x target), up at once, down after the window
        if not s.fixed:
            per = s.cpu_req * HPA_TARGET
            b.flow(f"{i}_hpa_up", f"HPA scales {n} up", None, desired, lin(**{cpu: 1 / (per * HPA_UP_BAND), desired: -1.0}), exact=True)
            b.flow(f"{i}_hpa_down", f"HPA scales {n} down", desired, None, lin(**{desired: HPA_DOWN_RATE, f"{i}_cpu_slow": -HPA_DOWN_RATE / (per * HPA_DOWN_BAND)}),
                   [table(desired, [(s.min, 0), (s.min + 1, 1)])], exact=True)
            b.flow(f"{i}_cpu_slow_in", f"{n}: the HPA's window takes in the CPU reading", None, f"{i}_cpu_slow", prop(cpu, 1 / STABILISE), exact=True)
            b.flow(f"{i}_cpu_slow_out", f"{n}: the HPA's window lets go of old readings", f"{i}_cpu_slow", None, prop(f"{i}_cpu_slow", 1 / STABILISE), exact=True)

    # ---- databases ----
    for dname, spec in dbs.items():
        d, info = sid(dname), db_info[dname]
        qs, cap, L = f"{d}_queue", info["cap"], info["L"]
        b.flow(f"{d}_served", f"{dname} executes queries", qs, None, const(cap))
        b.flow(f"{d}_query_timeout", f"{dname}: queries time out waiting", qs, None, lin(-0.5 * cap, **{qs: 0.5}))
        # connections in use = queries x latency; latency grows as the database saturates (slow
        # queries), and the pool caps them: a table of the queue gives min(slowdown, pool / (L x queue))
        pts = []
        for u in (0, 0.25, 0.5, 0.7, 0.85, 1.0, 1.1, 1.2, 1.35, 1.5, 1.75, 2.0, 2.5, 3.0, 4.0, 5.0, 7.0, 10.0):
            slow = 1 + 0.5 * u + 4 * max(0.0, u - 0.7) ** 1.5 * 3
            qv = u * cap
            pts.append((qv, min(slow, spec["pool"] / (L * qv)) if qv > 0 else slow))
        b.flow(f"{d}_conn_open", f"{dname}: queries hold connections", None, f"{d}_conn", prop(qs, L), [table(qs, pts)])
        b.flow(f"{d}_conn_close", f"{dname}: connections return to the pool", f"{d}_conn", None, prop(f"{d}_conn", 1.0))
        if spec.get("replica"):
            rc, lag = f"{d}_replica_conn", f"{d}_lag"
            b.flow(f"{d}_replica_close", f"{dname} replica: connections return to the pool", rc, None, prop(rc, 1.0))
            b.flow(f"{d}_apply", f"{dname} replica applies the primary's writes", lag, None, const(60),
                   [table(rc, [(0.5 * spec["replica_pool"], 1), (spec["replica_pool"], 0.6)])])

    # ---- message queues: messages expire after a retention (rarely binding) ----
    for q in queues:
        b.flow(f"mq_{sid(q)}_expired", f"Queue {q}: messages expire unconsumed", f"mq_{sid(q)}", None, prop(f"mq_{sid(q)}", 0.0005))

    # ---- node pools: occupancy, the cluster autoscaler ----
    for p, spec in pools.items():
        ps = pool_svcs[p]
        nodes, occ, mocc, slow = f"nodes_{p}", f"cpu_requested_{p}", f"mem_requested_{p}", f"cpu_requested_slow_{p}"
        top = spec["max"] + 2
        sched = lambda key: {f"{s.id}_{k}": 100 * getattr(s, key) / spec["cpu" if key == "cpu_req" else "mem"] for s in ps for k in ("starting", "ready", "oom")}  # noqa: E731
        b.flow(f"{p}_cpu_requests", f"Pool {p}: CPU requests of scheduled pods / allocatable", None, occ, lin(**sched("cpu_req")), [inverse(nodes, top)], exact=True)
        b.flow(f"{p}_cpu_daemonsets", f"Pool {p}: CPU requests of daemonsets", None, occ, const(spec["daemonsets"]), exact=True)
        b.flow(f"{p}_cpu_requested_out", f"Pool {p}: CPU requested is re-read", occ, None, prop(occ, 1.0), exact=True)
        b.flow(f"{p}_mem_requests", f"Pool {p}: memory requests of scheduled pods / allocatable", None, mocc, lin(**sched("mem_req")), [inverse(nodes, top)], exact=True)
        b.flow(f"{p}_mem_daemonsets", f"Pool {p}: memory requests of daemonsets", None, mocc, const(spec["daemonsets"]), exact=True)
        b.flow(f"{p}_mem_requested_out", f"Pool {p}: memory requested is re-read", mocc, None, prop(mocc, 1.0), exact=True)
        b.flow(f"{p}_slow_in", f"Pool {p}: the autoscaler's unneeded timer takes in occupancy", None, slow, prop(occ, 1 / CA_UNNEEDED), exact=True)
        b.flow(f"{p}_slow_out", f"Pool {p}: the autoscaler's unneeded timer lets go", slow, None, prop(slow, 1 / CA_UNNEEDED), exact=True)
        prov = [f"provisioning_{p}_{k}" for k in (1, 2, 3)]
        need = {f"{s.id}_pending": s.cpu_req / spec["cpu"] for s in ps}
        b.flow(f"{p}_scale_up", f"Cluster autoscaler adds {p} nodes for pending pods", None, prov[0], lin(**need, **{x: -1.0 for x in prov}),
               [table(occ, [(85, 0), (92, 1)]), table(nodes, [(spec["max"] - 1, 1), (spec["max"], 0)])], exact=True,
               delay={"id": f"{p}_nodes", "stage": 1, "of": 3, "time": NODE_DELAY})
        for k, (a, z) in enumerate(zip(prov, prov[1:] + [nodes]), start=2):
            b.flow(f"{p}_provision_{k - 1}", f"Pool {p}: a new node boots (stage {k - 1})", a, z, prop(a, 3 / NODE_DELAY),
                   delay={"id": f"{p}_nodes", "stage": k, "of": 3, "time": NODE_DELAY})
        b.flow(f"{p}_scale_down", f"Cluster autoscaler removes underused {p} nodes", nodes, None, prop(nodes, CA_DOWN_RATE),
               [table(slow, [(45, 1), (55, 0)]), table(occ, [(55, 1), (65, 0)]), table(nodes, [(spec["min"], 0), (spec["min"] + 1, 1)])], exact=True)

    # ---- events: rolling updates (announced eras), node failures (announced injections) ----
    for ev in (cat.get("events") or {}).get("deploys") or []:
        t0 = ev["day"] * DAY + ev["hour"] * 60 + 1
        names = ev["services"]
        on, off = {}, {}
        for n in names:
            s = services[n]
            on[f"{s.id}_rollout"], off[f"{s.id}_rollout"] = prop(f"{s.id}_ready", ROLLOUT_RATE), const(0)
            if s.leak:
                on[f"{s.id}_leak_rollout"], off[f"{s.id}_leak_rollout"] = prop(f"{s.id}_leak", ROLLOUT_RATE), const(0)
        schedule_changes.append({"t": t0, "label": f"Rolling update of {', '.join(names)}", "set": on, "announce": True})
        schedule_changes.append({"t": t0 + ROLLOUT_MINUTES, "label": "Rolling update finished", "set": off, "announce": True})
    injections = []
    for ev in (cat.get("events") or {}).get("node_failures") or []:
        for week in range(math.ceil(long_steps / WEEK)):
            t0 = week * WEEK + ev["day"] * DAY + ev["hour"] * 60 + 1
            if t0 > long_steps:
                continue
            p, k = ev["pool"], int(ev["nodes"])
            injections.append({"t": t0, "stock": f"nodes_{p}", "amount": -k})
            # the pods on the lost node(s) go back to pending: each service loses its share, by its load then
            edge = traffic_at(tr, t0)
            ld = loads(cat, services, edge)
            for s in pool_svcs[p]:
                pods = min(s.max, max(s.min, math.ceil(pods_for(s, ld[s.name]) * HPA_UP_BAND)))
                lost = round(pods * k / max(1, nodes0[p]))
                if lost:
                    injections.append({"t": t0, "stock": f"{s.id}_ready", "amount": -lost})
                    injections.append({"t": t0, "stock": f"{s.id}_pending", "amount": lost})

    measured = [s for s in b.stocks if s.get("measured", True)]
    truth = {"id": f"{cat['id']}-truth", "name": f"{cat['name']}: the truth", "time_unit": "minute",
             "seed": int(cat["seed"]), "steps": steps, "long_steps": long_steps, "noise": {"counts": True},
             "inputs": {"traffic": tr}, "stocks": b.stocks, "flows": b.flows, "machines": [],
             "schedule": {"every": WEEK, "changes": schedule_changes}, "injections": injections}
    n_svc = len(services)
    desc = cat.get("description") or (
        f"{n_svc} services on Kubernetes serving HTTP requests behind an edge load balancer, measured every minute for "
        f"{cat['days']} days (Monday to Sunday): requests in flight, CPU used, memory working set per pod, desired and ready "
        f"replicas and OOM restarts for every service; nodes and CPU and memory requested per node pool"
        + (", connections and replication lag per database" if dbs else "") + (", messages waiting per queue" if queues else "")
        + ". The main input is the traffic at the edge (a measured input: a daily cycle peaking around midday with weekend dips"
        + (" and a Friday-evening spike" if cat["traffic"].get("spike") else "") + "). "
        "Inside, each service has a load-balancer queue, retries, an HPA scaling on CPU (fast up, slow down), pods pending, starting, "
        "ready and terminating, CPU throttling at the limit, memory growing with load (and leaking in some), and OOM kills; "
        "the cluster autoscaler adds nodes for pending pods and removes underused ones. Events: "
        + "; ".join([f"a rolling update of {', '.join(e['services'])} (announced)" for e in (cat.get('events') or {}).get('deploys') or []]
                    + [f"a node failure in pool {e['pool']} (an announced injection)" for e in (cat.get('events') or {}).get('node_failures') or []])
        + f". {len(measured)} measured stocks, {len(b.stocks) - len(measured)} hidden, {len(b.flows)} flows. "
        f"The ground truth is in {cat['id']}/truth.model.json, built from the service catalogue sdlab/examples/k8s/{path.name}; "
        f"docs/research/k8s-model.md maps each stock to its Prometheus metric.")
    page = {"id": cat["id"], "name": cat["name"], "description": desc, "time_unit": "minute", "horizon": 240, "dt": 1,
            "stocks": [{k: v for k, v in s.items() if k not in ("measured", "max")} for s in measured],
            "flows": [], "machines": [], "history": {"program": f"{cat['id']}/history"}, "sensors": [{"program": f"{cat['id']}/live"}]}
    return {"truth": truth, "page": page, "services": services, "peak": peak, "trough": trough}


PROGRAMS = {
    "sim.py": '''"""The {id} example's simulator: its truth model (../truth.model.json), a system dynamics model
stepped with SD Lab's own equations (see sdlab/sdtruth.py). Built by sdlab/examples/k8s/build.py."""

from pathlib import Path

from sdlab.sdtruth import Truth

TRUTH = Truth(Path(__file__).resolve().parent.parent / "truth.model.json")
SEED, STEPS, LONG_STEPS = TRUTH.seed, TRUTH.steps, TRUTH.long_steps
MEASURED_STOCKS = TRUTH.measured_ids
UNBOUNDED = True                       # a longer run begins with the shorter one: it can go on forever


def run(seed: int = SEED, steps: int = STEPS) -> dict:
    return TRUTH.run(seed, steps)


def measured(seed: int = SEED, steps: int = STEPS) -> dict:
    return TRUTH.measured(seed, steps)
''',
    "history.py": '''"""History: what the example's dashboard showed at every step (see sdlab/sdtruth.py).

    history.py [seed] [steps]
"""

import sim

from sdlab.sdtruth import history_main

if __name__ == "__main__":
    history_main(sim.TRUTH)
''',
    "live.py": '''"""Sensor: the {id} example, live; see sdlab/livefeed.py.

    live.py [seed]

A lighter feed than the other examples' (a week of this model takes most of a minute to simulate,
and a sensor has a minute per tick): its first recording is one day, of the measured levels only
(no flow counters), and once a run is past half of a recording, the next one (twice as long) is made
in the background, so the run does not wait for it. SDLAB_LIVE_STEPS works as for the other examples.
"""

import io
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

import sim

from sdlab.livefeed import play, recording

LIVE_STEPS = 1440
FEED = SimpleNamespace(SEED=sim.SEED, STEPS=sim.STEPS, LONG_STEPS=LIVE_STEPS, UNBOUNDED=True,
                       measured=lambda seed, steps: {k: v for k, v in sim.measured(seed, steps).items() if k != "counters"})
HERE = Path(__file__).resolve().parent

if __name__ == "__main__":
    if sys.argv[1:2] == ["--prepare"]:                      # in the background: live.py --prepare <steps> <seed>
        recording(FEED, HERE, int(sys.argv[3]), int(sys.argv[2]))
        sys.exit(0)
    stdin = "" if sys.stdin.isatty() else sys.stdin.read()
    sys.stdin = io.StringIO(stdin)
    play(FEED, __file__)
    if not os.environ.get("SDLAB_LIVE_STEPS"):
        seed = int(sys.argv[1]) if len(sys.argv) > 1 else sim.SEED
        t, steps = int((json.loads(stdin) if stdin.strip() else {}).get("t") or 1), LIVE_STEPS
        while t > steps:
            steps *= 2
        if t > steps // 2:
            lock = Path(tempfile.gettempdir()) / f"sdlab-live-prepare-{HERE.parent.name}-{seed}-{2 * steps}"
            try:
                os.close(os.open(lock, os.O_CREAT | os.O_EXCL))
            except FileExistsError:
                pass
            else:
                subprocess.Popen([sys.executable, __file__, "--prepare", str(2 * steps), str(seed)], start_new_session=True,
                                 stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, cwd=HERE)
''',
}

TRUTH_PY = '''"""Writes truth.json, the answer key, from truth.model.json (see sdlab/sdtruth.py)."""

from pathlib import Path

from sdlab.sdtruth import Truth, write_truth

if __name__ == "__main__":
    here = Path(__file__).resolve().parent
    write_truth(Truth(here / "truth.model.json"), here / "truth.json")
'''


def write(path: Path) -> dict:
    from sdlab.sdtruth import Truth, write_truth
    out = build(path)
    truth, page = out["truth"], out["page"]
    ex = EXAMPLES / page["id"]
    (ex / "machines").mkdir(parents=True, exist_ok=True)
    (ex / "truth.model.json").write_text(json.dumps(truth, indent=1) + "\n")
    (EXAMPLES / f"{page['id']}.json").write_text(json.dumps(page, indent=1) + "\n")
    for name, text in PROGRAMS.items():
        (ex / "machines" / name).write_text(text.replace("{id}", page["id"]))
    (ex / "truth.py").write_text(TRUTH_PY)
    write_truth(Truth(ex / "truth.model.json"), ex / "truth.json")
    m = sum(1 for s in truth["stocks"] if s.get("measured", True))
    print(f"{page['id']}: {len(out['services'])} services, {len(truth['stocks'])} stocks ({m} measured, {len(truth['stocks']) - m} hidden), "
          f"{len(truth['flows'])} flows, {truth['steps']} steps")
    return out


if __name__ == "__main__":
    names = sys.argv[1:] or sorted(p.name for p in HERE.glob("*.yaml"))
    for n in names:
        write(HERE / n)
