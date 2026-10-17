import math

import pytest
from fastapi.testclient import TestClient

from sdlab.promlab.api import Clock, create_app
from sdlab.promlab.generate import generate
from sdlab.promlab.store import Dataset

END = 1_790_000_000 // 300 * 300


@pytest.fixture(scope="module")
def data(tmp_path_factory):
    out = tmp_path_factory.mktemp("promdata")
    truth = generate(str(out), services=20, days=2, step=300, seed=7, end=END)
    ds = Dataset(str(out))
    return ds, truth, TestClient(create_app(ds))


def q(client, expr, **params):
    r = client.get("/api/v1/query", params={"query": expr, **params})
    body = r.json()
    assert r.status_code == 200, body
    assert body["status"] == "success"
    return body["data"]


def qr(client, expr, start, end, step):
    r = client.get("/api/v1/query_range", params={"query": expr, "start": start, "end": end, "step": step})
    body = r.json()
    assert r.status_code == 200, body
    return body["data"]


def value(item):
    return float(item["value"][1])


def test_truth_has_the_expected_keys(data):
    ds, truth, _ = data
    for key in (
        "start",
        "end",
        "step",
        "services",
        "edges",
        "topics",
        "hidden_consumers",
        "outage",
        "leak_services",
        "change_events",
        "databases",
        "metrics",
    ):
        assert key in truth
    assert truth["end"] == END and truth["step"] == 300 and truth["n"] == 576
    assert ds.start == truth["start"] and ds.end == END
    assert len(truth["services"]) == 20
    assert truth["hidden_consumers"] and truth["leak_services"]
    assert truth["outage"]["start"] < truth["outage"]["end"]
    assert {e["kind"] for e in truth["change_events"]} <= {"deploy", "scale"}


def test_instant_vector_has_prometheus_shape(data):
    _, truth, client = data
    d = q(client, "kube_deployment_spec_replicas")
    assert d["resultType"] == "vector"
    assert len(d["result"]) == 20
    for item in d["result"]:
        assert set(item) == {"metric", "value"}
        assert item["metric"]["__name__"] == "kube_deployment_spec_replicas"
        ts, v = item["value"]
        assert ts == END and isinstance(v, str)
    want = {s["name"]: s["replicas"][-1][1] for s in truth["services"]}
    assert {i["metric"]["deployment"]: value(i) for i in d["result"]} == want


def test_scalar_and_errors(data):
    _, _, client = data
    d = q(client, "1 + 2 * 3 ^ 2")
    assert d == {"resultType": "scalar", "result": [END, "19"]}
    for bad in ("sum(rate(x[5m])", "rate(x[5m:1m])", "foo{a=b}", "nosuchfunc(x)", ""):
        r = client.get("/api/v1/query", params={"query": bad})
        assert r.status_code == 400
        body = r.json()
        assert body["status"] == "error" and body["errorType"] == "bad_data" and body["error"]


def test_matchers(data):
    _, truth, client = data
    names = [s["name"] for s in truth["services"]]
    one = names[0]
    ns = truth["services"][0]["namespace"]
    m = "grpc_server_inflight_requests"
    assert len(q(client, f'{m}{{service="{one}"}}')["result"]) == 1
    assert len(q(client, f'{m}{{service!="{one}"}}')["result"]) == 19
    in_ns = sum(s["namespace"] == ns for s in truth["services"])
    assert len(q(client, f'{m}{{namespace=~"{ns}"}}')["result"]) == in_ns
    assert len(q(client, f'{m}{{namespace!~"{ns}|nothing"}}')["result"]) == 20 - in_ns
    assert len(q(client, f'{{__name__=~"grpc_server_.*", service="{one}"}}')["result"]) == 4
    assert len(q(client, 'grpc_server_handled_total{grpc_code="OK"}')["result"]) == 20


