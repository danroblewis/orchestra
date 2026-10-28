"""What a store's samples say a metric is (sources/behaviour.py), which of its labels repeat each
other (sources/duplicates.py), and how candidates are told apart and named (rank, infer): pure,
on small payloads shaped like a real store's."""

from __future__ import annotations

from orchestra.sources.behaviour import amount, classify
from orchestra.sources.duplicates import duplicated, same_shape
from orchestra.sources.infer import apart, unique_names
from orchestra.sources.rank import rank
from orchestra.sources.spec import load
from orchestra.sources.views import Definition

T0 = 1_793_000_000.0          # 2026-10-26: values near it read as Unix times


def series(values, every=15.0, t0=T0):
    return [(t0 + every * i, float(v)) for i, v in enumerate(values)]


# A counter typed a gauge, and the gauge it must not be confused with


def test_kafka_offsets_typed_gauge_are_a_counter():
    """kafka_exporter types every family a gauge; a partition's offset only rises."""
    offs = [series(1_800_000 + 37 * i + (i % 3) for i in range(120)), series(950_000 + 12 * i for i in range(120))]
    kind, why = classify("kafka_topic_partition_current_offset", "gauge", "Current Offset of a Broker at Topic/Partition", offs)
    assert kind == "counter" and "typed gauge" in why


def test_a_counter_with_resets_typed_gauge_is_a_counter():
    """A worker's messages processed since start: it restarts from zero when its pod does."""
    v = [500 + 9 * i for i in range(60)] + [4 + 9 * i for i in range(60)]
    kind, why = classify("order_worker_processed_messages", "gauge", "Messages processed since start", [series(v)])
    assert kind == "counter" and "resets" in why


def test_a_slowly_growing_disk_stays_a_gauge():
    """Disk usage that only grew in the window behaves like a counter; its name says an amount held."""
    v = [21_474_836_480 + 4096 * i for i in range(240)]
    assert classify("kubelet_volume_stats_used_bytes", "gauge", "Number of used bytes in the volume", [series(v)]) == (None, "")
    emptied = v[:100] + [0.0] * 5 + [4096 * i for i in range(135)]       # even emptied to zero: the name decides
    assert classify("node_filesystem_used_bytes", "gauge", None, [series(emptied)])[0] is None


def test_a_gauge_that_falls_by_part_stays_a_gauge():
    """A log volume trimmed by retention: it falls, but not to zero."""
    v = [1000 + 10 * (i % 40) for i in range(240)]
    assert classify("kafka_log_segments_total_size", "gauge", None, [series(v)])[0] is None
    assert classify("events_processed", "gauge", None, [series(v)])[0] is None   # not a counter whatever the name


def test_a_gauge_that_seldom_moves_is_not_a_counter():
    """A deployment's generation: it steps up at a rollout, otherwise flat."""
    v = [7] * 100 + [8] * 100 + [9] * 40
    assert classify("kube_deployment_metadata_generation", "gauge", None, [series(v)])[0] is None


def test_a_queue_that_only_grew_or_is_drained_in_batches_stays_a_gauge():
    """A queue nobody consumes in an incident, and one a batch consumer empties every five minutes."""
    grew = [series(40 * i for i in range(240))]
    assert classify("rabbitmq_queue_messages", "gauge", None, grew)[0] is None
    batches = [series((i % 20) * 50 for i in range(240))]
    assert classify("batch_queue_items", "gauge", None, batches)[0] is None
    assert classify("batch_items_processed", "gauge", None, batches)[0] is None   # a counter does not reset every 5 minutes


def test_the_last_word_names_the_amount():
    assert amount("kubelet_volume_stats_used_bytes") and amount("kafka_consumergroup_lag") and amount("http_requests_in_flight")
    assert not amount("node_netstat_Tcp_ActiveOpens") and not amount("kafka_topic_partition_current_offset")
    assert not amount("order_worker_processed_messages")


