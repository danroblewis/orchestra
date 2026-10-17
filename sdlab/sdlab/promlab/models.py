"""Build SD Lab models from what a Prometheus server exports.

Only the HTTP API is used (series listings and instant queries), never the generator's truth, so
the same tool works against a real Prometheus. Stocks are gauges (in-flight requests, consumer lag);
flows are counters read as rates (requests handled, calls received, messages produced and consumed).
A consumer whose consumed counter is not exported gets no flow, exactly as it would in real life:
that is what "Discover flows" should find.

    python -m sdlab.promlab.models --prom http://127.0.0.1:9090 --out sdlab/examples
"""

from __future__ import annotations

import argparse
import json
import re
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path

STEP = 300


def api(base: str, path: str, **params) -> dict:
    q = urllib.parse.urlencode(params, doseq=True)
    with urllib.request.urlopen(f"{base}{path}?{q}", timeout=120) as r:
        body = json.load(r)
    if body.get("status") != "success":
        raise RuntimeError(body)
    return body["data"]


def series(base: str, match: str) -> list[dict]:
    return api(base, "/api/v1/series", **{"match[]": match})


def instant_by(base: str, query: str, label: str) -> dict[str, float]:
    return {r["metric"].get(label, ""): float(r["value"][1]) for r in api(base, "/api/v1/query", query=query)["result"]}