def test_rate_matches_the_raw_counter(data):
    ds, truth, client = data
    svc = truth["services"][-1]["name"]
    series = [
        s
        for s in ds.by_metric["grpc_server_handled_total"]
        if s.labels["service"] == svc and s.labels["grpc_code"] == "OK"
    ][0]
    raw = series.read(0, ds.n)
    for k in (ds.n - 1, ds.n - 100, 300):
        t = ds.start + k * ds.step
        a, b = raw[k - 1], raw[k]
        want = (b - a if b >= a else b) / ds.step
        got = value(
            q(client, f'rate(grpc_server_handled_total{{service="{svc}",grpc_code="OK"}}[5m])', time=t)["result"][0]
        )
        assert got == pytest.approx(want, rel=1e-6)
        # a 1h window covers 12 steps; increase extrapolates to the window
        got1h = value(
            q(client, f'increase(grpc_server_handled_total{{service="{svc}",grpc_code="OK"}}[1h])', time=t)["result"][0]
        )
        want1h = (
            sum((raw[i] - raw[i - 1]) if raw[i] >= raw[i - 1] else raw[i] for i in range(k - 10, k + 1)) * 3600 / 3300
        )
        assert got1h == pytest.approx(want1h, rel=1e-5)


def test_rates_never_go_negative_across_restarts(data):
    ds, truth, client = data
    restarted = [s["name"] for s in truth["services"] if s["restarts"]]
    assert restarted
    d = qr(client, f'rate(container_cpu_usage_seconds_total{{service="{restarted[0]}"}}[5m])', ds.start, ds.end, 300)
    vals = [float(v) for _, v in d["result"][0]["values"]]
    assert len(vals) == ds.n - 1 and min(vals) >= 0


def test_client_calls_over_served_requests_is_the_fanout(data):
    _, truth, client = data
    edge = next(e for e in truth["edges"] if not e["fanout_changes"])
    a, b = edge["caller"], edge["callee"]
    expr = (
        f'sum by (service) (rate(grpc_client_handled_total{{service="{a}",grpc_service="{b}"}}[1h]))'
        f' / sum by (service) (rate(grpc_server_handled_total{{service="{a}",grpc_code!="Unavailable"}}[1h]))'
    )
    d = q(client, expr)
    assert d["result"][0]["metric"] == {"service": a}
    assert value(d["result"][0]) == pytest.approx(edge["fanout"], rel=1e-3)


def test_sum_by_namespace(data):
    _, truth, client = data
    expr = "rate(grpc_server_handled_total[5m])"
    each = q(client, expr)["result"]
    summed = q(client, f"sum by (namespace) ({expr})")["result"]
    assert {i["metric"]["namespace"] for i in summed} == set(truth["namespaces"])
    for item in summed:
        assert set(item["metric"]) == {"namespace"}
        ns = item["metric"]["namespace"]
        assert value(item) == pytest.approx(sum(value(i) for i in each if i["metric"]["namespace"] == ns), rel=1e-9)
    total = q(client, f"sum without (namespace, service, grpc_code) ({expr})")["result"]
    assert len(total) == 1 and total[0]["metric"] == {}
    assert value(q(client, "count(kube_deployment_spec_replicas)")["result"][0]) == 20


def test_query_range_steps_are_aligned_to_start(data):
    ds, _, client = data
    start, end = ds.start + 3 * 3600 + 17, ds.start + 9 * 3600
    d = qr(client, "sum(kube_deployment_spec_replicas)", start, end, "10m")
    assert d["resultType"] == "matrix"
    (series,) = d["result"]
    assert set(series) == {"metric", "values"} and series["metric"] == {}
    ts = [t for t, _ in series["values"]]
    assert ts == [start + k * 600 for k in range(len(ts))]
    assert ts[-1] <= end < ts[-1] + 600
    assert all(isinstance(v, str) for _, v in series["values"])
    # a whole-range query on one series returns every sample
    full = qr(
        client,
        'grpc_server_inflight_requests{service="%s"}' % ds.series[0].labels.get("service", ""),
        ds.start,
        ds.end,
        300,
    )
    assert len(full["result"][0]["values"]) == ds.n


def test_hidden_consumers_have_lag_but_no_consumed_counter(data):
    _, truth, client = data
    for h in truth["hidden_consumers"]:
        sel = f'{{topic="{h["topic"]}",consumergroup="{h["consumergroup"]}"}}'
        assert len(q(client, f"kafka_consumergroup_lag{sel}")["result"]) == 1
        assert q(client, f"kafka_consumergroup_consumed_total{sel}")["result"] == []
    hidden = {(h["topic"], h["consumergroup"]) for h in truth["hidden_consumers"]}
    lags = q(client, "kafka_consumergroup_lag")["result"]
    consumed = q(client, "kafka_consumergroup_consumed_total")["result"]
    assert len(consumed) == len(lags) - len(hidden)