def test_a_counter_that_falls_by_halves_is_a_gauge():
    """statsd's email_queue_pending_total: typed a counter, it is a queue."""
    v = [100, 120, 90, 140, 110, 160, 100, 150, 95, 130, 120, 140]
    kind, why = classify("email_queue_pending_total", "counter", None, [series(v)])
    assert kind == "gauge" and "fell by less than half" in why
    resets = [100 + i for i in range(30)] + [2 + i for i in range(30)]
    assert classify("requests_total", "counter", None, [series(resets)]) == (None, "")


# Values that are no quantity


def test_unix_timestamps_are_neither_level_nor_flow():
    created = [series([1_792_762_671] * 40), series([1_792_915_965] * 40)]
    assert classify("kube_pod_created", "gauge", "Unix creation timestamp", created)[0] == "timestamp"
    assert classify("container_start_time_seconds", "gauge", "Start time of the container since unix epoch in seconds.", created)[0] == "timestamp"
    ms = [series([1_792_762_671_000] * 40)]
    assert classify("job_last_success_timestamp", "gauge", None, ms)[0] == "timestamp"
    memory = [series([1_792_762_671] * 40)]             # 1.7 GB of memory is not a time
    assert classify("container_memory_working_set_bytes", "gauge", None, memory)[0] is None


def test_an_uptime_is_a_clock():
    up = [series([3600 + 15 * i for i in range(60)]), series([120 + 15 * i for i in range(60)])]
    assert classify("process_uptime_seconds", "gauge", None, up)[0] == "clock"


def test_an_info_metric_is_one_everywhere():
    ones = [series([1] * 30), series([1] * 30)]
    assert classify("kube_pod_info", "gauge", None, ones, low=1.0, high=1.0)[0] == "info"
    assert classify("kube_pod_status_ready", "gauge", None, ones, low=0.0, high=1.0)[0] is None   # a 0/1 state elsewhere


# Duplicates


def _grid(*vals):
    return [float(v) for v in vals]


def test_two_scrape_jobs_of_one_exporter_are_read_once():
    """node_exporter scraped by two jobs that label their targets differently."""
    a = [({"job": "node-exporter", "instance": "10.0.1.1:9100", "mountpoint": "/"}, _grid(70, 69, 68, 67)),
         ({"job": "node-exporter", "instance": "10.0.1.2:9100", "mountpoint": "/"}, _grid(50, 50, 49, 49))]
    b = [({"job": "integrations/node_exporter", "instance": "ip-10-0-1-1", "agent_hostname": "ip-10-0-1-1"}, _grid(70, 69, 68, 67.0001)),
         ({"job": "integrations/node_exporter", "instance": "ip-10-0-1-2", "agent_hostname": "ip-10-0-1-2"}, _grid(50, 50, 49, 49))]
    assert duplicated(a + b, "job") == ("integrations/node_exporter", ["node-exporter"])


def test_equal_constants_prove_no_duplicate():
    """Two HPAs at two replicas each, all window: two things that agree."""
    s = [({"job": "a", "hpa": "x"}, _grid(2, 2, 2, 2)), ({"job": "b", "hpa": "x"}, _grid(2, 2, 2, 2))]
    assert duplicated(s, "job") is None
    differ = [({"job": "a"}, _grid(3, 4, 5, 6)), ({"job": "b"}, _grid(3, 3, 3, 3))]
    assert duplicated(differ, "job") is None


def test_two_counts_of_the_same_pods_are_one():
    a = [_grid(3, 3, 4, 4, 5), _grid(2, 2, 2, 3, 3)]
    assert same_shape(a, [_grid(2, 2, 2, 3, 3), _grid(3, 3, 4, 4, 5)])
    assert not same_shape(a, [_grid(2, 2, 2, 3, 3), _grid(3, 3, 3, 3, 3)])
    assert not same_shape([_grid(2, 2, 2)], [_grid(2, 2, 2)])       # nothing moves: nothing to tell


# Telling groups apart, and naming


