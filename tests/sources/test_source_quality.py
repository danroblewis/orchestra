"""Reading a messy store's schema well: summaries typed under their base name, recording rules on
their own clock, names that say one thing and data another, counters typed gauges, colliding
names, timestamps and info metrics, per-object labels, duplicate scrape jobs, what a total merges,
and the same pods counted twice. Against the fake, with small payloads shaped like a real
store's (VictoriaMetrics over kube-prometheus, kafka_exporter, Micrometer)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fake_prometheus import FakePrometheus

from orchestra.sources.fetch import read as read_definition
from orchestra.sources.infer import infer
from orchestra.sources.prometheus import PrometheusSource
from orchestra.sources.schema import read
from orchestra.sources.spec import load
from orchestra.sources.views import views

T0 = 1_793_000_000.0
END = T0 + 3600


def every(seconds: float, fn, *, start: float = T0, end: float = END, offset: float = 0.0):
    t, out = start + offset, []
    while t <= end:
        out.append((t, float(fn(t - start))))
        t += seconds
    return out


def spec_for(url: str, tmp_path: Path, **kw):
    specs = load({"sources": [{"name": "lab", "url": url, **kw}]}, tmp_path)
    assert not specs.refused, specs.refused
    return specs.sources[0]


@pytest.fixture
def store(tmp_path):
    made = []

    def make(dump, meta=None, **kw):
        f = FakePrometheus(dump)
        f.meta = meta or {}
        made.append(f)
        spec = spec_for(f.url, tmp_path, **kw)
        return PrometheusSource(spec), spec
    yield make
    for f in made:
        f.close()


def families(src, spec):
    return {f.name: f for f in read(src, spec, T0, END).families}


def test_a_summary_typed_under_its_base_name_is_counted_not_levelled(store):
    """VictoriaMetrics keeps Micrometer's summary type under ``jvm_gc_pause_seconds`` only."""
    pods = ("a", "b")
    dump = [(f"jvm_gc_pause_seconds_{part}", {"pod": p, "action": "end of minor GC"}, every(15, lambda s, k=k: k * s / 30))
            for part, k in (("count", 1), ("sum", 0.01)) for p in pods]
    dump += [("jvm_gc_pause_seconds_max", {"pod": p, "action": "end of minor GC"}, every(15, lambda s: 0.02 + (s % 90) / 1e4)) for p in pods]
    dump += [("go_gc_duration_seconds", {"pod": "c", "quantile": q}, every(15, lambda s: 1e-4)) for q in ("0.5", "1")]
    dump += [(f"go_gc_duration_seconds_{part}", {"pod": "c"}, every(15, lambda s: s / 10)) for part in ("count", "sum")]
    src, spec = store(dump, {"jvm_gc_pause_seconds": [{"type": "summary", "help": "Time spent in GC pause"}],
                             "jvm_gc_pause_seconds_max": [{"type": "gauge", "help": ""}]})
    fams = families(src, spec)
    assert fams["jvm_gc_pause_seconds_count"].kind == "counter"
    assert fams["go_gc_duration_seconds_count"].kind == "counter"        # no metadata at all: _count beside _sum
    assert not any(n.endswith("_sum") for n in fams)
    names = {d.name for f in fams.values() for d in views(f, spec)}
    assert not any("_count_max" in n or "_sum_max" in n for n in names)


def test_a_recording_rule_is_read_on_its_own_interval(store):
    """Rules are evaluated every 60 s; their base is scraped every 15 s."""
    dump = [("http_requests_total", {"pod": p, "job": "frontend"}, every(15, lambda s: 5 * s)) for p in ("a", "b")]
    dump += [("job:http_requests:rate5m", {"job": "frontend"}, every(60, lambda s: 10.0, offset=7))]
    src, spec = store(dump)
    fam = families(src, spec)["http_requests_total"]
    assert fam.resolution_s == 15.0 and fam.rollups["rate"]["resolution_s"] == 60.0
    rule = next(d for d in views(fam, spec) if d.view == "rollup")
    assert "[151s]" in rule.query and rule.resolution_s == 60.0
    got = read_definition(src, rule, "lab", None, T0 + 600, END - 60, 30.0)
    (_, _, pts, _), = got
    assert len(pts) == len(range(int(T0 + 600), int(END - 60) + 1, 60))   # on its own 60 s grid, a value at every step


