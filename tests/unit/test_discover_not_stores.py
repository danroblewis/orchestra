"""Levels that are no store, whatever their data (sd.properties), and balances the evidence does not
identify (sd.accept), from the metrics lab's cleanup round (reports/05-identification.md):

- a maximum over partitions (``…_lag_max``) is a statistic: never a stock, even balanced exactly;
- a process's CPU, threads or memory is a property of the process: no net flow is fitted to it;
- a balance whose halves chose different counters, short of exact, is not identified;
- two levels in different units (bytes and messages) are never one stock measured twice."""

import random

from test_discover_identification import STEP, T0, N, _counter, _queue
from test_discover_net_flow import HOURS, _outside, _room

from orchestra.sd.accept import gate
from orchestra.sd.discover import discover, twin_levels
from orchestra.sd.identify import Identification
from orchestra.sd.properties import resource, statistic
from orchestra.sd.series import Declared, sample


def test_a_maximum_is_a_statistic_and_never_a_stock_even_balanced_exactly():
    rng = random.Random(3)
    ins, outs, lv = _queue(rng)
    dump = [_counter("in_total", ins), _counter("out_total", outs), ("records_lag_max", {"instrument": "lab"}, lv)]
    m = discover(dump, start=T0, end=T0 + N * STEP, step=STEP)
    assert m.stocks == []
    assert "a statistic" in m.discovery["left_out"]['records_lag_max{instrument="lab"}']


def test_what_a_source_summarised_across_reporters_is_never_a_stock():
    rng = random.Random(3)
    ins, outs, lv = _queue(rng)
    dump = [_counter("in_total", ins), _counter("out_total", outs), ("backlog", {"instrument": "lab"}, lv)]
    kinds = {'backlog{instrument="lab"}': Declared("level", summary=True)}
    m = discover(dump, start=T0, end=T0 + N * STEP, step=STEP, kinds=kinds)
    assert m.stocks == []


def test_names_and_units_that_say_statistic_or_resource():
    assert statistic("kafka_consumer_fetch_manager_records_lag_max") and statistic("lab:latency_p99")
    assert statistic("shelf_mean_age_s") and not statistic("kafka_consumergroup_lag_sum") and not statistic("minio_objects")
    assert resource("process_cpu_usage") and resource("jvm_threads_live_threads") and resource("node_load1")
    assert resource("container_memory_rss") and resource("hpa_target", "ratio")
    assert not resource("node_filesystem_avail_bytes", "bytes") and not resource("frontend_sessions_active")


def test_a_process_resource_gets_no_net_flow():
    # the room's model, renamed: a process's CPU in use pulled toward its load. As a room it is a
    # stock by its net flow; as a process's CPU, nothing has accumulated
    rng = random.Random(1)
    outside = _outside(rng)
    dump = [("work_queued", {"machine": "app"}, outside), ("process_cpu_usage", {"machine": "app"}, _room(outside, rng))]
    m = discover(dump, start=T0, end=T0 + HOURS * 3600, step=5.0)
    assert "process_cpu_usage" not in {s.id for s in m.stocks}
    assert "a resource a process or host uses" in m.discovery["left_out"]['process_cpu_usage{machine="app"}']


def test_a_balance_its_halves_did_not_choose_alike_is_refused_unless_exact():
    idn = Identification([], 0.95, 0.0, 120, held_out_r2=0.95, stable=False, cum_ratio=0.01, p_null=0.1)
    assert "chose different counters" in gate(idn)
    idn.exact_moved, idn.moved = 1.0, 50                   # exact: its own proof
    assert gate(idn) == ""
    timing = Identification([], 0.62, 0.0, 57, held_out_r2=0.7, stable=False, cum_ratio=0.01, p_null=0.1, misses_rho=-0.5)
    assert gate(timing) == ""                               # on a slow counter's writes, the halves' choice is noisy


def test_bytes_and_messages_are_never_twins():
    rng = random.Random(3)
    _, _, lv = _queue(rng)
    dump = [("lag", {"instrument": "lab"}, lv), ("volume_used_bytes", {"instrument": "lab"}, lv)]
    a, b = sample(dump, T0, STEP, N)
    left: dict = {}
    kept, _ = twin_levels([(a, [], 1.0, 1.0), (b, [], 1.0, 1.0)], left, lambda x, y: False, unit={a.key: "count", b.key: "bytes"})
    assert len(kept) == 2 and not left
    kept, _ = twin_levels([(a, [], 1.0, 1.0), (b, [], 1.0, 1.0)], left, lambda x, y: False, unit={a.key: "count", b.key: "count"})
    assert len(kept) == 1


def test_a_lag_balanced_by_offsets_read_once_a_minute_is_found_on_their_writes():
    # a consumer lag read every 15 s; its topic's produced and consumed offsets read server-side
    # every 30 s (declared so by the source). On steps the offsets move every other step; on their
    # writes, produced less consumed is the lag's change exactly
    rng = random.Random(4)
    ins, outs, lv = _queue(rng)
    slow = lambda incs: [(T0 + STEP * i, float(sum(incs[: i + 1]))) for i in range(0, N + 1, 2)]
    dump = [("produced_total", {"instrument": "lab"}, slow(ins)), ("consumed_total", {"instrument": "lab"}, slow(outs)),
            ("lag", {"instrument": "lab"}, lv)]
    kinds = {'produced_total{instrument="lab"}': Declared("counter", resolution_s=2 * STEP),
             'consumed_total{instrument="lab"}': Declared("counter", resolution_s=2 * STEP)}
    m = discover(dump, start=T0, end=T0 + N * STEP, step=STEP, kinds=kinds)
    [st] = m.stocks
    assert {(b["series"], b["sign"]) for b in st.evidence["balance"]} == {('produced_total{instrument="lab"}', 1),
                                                                         ('consumed_total{instrument="lab"}', -1)}