def test_groups_that_move_on_their_own_are_apart():
    t = [T0 + 60 * i for i in range(60)]
    filling = [({"queue": "email"}, [(x, float(i * 10)) for i, x in enumerate(t)]),
               ({"queue": "dlq"}, [(x, float(5 if i > 30 else 0)) for i, x in enumerate(t)])]
    assert apart(filling, t[0], t[-1]) > 0.5
    together = [({"job": "a"}, [(x, float(i * 10)) for i, x in enumerate(t)]),
                ({"job": "b"}, [(x, float(i * 20)) for i, x in enumerate(t)])]
    assert apart(together, t[0], t[-1]) < 0.1
    one = [({"q": "a"}, [(x, float(i)) for i, x in enumerate(t)]), ({"q": "b"}, [(x, 3.0) for x in t])]
    assert apart(one, t[0], t[-1]) == 0.0


def _defn(i, family, name, group, view="sum_by", kind="level", card=3):
    info = {c: {"role": "grouping", "cardinality": card, "churn": 0.0} for c in group}
    return Definition(id=f"c{i}", source="lab", name=name, family=family, view=view, kind=kind, query="x", group_by=list(group),
                      labels_info=info, est_series=card if group else 1)


def test_every_family_is_read_whole_first_and_splits_that_move_apart_come_next(tmp_path):
    """Three queues that fill and drain on their own, and services' request counters that move
    together: with room for one split, the queues get it."""
    spec = load({"sources": [{"name": "lab", "url": "http://127.0.0.1:9", "max_series": 5}]}, tmp_path).sources[0]
    q_total, q_split = _defn(0, "queue_messages", "queue_messages", []), _defn(1, "queue_messages", "queue_messages", ["queue"])
    r_total = _defn(2, "requests_total", "requests_total", [], view="increments", kind="counter")
    r_split = _defn(3, "requests_total", "requests_total", ["job"], view="increments", kind="counter")
    probes = {"c0": {"series": 1, "moves": True}, "c1": {"series": 3, "moves": True, "apart": 0.9},
              "c2": {"series": 1, "moves": True}, "c3": {"series": 3, "moves": True, "apart": 0.05}}
    kept, left = rank([q_total, q_split, r_total, r_split], spec, probes)
    assert {d.id for d in kept} == {"c0", "c1", "c2"}
    assert [d.id for d in left] == ["c3"] and "over the cap" in left[0].why


def test_counters_split_like_a_stock_score_as_apart(tmp_path):
    """Lag split by consumer group: the offsets consumed by consumer group are what balance it,
    though the groups' consumption moves together."""
    spec = load({"sources": [{"name": "lab", "url": "http://127.0.0.1:9", "max_series": 8}]}, tmp_path).sources[0]
    lag_total, lag = _defn(0, "lag", "lag", []), _defn(1, "lag", "lag", ["consumergroup"])
    total = _defn(2, "consumed", "consumed", [], view="increments", kind="counter")
    split = _defn(3, "consumed", "consumed", ["consumergroup"], view="increments", kind="counter")
    other = _defn(4, "bytes_total", "bytes_total", ["node"], view="increments", kind="counter")
    other_total = _defn(5, "bytes_total", "bytes_total", [], view="increments", kind="counter")
    probes = {"c0": {"series": 1, "moves": True}, "c1": {"series": 3, "moves": True, "apart": 0.8},
              "c2": {"series": 1, "moves": True}, "c3": {"series": 3, "moves": True, "apart": 0.1},
              "c4": {"series": 3, "moves": True, "apart": 0.5}, "c5": {"series": 1, "moves": True}}
    kept, _ = rank([lag_total, lag, total, split, other, other_total], spec, probes)
    assert {d.id for d in kept} == {"c0", "c2", "c5", "c1"}  # 6 series: room for one split, the lag's
    spec.max_series = 9
    kept, _ = rank([lag_total, lag, total, split, other, other_total], spec, probes)
    assert {d.id for d in kept} == {"c0", "c2", "c5", "c1", "c3"}   # then the consumed by group, before the bytes by node