def slug(*parts: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", "_".join(parts).lower()).strip("_")
    return ("x_" + s if not s[:1].isalpha() else s)[:64]


def kafka_part(base: str, x0: float, y0: float):
    """Consumer lag stocks, fed by the topic's produced messages and drained by the group's consumption."""
    lags = sorted((s["topic"], s["consumergroup"]) for s in series(base, "kafka_consumergroup_lag"))
    consumed = {(s["topic"], s["consumergroup"]) for s in series(base, "kafka_consumergroup_consumed_total")}
    produced = instant_by(base, "sum by (topic) (rate(kafka_topic_messages_in_total[1h]))", "topic")
    eaten = {}
    for r in api(base, "/api/v1/query", query="sum by (topic, consumergroup) (rate(kafka_consumergroup_consumed_total[1h]))")["result"]:
        eaten[(r["metric"]["topic"], r["metric"]["consumergroup"])] = float(r["value"][1])
    stocks, flows = [], []
    by_topic = defaultdict(list)
    for topic, group in lags:
        by_topic[topic].append(group)
    for row, topic in enumerate(sorted(by_topic)):
        for col, group in enumerate(by_topic[topic]):
            sid = slug("lag", topic, group)
            stocks.append({"id": sid, "name": f"{topic} → {group}", "unit": "messages", "initial": 0, "group": f"{topic}/{group}",
                           "x": x0 + col * 230, "y": y0 + row * 120,
                           "query": f'sum(kafka_consumergroup_lag{{topic="{topic}",consumergroup="{group}"}})'})
            flows.append({"id": slug("produced", topic, group), "name": f"{topic} produced", "from": None, "to": sid,
                          "cloud": {"x": x0 + col * 230 - 60, "y": y0 + row * 120 - 30},
                          "rate": {"form": "constant", "value": round(produced.get(topic, 0) * STEP, 2)}, "machine": "environment",
                          "query": f'sum(rate(kafka_topic_messages_in_total{{topic="{topic}"}}[5m]))'})
            if (topic, group) in consumed:
                flows.append({"id": slug("consumed", topic, group), "name": f"{group} consumes", "from": sid, "to": None,
                              "cloud": {"x": x0 + col * 230 + 210, "y": y0 + row * 120 + 70},
                              "rate": {"form": "constant", "value": round(eaten.get((topic, group), 0) * STEP, 2)}, "machine": "environment",
                              "query": f'sum(rate(kafka_consumergroup_consumed_total{{topic="{topic}",consumergroup="{group}"}}[5m]))'})
    return stocks, flows


def fleet_part(base: str, x0: float, y0: float):
    """In-flight requests per service: calls from other services flow in, handled requests flow out."""
    services = sorted({(s["namespace"], s["service"]) for s in series(base, "grpc_server_inflight_requests")})
    called = {s["grpc_service"] for s in series(base, "grpc_client_handled_total")}
    calls_in = instant_by(base, "sum by (grpc_service) (rate(grpc_client_handled_total[1h]))", "grpc_service")
    stocks, flows = [], []
    by_ns = defaultdict(list)
    for ns, svc in services:
        by_ns[ns].append(svc)
    for col, ns in enumerate(sorted(by_ns)):
        for row, svc in enumerate(by_ns[ns]):
            sid = slug("inflight", svc)
            x, y = x0 + col * 260, y0 + row * 110
            stocks.append({"id": sid, "name": f"{svc} in flight", "unit": "requests", "initial": 0, "x": x, "y": y, "group": f"{ns}/{svc}",
                           "query": f'sum(grpc_server_inflight_requests{{service="{svc}"}})'})
            if svc in called:
                flows.append({"id": slug("called", svc), "name": f"calls to {svc}", "from": None, "to": sid,
                              "cloud": {"x": x - 50, "y": y - 30},
                              "rate": {"form": "constant", "value": round(calls_in.get(svc, 0) * STEP, 1)}, "machine": "environment",
                              "query": f'sum(rate(grpc_client_handled_total{{grpc_service="{svc}"}}[5m]))'})
            flows.append({"id": slug("handled", svc), "name": f"{svc} handles", "from": sid, "to": None,
                          "cloud": {"x": x + 200, "y": y + 70},
                          "rate": {"form": "proportional", "stock": sid, "k": 1}, "machine": "environment",
                          "query": f'sum(rate(grpc_server_handled_total{{service="{svc}"}}[5m]))'})
    return stocks, flows


def model(mid: str, name: str, description: str, stocks: list, flows: list, days: float, era_query: str | None) -> dict:
    m = {"id": mid, "name": name, "description": description, "time_unit": "5-minute step", "step_seconds": STEP,
         "horizon": 288, "dt": 0.25, "stocks": stocks, "flows": flows, "machines": [],
         "sensors": [{"program": "prometheus/promql"}],
         "history": {"program": "prometheus/promql", "args": ["history", "--days", str(days)]}}
    if era_query:
        m["era_query"] = era_query
    return m


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--prom", default="http://127.0.0.1:9090")
    ap.add_argument("--out", default="sdlab/examples")
    a = ap.parse_args()
    out = Path(a.out)
    ks, kf = kafka_part(a.prom, 120, 120)
    kafka = model("k8s-kafka", "Kafka consumer lag (Prometheus)",
                  "Every consumer group's lag as a stock, read from Prometheus with PromQL. Produced messages flow in and "
                  "each group's consumption flows out, both measured. Some groups don't export a consumed counter; "
                  "select their lag stocks and use Discover flows to find their consumption. Import history loads 29 days.",
                  ks, kf, 29, None)
    fs, ff = fleet_part(a.prom, 120, 120)
    ks2, kf2 = kafka_part(a.prom, 120 + 21 * 260, 120)
    fleet = model("k8s-fleet", "Fleet: 400 gRPC services (Prometheus)",
                  "The stress model: in-flight requests for every service and lag for every consumer group, from Prometheus. "
                  "Calls between services flow in, handled requests flow out; each replica change starts an era. "
                  "With this many stocks, select a team's services (search the namespace) before charting, fitting or discovering. "
                  "Import history loads 7 days.",
                  fs + ks2, ff + kf2, 7, "kube_deployment_spec_replicas")
    for m in (kafka, fleet):
        (out / f"{m['id']}.json").write_text(json.dumps(m, indent=1))
        print(f"{m['id']}: {len(m['stocks'])} stocks, {len(m['flows'])} flows")


if __name__ == "__main__":
    main()