def test_a_rule_named_a_rate_of_a_utilisation_is_a_gauge(store):
    dump = [("instance:node_cpu_utilisation:rate5m", {"instance": f"10.0.0.{i}:9100"}, every(60, lambda s: 0.3 + (s % 600) / 3000))
            for i in range(3)]
    dump += [("service:grpc_server_handling_seconds:histogram_quantile", {"app": "checkout", "quantile": q},
              every(60, lambda s, q=q: float(q) * (1 + (s % 300) / 300))) for q in ("0.5", "0.99")]
    src, spec = store(dump)
    fams = families(src, spec)
    util = fams["instance:node_cpu_utilisation:rate5m"]
    assert util.kind == "gauge" and not util.rollups
    defs = views(util, spec)
    assert {d.view for d in defs} >= {"max_by", "avg_by"} and not any(d.kind == "rate" for d in defs)
    q = fams["service:grpc_server_handling_seconds:histogram_quantile"]
    assert q.stat_label == "quantile" and q.stats == ["p50", "p99"]
    assert not any(d.view == "sum_by" for d in views(q, spec))           # never a sum of quantiles


def test_kafka_offsets_typed_gauges_are_counters_and_a_growing_disk_stays_a_gauge(store):
    meta = {n: [{"type": "gauge", "help": h}] for n, h in (("kafka_topic_partition_current_offset", "Current Offset of a Broker at Topic/Partition"),
                                                         ("kubelet_volume_stats_used_bytes", "Number of used bytes in the volume"))}
    dump = [("kafka_topic_partition_current_offset", {"topic": t, "partition": str(p)}, every(30, lambda s, k=k: 10_000 + k * s // 2))
            for t, k in (("orders", 3), ("clickstream", 40)) for p in range(2)]
    dump += [("kubelet_volume_stats_used_bytes", {"persistentvolumeclaim": "data-kafka-0"}, every(15, lambda s: 2**31 + 1100 * s))]
    src, spec = store(dump, meta)
    fams = families(src, spec)
    offsets, disk = fams["kafka_topic_partition_current_offset"], fams["kubelet_volume_stats_used_bytes"]
    assert offsets.kind == "counter" and "typed gauge" in offsets.retyped
    assert disk.kind == "gauge" and disk.retyped is None
    offs = views(offsets, spec)
    assert {d.view for d in offs} - {"distinct"} == {"increments"} and any(d.group_by == ["topic"] for d in offs)
    assert any("typed gauge" in o for d in offs for o in d.origin)


def test_timestamps_info_metrics_and_scrapes_are_no_levels(store):
    created = {f"p{i}": 1_792_762_671.0 + 3600 * i for i in range(3)}
    dump = [("kube_pod_created", {"pod": p, "uid": f"{i:08x}-4de6-4343-8bda-4782790966c9"}, every(30, lambda s, v=v: v))
            for i, (p, v) in enumerate(created.items())]
    dump += [("kube_pod_info", {"pod": p, "node": "n1", "host_ip": "10.0.0.1"}, every(30, lambda s: 1.0)) for p in created]
    dump += [("process_uptime_seconds", {"pod": p}, every(15, lambda s, i=i: 600 * i + s)) for i, p in enumerate(created)]
    dump += [("up", {"job": j, "instance": "x"}, every(15, lambda s: 1.0 if s % 600 else 0.0)) for j in ("a", "b")]
    src, spec = store(dump, {"kube_pod_created": [{"type": "gauge", "help": "Unix creation timestamp"}]})
    fams = families(src, spec)
    assert fams["kube_pod_created"].kind == "timestamp" and not views(fams["kube_pod_created"], spec)
    assert fams["process_uptime_seconds"].kind == "clock" and not views(fams["process_uptime_seconds"], spec)
    assert fams["up"].kind == "scrape" and not views(fams["up"], spec)
    info = views(fams["kube_pod_info"], spec)
    assert fams["kube_pod_info"].kind == "info" and info and not any(d.view == "sum_by" for d in info)


def test_labels_that_name_one_object_never_group(store):
    """A pod's uid, a container's image, an internal IP: per object, never a grouping."""
    dump = [("container_memory_rss", {"namespace": ns, "uid": f"{i:08x}-4de6-4343-8bda-4782790966c9",
                                      "image": f"registry/app:v1.{i % 2}", "internal_ip": f"10.0.{i}.7", "cpu_arch": "arm64" if i % 2 else "amd64"},
              every(15, lambda s, i=i: 1e8 * (1 + i) + s)) for i, ns in enumerate(("shop", "shop", "kafka", "kafka"))]
    src, spec = store(dump, identity=["pod"])
    fam = families(src, spec)["container_memory_rss"]
    roles = {c: i.role for c, i in fam.labels.items()}
    assert roles["uid"] == roles["image"] == roles["internal_ip"] == "identity"
    assert roles["namespace"] == roles["cpu_arch"] == "grouping"


def test_a_duplicate_scrape_job_is_read_once(store):
    """node_exporter under two jobs, each labelling the node its own way."""
    nodes = {"10.0.1.1": 7e10, "10.0.1.2": 5e10}
    dump = [("node_filesystem_avail_bytes", {"job": "node-exporter", "instance": f"{ip}:9100", "mountpoint": "/"},
             every(15, lambda s, v=v: v - 1e5 * s)) for ip, v in nodes.items()]
    dump += [("node_filesystem_avail_bytes", {"job": "integrations/node_exporter", "instance": f"ip-{ip}", "agent_hostname": f"ip-{ip}",
                                              "mountpoint": "/"}, every(15, lambda s, v=v: v - 1e5 * s, offset=4)) for ip, v in nodes.items()]
    src, spec = store(dump)
    fam = families(src, spec)["node_filesystem_avail_bytes"]
    assert fam.where == {"job": "integrations/node_exporter"} and fam.labels["job"].role == "constant"   # the first by name
    assert any("only repeats" in n for n in fam.notes)
    total = next(d for d in views(fam, spec) if d.view == "sum_by" and not d.group_by)
    assert 'job="integrations/node_exporter"' in total.query
    (_, _, pts, _), = read_definition(src, total, "lab", None, T0 + 600, T0 + 900, 60.0)
    assert pts[0][1] == pytest.approx(sum(nodes.values()) - 2e5 * 600, rel=1e-3)        # once, not twice


def test_two_nodes_that_agree_are_two_nodes(store):
    """Equal series under a label that is not the collection's are two things that agree."""
    dump = [("kube_node_status_capacity", {"node": n, "resource": r}, every(30, lambda s, v=v: v))
            for n in ("n1", "n2") for r, v in (("cpu", 4), ("memory", 16e9))]
    src, spec = store(dump)
    assert families(src, spec)["kube_node_status_capacity"].where == {}


def test_every_definition_says_what_it_merges(store):
    dump = [("rabbitmq_queue_messages", {"queue": q, "vhost": "/"}, every(15, lambda s, k=k: (k * s) % 400)) for k, q in enumerate(("a", "b", "c"), 1)]
    src, spec = store(dump)
    defs = views(families(src, spec)["rabbitmq_queue_messages"], spec)
    total = next(d for d in defs if d.view == "sum_by" and not d.group_by)
    split = next(d for d in defs if d.view == "sum_by" and d.group_by == ["queue"])
    assert total.merged == {"queue": 3} and "merges queue (3 values)" in total.flags
    assert split.merged == {} and not any("merges" in f for f in split.flags)


def test_the_same_pods_counted_from_two_families_are_counted_once(store, tmp_path):
    """Pods come and go; two families report for each of them under different labels (``app`` and
    ``service``, each kept), so the two counts are of different things by their labels alone."""
    def life(i):
        return T0 + 300 * i, T0 + 300 * i + 1500
    dump = []
    for i in range(6):
        a, b = life(i)
        dump.append(("go_goroutines", {"pod": f"p{i}", "app": "frontend"}, every(15, lambda s: 40.0, start=a, end=b)))
        dump.append(("go_memstats_alloc_bytes", {"pod": f"p{i}", "service": "frontend"}, every(15, lambda s: 4e6 + s, start=a, end=b)))
    src, spec = store(dump, labels={"app": ["app"], "service": ["service"]})
    got = infer(src, spec, [], tmp_path, T0, END)
    counts = [d for d in got.kept if d.view == "count"]
    assert len({d.family for d in counts}) == 1, [d.name for d in counts]
    twin = [d for d in got.left_out if "the same things counted from another family" in d.why]
    assert twin and all(d.view == "count" for d in twin)
