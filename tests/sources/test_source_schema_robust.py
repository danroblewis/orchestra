"""What a family is, decided robustly: a read that fails never changes a type (the last round's
stands, or the family is unknown and left out); a type is judged over a long history and changes
only when the samples decide; a native histogram is read by its count; a unit label is never
summed across; one missed scrape never dips a sum; two jobs are one only when they scrape the same
targets; a rule over a counter gives way to the counter."""

from __future__ import annotations

import math
import time
from pathlib import Path

import pytest
from fake_prometheus import Busy, FakePrometheus

from orchestra.sources.fetch import read as read_definition
from orchestra.sources.infer import infer
from orchestra.sources.prometheus import PrometheusSource
from orchestra.sources.schema import read
from orchestra.sources.spec import load
from orchestra.sources.survey import known_record
from orchestra.sources.views import views

NOW = math.floor(time.time() / 60) * 60
T0 = NOW - 3600


def every(seconds, fn, start=T0, end=NOW, skip=()):
    out, t = [], start
    while t <= end:
        if t - start not in skip:
            out.append((t, float(fn(t - start))))
        t += seconds
    return out


@pytest.fixture
def store(tmp_path):
    made = []

    def make(dump, meta=None, **kw):
        f = FakePrometheus(dump)
        f.meta = meta or {}
        made.append(f)
        specs = load({"sources": [{"name": "lab", "url": f.url, **kw}]}, tmp_path)
        assert not specs.refused, specs.refused
        src = PrometheusSource(specs.sources[0])
        src._sleep = lambda s: None
        src.limiter.hold = lambda s: None
        return f, src, specs.sources[0]
    yield make
    for f in made:
        f.close()


def fams(src, spec, start=T0, known=None):
    return {f.name: f for f in read(src, spec, start, NOW, known=known).families}