def test_a_rule_and_an_exporter_metric_never_share_a_name():
    rule = Definition(id="", source="lab", name="kafka_consumergroup_lag_sum", family="kafka_consumergroup_lag", view="rollup",
                      kind="level", query="sum(last_over_time(consumergroup_topic:kafka_consumergroup_lag:sum[91s]))")
    own = Definition(id="", source="lab", name="kafka_consumergroup_lag_sum", family="kafka_consumergroup_lag_sum", view="sum_by",
                     kind="level", query="sum(last_over_time(kafka_consumergroup_lag_sum[46s]))")
    for order in ([rule, own], [own, rule]):
        a, b = (Definition(**{**x.__dict__, "flags": []}) for x in order)
        unique_names([a, b])
        names = {x.family: x.name for x in (a, b)}
        assert names == {"kafka_consumergroup_lag_sum": "kafka_consumergroup_lag_sum",
                         "kafka_consumergroup_lag": "kafka_consumergroup_lag_sum__kafka_consumergroup_lag"}


# The statistics review's cases (review-r1-stats F10, F11)


def test_a_crash_looping_counter_is_a_counter():
    """An untyped request counter restarting every 8 minutes, each restart scraped after the new
    process counted a little (13% of the last value)."""
    v, out = 0.0, []
    for i in range(240):
        v = 0.13 * v if i and i % 32 == 0 else v + 5
        out.append(v)
    assert classify("api_requests", None, None, [series(out)])[0] == "counter"


def test_a_delta_gauge_is_read_as_counts_of_its_own():
    """OTel delta temporality pushed as a gauge: each sample is the requests since the last."""
    vals = [(i * 7919) % 13 + (i * 104729) % 5 for i in range(120)]
    kind, why = classify("checkoutRequests", "gauge", None, [series(vals)])
    assert kind == "delta" and "delta" in why
    assert classify("http_requests_per_second", "gauge", None, [series(vals)])[0] is None    # a rate is no count
    assert classify("http_requests_in_flight", "gauge", None, [series(vals)])[0] is None     # an amount held


def test_decides_only_on_what_the_samples_show():
    from orchestra.sources.behaviour import decides
    assert decides([series([1, 2, 3, 2.5, 4, 3, 5, 4.2])]) == "gauge"
    assert decides([series([10, 20, 30, 2, 12, 22])]) == "counter"
    assert decides([series([10, 20, 30, 40])]) == ""           # only rose: a counter or a filling level; the name cannot tell


def test_two_deployments_that_differ_only_at_a_rollout_are_two():
    steady = _grid(*([3] * 30))
    surge = _grid(*([3] * 14 + [4] + [3] * 15))
    assert not same_shape([surge], [steady]) and not same_shape([steady, surge], [steady, steady])
    lagged = _grid(*([3] * 14 + [4] * 16))
    early = _grid(*([3] * 13 + [4] * 17))
    assert same_shape([lagged], [early])                       # the same pods, seen a scrape apart


def test_two_jobs_scraping_different_nodes_are_not_one():
    """A half-migrated fleet: A, B under one job, C, D under the other; totals alike, rates not."""
    grid = lambda v, r: [v + r * k for k in range(30)]
    a = [({"job": "node-exporter", "instance": "10.0.1.1:9100"}, grid(3.0e12, 8.4e8)),
         ({"job": "node-exporter", "instance": "10.0.1.2:9100"}, grid(4.0e12, 4.2e8))]
    b = [({"job": "integrations/node_exporter", "instance": "10.0.1.3:9100"}, grid(3.0e12, 4.2e8)),
         ({"job": "integrations/node_exporter", "instance": "10.0.1.4:9100"}, grid(4.0e12, 1.26e9))]
    assert duplicated(a + b, "job", counter=True) is None
    same = [({"job": "integrations/node_exporter", "instance": "ip-10-0-1-1"}, grid(3.0e12, 8.4e8)),
            ({"job": "integrations/node_exporter", "instance": "ip-10-0-1-2"}, grid(4.0e12, 4.2e8))]
    assert duplicated(a + same, "job", counter=True) == ("integrations/node_exporter", ["node-exporter"])
    faster = [({"job": "integrations/node_exporter", "instance": "ip-10-0-1-1"}, grid(3.0e12, 2.1e9)),
              ({"job": "integrations/node_exporter", "instance": "ip-10-0-1-2"}, grid(4.0e12, 4.2e8))]
    assert duplicated(a + faster, "job", counter=True) is None    # the same targets, but not the same counts
