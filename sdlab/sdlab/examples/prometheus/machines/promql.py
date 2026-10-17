"""Measure a model from Prometheus: a PromQL client for SD Lab sensors and history.

Each stock in the model may carry a `query` whose value is the stock's level (a gauge such as
`sum(kafka_consumergroup_lag{topic="orders"})`). Each flow may carry a `query` whose value is its
rate per second (`sum(rate(kafka_topic_messages_in_total{topic="orders"}[5m]))`); the amount per
step is that rate times the model's `step_seconds`. The model may carry an `era_query` (for example
`kube_deployment_spec_replicas{namespace="orders"}`): every step where one of its series changes
value starts an era, labelled with what changed.

The runner gives this program the model's stocks and flows on stdin. Point it at a server with
SDLAB_PROM_URL (default http://127.0.0.1:9090); it only uses the standard HTTP API
(/api/v1/query and /api/v1/query_range), so a real Prometheus works the same way.

    promql.py                    print the current levels and flow amounts, as a sensor
    promql.py history [--days 7] print one line per step for the last N days, as history
"""

import argparse
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

URL = os.environ.get("SDLAB_PROM_URL", "http://127.0.0.1:9090").rstrip("/")


def api(path, **params):
    url = f"{URL}{path}?{urllib.parse.urlencode(params)}"
    with urllib.request.urlopen(url, timeout=120) as r:
        body = json.load(r)
    if body.get("status") != "success":
        raise RuntimeError(f"{body.get('errorType')}: {body.get('error')} ({params.get('query')})")
    return body["data"]


def now(probe=None):
    """The server's evaluation time: an instant query with no time is evaluated at the server's
    "now", which a stand-in server may set in the past. Falls back to this machine's clock."""
    for q in ["time()", probe]:
        if not q:
            continue
        try:
            data = api("/api/v1/query", query=q)
            if data.get("resultType") == "scalar":
                return float(data["result"][0])
            if data.get("result"):
                return float(data["result"][0]["value"][0])
        except Exception:
            pass
    return time.time()


def instant(query, at):
    data = api("/api/v1/query", query=query, time=at)
    if data["resultType"] == "scalar":
        return float(data["result"][1])
    vals = [float(r["value"][1]) for r in data["result"]]
    return sum(vals) if vals else None                     # several series: their sum is the stock


def ranged(query, start, end, step):
    """{timestamp: value} summed over the series a query returns."""
    data = api("/api/v1/query_range", query=query, start=start, end=end, step=step)
    out = {}
    for r in data["result"]:
        for ts, v in r["values"]:
            out[float(ts)] = out.get(float(ts), 0.0) + float(v)
    return out


def ranged_series(query, start, end, step):
    """The individual series a query returns, as (labels, {timestamp: value})."""
    data = api("/api/v1/query_range", query=query, start=start, end=end, step=step)
    return [(r["metric"], {float(ts): float(v) for ts, v in r["values"]}) for r in data["result"]]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", nargs="?", default="sensor", choices=["sensor", "history"])
    ap.add_argument("--days", type=float, default=7)
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args()
    job = json.load(sys.stdin)
    model = job.get("model") or {}
    step = float(model.get("step_seconds") or 300)
    stocks = [s for s in job.get("stocks", []) if s.get("query")]
    flows = [f for f in job.get("flows", []) if f.get("query")]
    end = now(stocks[0]["query"] if stocks else None)
    end -= end % step

    if args.mode == "sensor":
        at = now(stocks[0]["query"] if stocks else None)     # the latest sample, not the step boundary
        with ThreadPoolExecutor(args.workers) as pool:
            lv = dict(zip([s["id"] for s in stocks], pool.map(lambda s: instant(s["query"], at), stocks)))
            fl = dict(zip([f["id"] for f in flows], pool.map(lambda f: instant(f["query"], at), flows)))
        print(json.dumps({"levels": lv, "flows": {k: (v * step if v is not None else None) for k, v in fl.items()}}))
        return

    start = end - args.days * 86400
    with ThreadPoolExecutor(args.workers) as pool:
        lv = dict(zip([s["id"] for s in stocks], pool.map(lambda s: ranged(s["query"], start, end, step), stocks)))
        fl = dict(zip([f["id"] for f in flows], pool.map(lambda f: ranged(f["query"], start, end, step), flows)))
    eras = {}
    if model.get("era_query"):
        last = {}
        for labels, values in ranged_series(model["era_query"], start, end, step):
            name = labels.get("deployment") or labels.get("service") or ",".join(f"{k}={v}" for k, v in labels.items() if k != "__name__")
            prev = None
            for ts in sorted(values):
                v = values[ts]
                if prev is not None and v != prev:
                    eras.setdefault(ts, []).append(f"{name} {prev:g} → {v:g}")
                prev = v
            last[name] = prev
    times = sorted({ts for series in lv.values() for ts in series} | {ts for series in fl.values() for ts in series})
    for i, ts in enumerate(times, start=1):
        rec = {"t": i, "time": ts,
               "levels": {sid: round(series.get(ts, 0.0), 4) for sid, series in lv.items()},
               "flows": {fid: round(series.get(ts, 0.0) * step, 4) for fid, series in fl.items()}}
        if ts in eras:
            rec["era"] = "; ".join(eras[ts])
        print(json.dumps(rec))


if __name__ == "__main__":
    main()