def test_lag_is_a_stock_of_produced_minus_consumed(data):
    _, truth, client = data
    topic = next(t for t in truth["topics"] if len(t["consumers"]) == 1 and not t["consumers"][0]["hidden"])
    sel = f'{{topic="{topic["name"]}"}}'
    expr = (
        f"sum by (topic) (increase(kafka_topic_messages_in_total{sel}[5m]))"
        f" - sum by (topic) (increase(kafka_consumergroup_consumed_total{sel}[5m]))"
        f" - sum by (topic) (delta(kafka_consumergroup_lag{sel}[5m]))"
    )
    lag = value(q(client, f"max(kafka_consumergroup_lag{sel})")["result"][0])
    produced = value(q(client, f"sum(increase(kafka_topic_messages_in_total{sel}[5m]))")["result"][0])
    assert abs(value(q(client, expr)["result"][0])) <= 1e-3 * max(1.0, lag, produced)


def test_metadata_and_discovery_endpoints(data):
    _, truth, client = data
    names = client.get("/api/v1/label/__name__/values").json()["data"]
    assert set(names) == set(truth["metrics"])
    labels = client.get("/api/v1/labels").json()["data"]
    assert {
        "namespace",
        "service",
        "grpc_code",
        "grpc_service",
        "topic",
        "consumergroup",
        "database",
        "deployment",
    } <= set(labels)
    services = client.get("/api/v1/label/service/values", params={"match[]": "grpc_server_inflight_requests"}).json()[
        "data"
    ]
    assert sorted(services) == sorted(s["name"] for s in truth["services"])
    series = client.get("/api/v1/series", params={"match[]": "kafka_consumergroup_lag"}).json()
    assert series["status"] == "success" and all(s["__name__"] == "kafka_consumergroup_lag" for s in series["data"])
    assert client.get("/api/v1/series").status_code == 400
    meta = client.get("/api/v1/metadata").json()["data"]
    assert meta["grpc_server_handled_total"][0]["type"] == "counter"
    assert meta["kafka_consumergroup_lag"][0]["type"] == "gauge"


def test_post_form_and_offset(data):
    ds, _, client = data
    r = client.post(
        "/api/v1/query", data={"query": "sum(kube_deployment_spec_replicas offset 1h)", "time": str(ds.end)}
    )
    assert r.status_code == 200 and r.json()["data"]["resultType"] == "vector"
    r = client.post("/api/v1/query_range", data={"query": "up", "start": ds.start, "end": ds.end, "step": "1h"})
    assert r.json() == {"status": "success", "data": {"resultType": "matrix", "result": []}}


def test_replay_clock_hides_the_future(data):
    ds, _, _ = data
    clock = Clock(ds, "replay", replay_from=1, speed=0)
    client = TestClient(create_app(ds, clock))
    now = ds.end - 86400
    d = q(client, "kube_deployment_spec_replicas")
    assert d["result"][0]["value"][0] == now
    late = qr(client, "sum(kube_deployment_spec_replicas)", ds.start, ds.end, 300)
    # like Prometheus, the last sample stays visible for the 5m lookback after it
    assert late["result"][0]["values"][-1][0] == now + 300
    raw = client.get("/api/v1/query", params={"query": "kube_deployment_spec_replicas[1h]", "time": now + 1800}).json()
    assert raw["data"]["resultType"] == "matrix"
    assert max(t for t, _ in raw["data"]["result"][0]["values"]) == now
    assert math.isclose(clock.now(), now)


def test_replay_clock_starts_over_at_the_end_so_live_runs_keep_moving(data, monkeypatch):
    ds, _, _ = data
    clock = Clock(ds, "replay", replay_from=1, speed=3600)          # an hour of data per second
    import sdlab.promlab.api as api
    monkeypatch.setattr(api.time, "time", lambda: clock.wall0 + 30)   # 30 hours in: past the end
    assert math.isclose(clock.now(), ds.end - 86400 + 6 * 3600)       # started over 6 hours ago
    still = Clock(ds, "replay", replay_from=1, speed=3600, loop=False)
    monkeypatch.setattr(api.time, "time", lambda: still.wall0 + 30)
    assert still.now() == ds.end
