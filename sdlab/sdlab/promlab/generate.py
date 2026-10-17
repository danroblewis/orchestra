"""Generate a fleet's Prometheus data and its ground truth.

python -m sdlab.promlab.generate --out DIR --services 400 --days 30 --step 300 --seed 7
"""

import argparse
import json
import os
import time

from . import fleet as fleet_mod
from . import simulate
from .store import Writer


def generate(
    out: str, services: int = 400, days: float = 30, step: int = 300, seed: int = 7, end: int | None = None
) -> dict:
    """Write `index.json`, `<metric>.bin` and `truth.json` into `out`; return the truth."""
    end = int(end if end is not None else time.time()) // step * step
    n = int(days * 86400 // step)
    start = end - (n - 1) * step
    f = fleet_mod.design(services, start, step, n, seed)
    writer = Writer(out, start, step, n)
    result = simulate.run(f, writer, seed)
    writer.close()
    truth = _truth(f, result, seed, writer)
    with open(os.path.join(out, "truth.json"), "w") as fh:
        json.dump(truth, fh, indent=1)
    return truth


def _truth(f, result, seed, writer) -> dict:
    ts = f.ts
    svcs = f.services
    hidden = [{"topic": t.name, "consumergroup": c.group} for t in f.topics for c in t.consumers if c.hidden]
    leaks = [s.name for s in svcs if s.leak_rate > 0]
    return {
        "about": "Ground truth for a fabricated Kubernetes fleet. Times are epoch seconds on the sample grid.",
        "seed": seed,
        "start": f.start,
        "end": ts(f.n - 1),
        "step": f.step,
        "n": f.n,
        "namespaces": sorted({s.namespace for s in svcs}),
        "services": [
            {
                "name": s.name,
                "namespace": s.namespace,
                "tier": s.tier,
                "edge": s.edge,
                "external_peak_rps": round(s.base_rps, 3) if s.edge else 0,
                "peak_hour_utc": round(s.peak_hour, 2) if s.edge else None,
                "mean_rps": round(result["mean_rps"][i], 4),
                "replicas": [[ts(j), r] for j, r in s.replica_plan],
                "per_replica_rps": [[ts(j), round(v, 3)] for j, v in s.capacity_plan],
                "under_provisioned": s.under_provisioned,
                "latency_s": round(s.latency, 5),
                "cpu_seconds_per_request": round(s.cpu_per_req, 6),
                "database": s.database,
                "db_queries_per_request": s.db_queries_per_req or None,
                "leak_bytes_per_s": round(s.leak_rate, 1) or None,
                "deploys": [ts(j) for j in s.deploys],
                "restarts": [{"ts": ts(r["step"]), "cause": r["cause"]} for r in result["restarts"][i]],
            }
            for i, s in enumerate(svcs)
        ],
        "edges": [
            {
                "caller": svcs[e.caller].name,
                "callee": svcs[e.callee].name,
                "caller_namespace": svcs[e.caller].namespace,
                "callee_namespace": svcs[e.callee].namespace,
                "cross_namespace": svcs[e.caller].namespace != svcs[e.callee].namespace,
                "fanout": e.fanout,
                "fanout_changes": [[ts(j), v] for j, v in e.plan[1:]],
            }
            for e in f.edges
        ],
        "topics": [
            {
                "name": t.name,
                "producers": [{"service": svcs[p].name, "events_per_request": r} for p, r in t.producers],
                "mean_rate": round(result["topics"][k]["mean_rate"], 4),
                "peak_hour_rate": round(result["topics"][k]["peak_hour_rate"], 4),
                "consumers": [
                    {
                        "consumergroup": c.group,
                        "service": svcs[c.service].name,
                        "capacity_per_s": round(c.capacity, 4),
                        "trails_by_s": round(c.latency, 2),
                        "hidden": c.hidden,
                    }
                    for c in t.consumers
                ],
            }
            for k, t in enumerate(f.topics)
        ],
        "hidden_consumers": hidden,
        "outage": {
            "topic": f.outage["topic"],
            "consumergroup": f.outage["group"],
            "start": ts(f.outage["step0"]),
            "end": ts(f.outage["step1"]),
        },
        "leak_services": leaks,
        "databases": [
            {
                "service": s.name,
                "namespace": s.namespace,
                "database": s.database,
                "queries_per_request": s.db_queries_per_req,
                "pool_per_replica": 10,
            }
            for s in svcs
            if s.database
        ],
        "traffic_spikes": [
            {"namespace": ns, "start": ts(j0), "end": ts(min(j1, f.n - 1)), "factor": k}
            for ns, j0, j1, k in f.traffic_spikes
        ],
        "change_events": [{"ts": ts(ev["step"]), **{k: v for k, v in ev.items() if k != "step"}} for ev in f.events],
        "metrics": {name: {"type": m["type"], "series": len(m["series"])} for name, m in writer.metrics.items()},
        "semantics": {
            "grpc_server_handled_total": "OK + DeadlineExceeded = requests served; Unavailable = rejected when the queue is full (never served, no downstream calls).",
            "grpc_client_handled_total": "calls from `service` to `grpc_service` = fanout x requests `service` served.",
            "grpc_server_inflight_requests": "active (served rate x latency) + queued requests; the queue is a stock.",
            "kafka_consumergroup_lag": "stock: lag(t) = lag(t-1) + produced - consumed; starts at 0.",
            "counters": "start at a random uptime offset; reset to 0 at restarts (deploys and OOM kills, listed per service).",
        },
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", required=True)
    ap.add_argument("--services", type=int, default=400)
    ap.add_argument("--days", type=float, default=30)
    ap.add_argument("--step", type=int, default=300)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--end", type=int, default=None, help="last sample time (epoch s); default now")
    a = ap.parse_args(argv)
    t0 = time.time()
    truth = generate(a.out, a.services, a.days, a.step, a.seed, a.end)
    size = sum(os.path.getsize(os.path.join(a.out, x)) for x in os.listdir(a.out))
    series = sum(m["series"] for m in truth["metrics"].values())
    print(
        f"{a.out}: {len(truth['services'])} services, {series} series, {truth['n']} samples each, "
        f"{size / 1e6:.1f} MB, {time.time() - t0:.1f}s"
    )


if __name__ == "__main__":
    main()
