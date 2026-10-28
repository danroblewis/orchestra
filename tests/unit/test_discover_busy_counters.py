"""Busy counters from another store (sd.between, sd.passing, sd.discover): a level that wiggles
at every sample is not the state between counters that count at every sample, a counter no
machine writes does not join a passage on its total alone, and the likelihood the flow fitter
evaluates is the same summed by level as by event."""

from __future__ import annotations

import json
import math
import random
from pathlib import Path

from orchestra.sd.between import at_events
from orchestra.sd.discover import _by_level
from orchestra.sd.passing import _best
from orchestra.sd.series import Series

T0 = 1_800_000_000.0


def counter(name: str, every: float, minutes: int = 30, machine: str | None = None, rate: float = 7.0) -> Series:
    pts, v = [], 0.0
    for i in range(int(minutes * 60 / every)):
        v += rate
        pts.append((T0 + every * i, v))
    return Series(name, {"machine": machine} if machine else {}, pts, [], True)


def test_a_wiggling_level_is_no_state_between_counters_that_count_at_every_sample():
    rng = random.Random(4)
    memory = Series("container_memory_rss", {}, [(T0 + 15 * i + 2, 1e9 + rng.randint(-5, 5) * 1e6) for i in range(120)], [], False)
    ins, outs = [counter("requests_total", 15)], [counter("orders_total", 15)]
    assert at_events(memory, ins, outs, T0, T0 + 1800, 30) is None
    sparse = Series("x_level", {}, [(T0 + 1, 0.0), (T0 + 600.3, 1.0), (T0 + 600.6, 0.0), (T0 + 1200.3, 1.0), (T0 + 1200.6, 0.0)], [], False)
    rare_in = Series("moved_total", {}, [(T0, 0.0), (T0 + 600.3, 1.0), (T0 + 1200.3, 2.0)], [], True)
    rare_out = Series("passed_total", {}, [(T0, 0.0), (T0 + 600.6, 1.0), (T0 + 1200.6, 2.0)], [], True)
    assert at_events(sparse, [rare_in], [rare_out], T0, T0 + 1800, 30) == ([2, 2], [2, 2])


def test_a_counter_no_machine_writes_never_joins_a_passage():
    """A drain and a fill whose totals differ by what a third, machine-less counter counted."""
    n = 60
    drain = Series("moved_total", {}, [], [float(10 * i) for i in range(n)], True)
    fill = Series("passed_total", {}, [], [float(7 * i) for i in range(n)], True)
    other = Series("http_requests_total", {}, [], [float(3 * i) for i in range(n)], True)
    claims = {drain.key: {("a", -1)}, fill.key: {("b", 1)}}
    total = {c.key: c.values[-1] - c.values[0] for c in (drain, fill, other)}
    machine = {drain.key: None, fill.key: None, other.key: None}
    writer_of = lambda c: machine[c.key]
    pool = [(other, -1)]
    assert _best(drain, [fill], pool, total, claims, 5, writer_of, lambda i, o: False) is None
    machine.update({drain.key: "worker", fill.key: "worker", other.key: "worker"})
    got = _best(drain, [fill], pool, total, claims, 5, writer_of, lambda i, o: False)
    assert got is not None and [c.name for c in got[2]] == ["passed_total", "http_requests_total"]


def test_the_likelihood_summed_by_level_is_the_likelihood_summed_by_event():
    rng = random.Random(1)
    events = [(T0 + i, float(rng.randint(1, 4))) for i in range(500)]
    xs = [float(rng.randint(0, 6)) for _ in events]
    by_event = sum(d * math.log(2 + 0.5 * x) for (_, d), x in zip(events, xs, strict=True))
    by_level = sum(d * math.log(2 + 0.5 * x) for x, d in _by_level(events, xs))
    assert len(_by_level(events, xs)) == 7 and math.isclose(by_event, by_level, rel_tol=1e-12)


def test_a_counter_millions_of_times_the_level_does_not_hide_its_balance():
    """An hour, calm, of a store (data/pool_beside_bytes.json): a gateway's connection pool
    that gains or loses two now and then, its opened and closed counters (about ten a step each),
    and the bytes four nodes sent (millions a step). The bytes' squares round to more than the
    pool's whole variance; searched, every pair with them looked exact and crowded out the pair
    that is, and the pool was left out as an input."""
    from orchestra.sd.discover import discover
    from orchestra.sd.series import Declared, series_key

    start = 1_793_179_800.0                                   # the store's window, as it was read
    data = json.loads((Path(__file__).parent / "data" / "pool_beside_bytes.json").read_text())
    dump = [(f"lab:{name}", {}, [(start + t, float(v)) for t, v in pts]) for name, pts in data.items()]   # floats, as read
    kinds = {series_key(n, {}): Declared("level" if n.endswith("_active") else "counter", resolution_s=15.0) for n, _, _ in dump}
    m = discover(dump, start=start, end=start + 3600, step=30, time_unit="minute", kinds=kinds)
    pool = next((s for s in m.stocks if s.id == "lab:envoy_cluster_upstream_cx_active"), None)
    assert pool is not None, m.discovery["left_out"].get("lab:envoy_cluster_upstream_cx_active")
    assert sorted((b["series"], b["sign"]) for b in pool.evidence["balance"]) == [
        ("lab:envoy_cluster_upstream_cx_destroy", -1), ("lab:envoy_cluster_upstream_cx_total", 1)]
    assert pool.evidence["balance_r2"] > 0.999


def test_dispersion_counts_events_at_one_instant_without_listing_them():
    """A counter of bytes counts millions a step; the gaps between events at one instant are 0,
    counted rather than listed, and the statistic is what listing them gave."""
    from itertools import pairwise

    from orchestra.sd.discover import dispersion

    def listed(events, live, c, unit_s):
        times = [t for t, d in events for _ in range(int(d))]
        gaps = [max(0.0, c) * sum(max(0.0, min(b, hi) - max(a, lo)) for lo, hi in live) / unit_s for a, b in pairwise(times)]
        mean = sum(gaps) / len(gaps)
        return sum((g - mean) ** 2 for g in gaps) / max(1, len(gaps) - 1) / max(mean * mean, 1e-12)

    rng = random.Random(3)
    for _ in range(20):
        events = sorted((rng.uniform(0, 3600), float(rng.choice([0, 1, 1, 2, 5, 0.5, 30]))) for _ in range(rng.randint(3, 200)))
        if sum(int(d) for _, d in events) < 2:
            continue
        got = dispersion(events, [(0.0, 3600.0)], {"params": {"c": 2.0}, "inputs": []}, {}, 60.0)
        assert math.isclose(got, listed(events, [(0.0, 3600.0)], 2.0, 60.0), rel_tol=1e-9)
    big = [(30.0 * i, 6.3e6) for i in range(120)]                        # would be 756 million gaps listed
    assert dispersion(big, [(0.0, 3600.0)], {"params": {"c": 1.0}, "inputs": []}, {}, 60.0) > 1