OFFSETS = [("kafka_topic_partition_current_offset", {"topic": t, "partition": str(p)}, every(30, lambda s, k=k: 10_000 + k * s // 2))
           for t, k in (("orders", 3), ("clickstream", 40)) for p in range(2)]
GAUGE = {"kafka_topic_partition_current_offset": [{"type": "gauge", "help": "Current Offset of a Broker at Topic/Partition"}]}


def test_a_failed_read_keeps_the_last_type_or_leaves_the_family_out(store):
    f, src, spec = store(OFFSETS + [("queue_depth", {"q": "a"}, every(15, lambda s: (s // 15) % 9))], GAUGE)
    first = fams(src, spec)
    assert first["kafka_topic_partition_current_offset"].kind == "counter"
    answer = f.answer

    def raw_busy(endpoint, form):                       # its raw samples stay busy past the retries
        if endpoint == "query" and "kafka_topic" in (form.get("query") or [""])[0]:
            raise Busy()
        return answer(endpoint, form)
    f.answer = raw_busy
    known = {n: known_record(fam) for n, fam in first.items()}
    again = fams(src, spec, known=known)["kafka_topic_partition_current_offset"]
    assert again.kind == "counter" and again.resolution_s == 30.0           # never back to the store's gauge
    assert any("kept as the last round found it" in n for n in again.notes)
    fresh = fams(src, spec)["kafka_topic_partition_current_offset"]
    assert fresh.kind == "unknown" and "not guessed" in fresh.retyped
    assert not views(fresh, spec)                                            # unknown: read as neither level nor flow


def test_a_type_is_judged_over_the_history_not_the_window(store):
    """A counter that resets once a day only rose in the window; a retry set named for events only
    grew in this (incident) hour, and drains the rest of the day."""
    day = 86400
    since_reset = every(300, lambda s: (s - 0.4 * day) * 2 if s > 0.4 * day else 7000 + s, start=NOW - day)
    retries = every(300, lambda s: 50 + 40 * math.sin(s / 7000) + (s - (day - 3600)) / 10 if s > day - 3600 else 50 + 40 * math.sin(s / 7000),
                    start=NOW - day)
    fine = lambda pts: [(t, v) for t, v in pts if t < T0] + every(15, lambda s, a=pts[-13][1]: a + s / 3)
    f, src, spec = store([("shop_orders_since_reset", {}, fine(since_reset)), ("sidekiq_retries", {}, fine(retries))])
    window_only = fams(src, load({"sources": [{"name": "lab", "url": f.url, "history": "1h"}]}, Path(".")).sources[0])
    assert window_only["sidekiq_retries"].kind == "counter"                  # the name's tie-break, on an hour that only rose
    got = fams(src, spec)
    assert got["shop_orders_since_reset"].kind == "counter" and "over the last 24 h" in got["shop_orders_since_reset"].retyped
    assert got["sidekiq_retries"].kind == "gauge"


def test_a_judged_type_changes_only_when_the_samples_decide(store):
    f, src, spec = store([("sidekiq_retries", {}, every(15, lambda s: 100 + s / 3))], history="1h")
    known = {"sidekiq_retries": {"kind": "gauge", "resolution_s": 15.0, "labels": {}}}
    got = fams(src, spec, known=known)["sidekiq_retries"]
    assert got.kind == "gauge" and any("do not decide" in n for n in got.notes)
    f.dump = [("sidekiq_retries", {}, every(15, lambda s: 100 + (s % 900) / 3))]   # reset to near zero, otherwise only rose
    assert fams(src, spec, known=known)["sidekiq_retries"].kind == "counter"


def test_a_native_histogram_is_read_by_its_count(store):
    dump = [("rpc_duration_seconds", {"service": s}, every(15, lambda t, k=k: k * t / 15)) for k, s in ((2, "a"), (3, "b"))]
    f, src, spec = store(dump, {"rpc_duration_seconds": [{"type": "histogram", "help": "RPC latency"}]})
    f.native = {"rpc_duration_seconds"}
    assert src.select("rpc_duration_seconds", T0, NOW)[0][1][-1][1] > 0     # a histogram sample read as its count
    fam = fams(src, spec)["rpc_duration_seconds"]
    assert fam.kind == "counter" and fam.counter_form == "native"
    total = next(d for d in views(fam, spec) if d.view == "increments" and not d.group_by)
    total.id = "n"
    (_, _, pts, _), = read_definition(src, total, "lab", None, T0 + 600, NOW, 60.0)
    assert "histogram_count(increase(rpc_duration_seconds[60s]))" in f.queries[-1]
    assert pts[-1][1] == pytest.approx(5 * (NOW - T0 - 600) / 15)


def test_cpu_and_memory_are_never_summed_together(store):
    dump = [("kube_pod_container_resource_requests", {"pod": f"p{i}", "resource": r, "unit": u}, every(30, lambda s, v=v: v))
            for i in range(3) for r, u, v in (("cpu", "core", 0.5), ("memory", "byte", 2**30))]
    _, src, spec = store(dump)
    fam = fams(src, spec)["kube_pod_container_resource_requests"]
    assert fam.labels["resource"].role == "unit" and fam.labels["unit"].role == "unit"
    sums = [d for d in views(fam, spec) if d.view == "sum_by"]
    assert sums and all({"resource", "unit"} <= set(d.by_real) for d in sums) and all(d.unit_label for d in sums)
    counts = [d for d in views(fam, spec) if d.view == "count"]
    assert counts and all("resource" not in d.by_real for d in counts)     # pods are counted once, not once per unit


def test_one_missed_scrape_never_dips_a_sum(store):
    dump = [("frontend_sessions_active", {"pod": f"p{i}"}, every(15, lambda s: 100.0, skip=(1200 + 15 * i,))) for i in range(4)]
    _, src, spec = store(dump)
    fam = fams(src, spec)["frontend_sessions_active"]
    total = next(d for d in views(fam, spec) if d.view == "sum_by" and not d.group_by)
    total.id = "s"
    assert "[46s]" in total.query                                   # 2.5 intervals of 15 s, and more than one interval plus 30 s
    (_, _, pts, _), = read_definition(src, total, "lab", None, T0 + 600, NOW, 15.0)
    assert {v for _, v in pts} == {400.0}


NODES = {"10.0.1.1": 7e12, "10.0.1.2": 5e12}


def test_two_jobs_are_one_only_when_they_scrape_the_same_targets(store):
    same = [("node_network_receive_bytes_total", {"job": "node-exporter", "instance": f"{ip}:9100", "device": "eth0"},
             every(15, lambda s, v=v: v + 1e6 * s)) for ip, v in NODES.items()]
    same += [("node_network_receive_bytes_total", {"job": "integrations/node_exporter", "device": "eth0",
                                                   "instance": f"ip-{ip.replace('.', '-')}.eu-west-1.compute.internal"},
              every(15, lambda s, v=v: v + 1e6 * s, start=T0 + 4)) for ip, v in NODES.items()]
    f, src, spec = store(same)
    fam = fams(src, spec)["node_network_receive_bytes_total"]
    assert fam.where == {"job": "integrations/node_exporter"} and any("target for target" in n for n in fam.notes)
    # a half-migrated fleet: other nodes under the other job, with totals alike and rates 2-3 times apart
    other = [("node_network_receive_bytes_total", {"job": "node-exporter", "instance": f"{ip}:9100", "device": "eth0"},
              every(15, lambda s, v=v: v + 1e6 * s)) for ip, v in NODES.items()]
    other += [("node_network_receive_bytes_total", {"job": "integrations/node_exporter", "device": "eth0", "instance": f"10.0.2.{i}:9100"},
               every(15, lambda s, v=v, i=i: v + (2.5e6 if i else 3e6) * s)) for i, v in enumerate(NODES.values())]
    f.dump = other
    assert fams(src, spec)["node_network_receive_bytes_total"].where == {}


def test_a_rate_rule_and_its_counter_are_one_flow(store, tmp_path):
    dump = [("http_requests_total", {"pod": p, "job": "frontend"}, every(15, lambda s: 5 * s)) for p in ("a", "b")]
    dump += [("job:http_requests:rate5m", {"job": "frontend"}, every(60, lambda s: 10.0, start=T0 + 7))]
    _, src, spec = store(dump)
    inf = infer(src, spec, [], tmp_path, T0, NOW)
    assert any(d.view == "increments" and d.family == "http_requests_total" for d in inf.kept)
    rule = [d for d in inf.left_out if d.view == "rollup"]
    assert rule and all("the same events as its counter http_requests_total" in d.why for d in rule)
    assert not any(d.view == "rollup" for d in inf.kept)


def test_units_come_from_the_metadata_or_the_name(store):
    dump = [("node_memory_MemFree_bytes", {}, every(15, lambda s: 1e9 - s)), ("process_cpu_seconds_total", {}, every(15, lambda s: s)),
            ("queue_depth", {}, every(15, lambda s: s % 7))]
    _, src, spec = store(dump, {"queue_depth": [{"type": "gauge", "unit": "messages", "help": ""}]})
    got = fams(src, spec)
    assert (got["node_memory_MemFree_bytes"].unit, got["process_cpu_seconds_total"].unit, got["queue_depth"].unit) == \
        ("bytes", "seconds", "messages")
