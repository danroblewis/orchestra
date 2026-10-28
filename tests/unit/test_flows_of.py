"""``sd.flows_of``: discovery's balance search and gates, asked about one level."""

from __future__ import annotations

import random

from orchestra.sd.flows_of import flows_of, name_unit
from orchestra.sd.series import Declared

START, STEP, N = 1_000_000.0, 30.0, 120


def _counter(incs: list[float]) -> list[tuple[float, float]]:
    total, out = 0.0, [(START, 0.0)]
    for i, v in enumerate(incs):
        total += v
        out.append((START + (i + 1) * STEP, total))
    return out


def _level(changes: list[float], at: float = 100.0) -> list[tuple[float, float]]:
    out = [(START, at)]
    for i, v in enumerate(changes):
        at += v
        out.append((START + (i + 1) * STEP, at))
    return out


def _queue(seed: int = 1):
    rnd = random.Random(seed)
    ins = [rnd.randint(5, 30) for _ in range(N)]
    outs = [rnd.randint(5, 30) for _ in range(N)]
    noise = [rnd.randint(0, 40) for _ in range(N)]
    return ins, outs, noise


def test_a_queue_is_balanced_by_its_inflow_less_its_outflow_and_accepted():
    ins, outs, noise = _queue()
    level = ("shop:queue_messages", {}, _level([a - b for a, b in zip(ins, outs)]))
    counters = [("shop:published_total", {}, _counter(ins)), ("shop:acked_total", {}, _counter(outs)),
                ("shop:http_requests_total", {}, _counter(noise))]
    got = flows_of(level, counters, START, STEP, N)
    best = got.balances[0]
    assert sorted(best.terms) == [("shop:acked_total", -1), ("shop:published_total", 1)]
    assert best.accepted and best.r2 > 0.99 and best.exact == 1.0
    assert best.evidence["held_out_r2"] > 0.9 and best.residual == 0.0


def test_a_counter_in_another_unit_is_never_a_term_and_is_listed():
    ins, outs, _ = _queue(2)
    level = ("q:messages", {}, _level([a - b for a, b in zip(ins, outs)]))
    counters = [("q:in_total", {}, _counter(ins)), ("q:out_total", {}, _counter(outs)),
                ("q:cpu_seconds_total", {}, _counter([float(x) for x in ins]))]
    got = flows_of(level, counters, START, STEP, N)
    assert got.other_units == {"q:cpu_seconds_total": "seconds"}
    assert all(k != "q:cpu_seconds_total" for k, _ in got.balances[0].terms)


def test_a_unit_glued_to_its_direction_is_read():
    assert name_unit("kafka_server_brokertopicmetrics_bytesin_total", {}) == "bytes"
    assert name_unit("kafka_topic_partition_current_offset", {}) == "count"
    assert name_unit("node_network_receive_bytes_total", {}) == "bytes"


def test_a_level_drained_in_bursts_no_counter_measures_is_balanced_between_them():
    """A log volume: bytes in every step, retention deleting a whole segment now and then."""
    rnd = random.Random(3)
    ins = [float(rnd.randint(14_000_000, 16_000_000)) for _ in range(N)]
    changes = list(ins)
    for i in (20, 60, 100):
        changes[i] -= 500_000_000
    level = ("shop:volume_used_bytes", {}, _level(changes, 5e10))
    counters = [("biz:bytesin_total", {}, _counter(ins)),
                ("biz:other_bytes_total", {}, _counter([float(rnd.randint(1, 9) * 1_000_000) for _ in range(N)]))]
    got = flows_of(level, counters, START, STEP, N)
    best = got.balances[0]
    assert best.terms == [("biz:bytesin_total", 1)]
    assert best.accepted and best.bursts["direction"] == "falls" and best.bursts["units"] == 3


def test_a_counter_read_once_every_four_steps_balances_on_its_writes():
    """The outflow from a store that reports every two minutes, held between its samples."""
    ins, outs, _ = _queue(4)
    level = ("shop:queue_messages", {}, _level([a - b for a, b in zip(ins, outs)]))
    slow, total = [], 0.0
    for i in range(N + 1):
        if i and i % 4 == 0:
            total += sum(outs[i - 4:i])
        slow.append((START + i * STEP, total))
    counters = [("shop:published_total", {}, _counter(ins)), ("biz:sent_total", {}, slow)]
    kinds = {"biz:sent_total": Declared("counter", resolution_s=120.0)}
    got = flows_of(level, counters, START, STEP, N, kinds)
    best = got.balances[0]
    assert sorted(best.terms) == [("biz:sent_total", -1), ("shop:published_total", 1)]
    assert "biz:sent_total" in best.on and best.accepted


def test_a_copy_of_a_flow_is_reported_as_an_alternative():
    ins, outs, _ = _queue(5)
    level = ("q:messages", {}, _level([a - b for a, b in zip(ins, outs)]))
    counters = [("a:in_total", {}, _counter(ins)), ("a:out_total", {}, _counter(outs)), ("b:sent_total", {}, _counter(outs))]
    got = flows_of(level, counters, START, STEP, N)
    seen = [sorted(b.terms) for b in got.balances]
    assert [("a:in_total", 1), ("a:out_total", -1)] in seen and [("a:in_total", 1), ("b:sent_total", -1)] in seen


def test_nothing_is_claimed_for_a_level_no_counter_balances():
    rnd = random.Random(6)
    level = ("x:level", {}, _level([rnd.randint(-50, 50) for _ in range(N)]))
    counters = [("x:a_total", {}, _counter([rnd.randint(0, 9) for _ in range(N)]))]
    got = flows_of(level, counters, START, STEP, N)
    assert not got.balances and got.why


def test_a_level_that_barely_moved_says_so():
    level = ("x:level", {}, _level([0.0] * (N - 2) + [1.0, -1.0]))
    got = flows_of(level, [("x:a_total", {}, _counter([1.0] * N))], START, STEP, N)
    assert not got.balances and "too few" in got.why
