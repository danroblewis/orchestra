"""A balance is a stock's only on evidence that holds (sd.identify, sd.accept): its counters chosen
again on each half of the window, the level reproduced over time, chance priced by a shift null,
enough units, the right units; and every stock records how far to trust it (sd.stocktrust).

The cases are the metrics lab's review r1 findings, made small: a noise-soaking counter beside a true
balance (F1), a proxy that fits every step and drifts from the level (F7), a slow gauge balanced on
two stretches (F3, F9), a count of reporters balanced by its own turnover (F4), a hidden stock given
R² 1 (F4), and CPU seconds in a balance of messages (F8)."""

import random

from test_discover_passing import chain  # pytest puts this folder on the path

from orchestra.metrics.file import FileMetrics
from orchestra.sd.balance import LeastSquares, columns, fit_of
from orchestra.sd.discover import discover
from orchestra.sd.identify import identify
from orchestra.sd.live import balance_steps
from orchestra.sd.series import sample
from orchestra.sd.units import from_name, unit_of

T0 = 1_800_000_000.0
STEP = 15.0
N = 240                     # an hour of 15 s steps


def _counter(name: str, incs: list[int], labels=None) -> tuple:
    total, pts = 0, []
    for i, d in enumerate(incs):
        total += d
        pts.append((T0 + STEP * i, float(total)))
    return (name, labels or {"instrument": "lab"}, pts)


def _queue(rng: random.Random, noise: float = 0.0, steady_in: float = 0.0):
    """A queue filled by ``in_total`` and drained by ``out_total``, its length written every step
    with ``noise`` (a gauge scraped a moment off the counters); ``steady_in``: items per step that
    arrive uncounted."""
    ins, outs, lv, q, extra = [], [], [], 50, 0.0
    for i in range(N + 1):
        a = rng.randint(5, 30) if (i // 40) % 2 else rng.randint(0, 12)
        d = min(q + a, rng.randint(5, 25))
        extra += steady_in
        q += a - d + int(extra)
        extra -= int(extra)
        ins.append(a)
        outs.append(d)
        lv.append((T0 + STEP * i, float(q + (rng.choice([-1, 0, 1]) if noise and rng.random() < noise else 0))))
    return ins, outs, lv


def _series(dump):
    return {s.name: s for s in sample(dump, T0, STEP, N)}


def test_a_counter_only_the_whole_window_chose_is_dropped():
    rng = random.Random(2)
    ins, outs, lv = _queue(rng, noise=0.5)
    junk = [rng.randint(0, 3) for _ in range(N + 1)]
    dump = [_counter("in_total", ins), _counter("out_total", outs), _counter("gc_runs_total", junk), ("queue_length", {"instrument": "lab"}, lv)]
    s = _series(dump)
    level, pool = s["queue_length"], [s["in_total"], s["out_total"], s["gc_runs_total"]]
    steps = balance_steps(level, pool)
    terms = [(s["in_total"], 1), (s["out_total"], -1), (s["gc_runs_total"], -1)]     # as a search over the whole window might
    r2, exact = fit_of(level, terms, steps)
    got = identify(level, terms, r2, exact, pool, steps, _solver)
    assert [c.name for c, _ in got.terms] == ["in_total", "out_total"], got.record()
    assert [c.name for c, _ in got.dropped] == ["gc_runs_total"]
    assert got.held_out_r2 > 0.8 and got.p_null is not None and got.p_null <= 0.1 + 1e-9
    assert got.cum_ratio < 0.1


def _solver(level, pool, steps):
    return LeastSquares(columns(level, pool, steps))


def test_a_proxy_that_drifts_from_the_level_is_refused_and_says_why():
    # the backlog's true inflow is not offered; requests, one per message most of the time, are.
    # Step by step they fit (R² ≥ 0.9); over the hour they drift from the level by more than it moves
    rng = random.Random(5)
    outs, req, lv, q = [], [], [], 300
    for i in range(N + 1):
        a = rng.randint(30, 70)
        d = min(q + a, rng.randint(30, 70))
        q += a - d
        outs.append(d)
        req.append(a + (3 if i < N // 2 else -3))        # a proxy a little off, and off one way for a while
        lv.append((T0 + STEP * i, float(q)))
    dump = [_counter("requests_total", req), _counter("consumed_total", outs), ("backlog_messages", {"instrument": "lab"}, lv)]
    m = discover(dump, start=T0, end=T0 + N * STEP, step=STEP)
    why = m.discovery["left_out"]['backlog_messages{instrument="lab"}']
    assert "backlog_messages" not in {s.id for s in m.stocks if "balance" in s.evidence}, why
    assert why.startswith("no counters balance it on evidence that holds") and "does not reproduce the level" in why, why
    rec = m.discovery["refused"]['backlog_messages{instrument="lab"}']
    assert rec["r2"] >= 0.9 and rec["held_out_r2"] >= 0.5 and rec["cum_residual_ratio"] > 0.5, rec


def test_an_exact_balance_is_a_stock_with_high_trust():
    rng = random.Random(3)
    ins, outs, lv = _queue(rng)
    dump = [_counter("in_total", ins), _counter("out_total", outs), ("queue_length", {"instrument": "lab"}, lv)]
    m = discover(dump, start=T0, end=T0 + N * STEP, step=STEP)
    [st] = m.stocks
    tr = st.evidence["trust"]
    assert tr["kind"] == "conservation" and tr["score"] >= 0.8 and tr["level"] == "high", tr
    assert set(tr["components"]) >= {"null", "held_out", "level", "units"}
    assert tr["p_null"] <= 0.1 + 1e-9 and tr["cum_residual_ratio"] < 0.01 and tr["units"] == N
    assert st.evidence["identification"]["exact_moved"] == 1.0


def test_a_level_its_counters_do_not_reproduce_is_no_conservation_stock_however_well_they_fit():
    # a supplier nobody counts adds an item every other step: the counters explain each step (R² 0.99)
    # but not the level, which drifts from them by more than it moves. From the data that is a proxy
    # off by a steady rate as much as a flow no counter measures, so it is refused, and the record says
    # how much of the drift a steady unmeasured flow would account for
    rng = random.Random(8)
    ins, outs, lv = _queue(rng, noise=0.3, steady_in=0.5)
    dump = [_counter("in_total", ins), _counter("out_total", outs), ("queue_length", {"instrument": "lab"}, lv)]
    m = discover(dump, start=T0, end=T0 + N * STEP, step=STEP)
    assert "queue_length" not in {s.id for s in m.stocks if "balance" in s.evidence}
    rec = m.discovery["refused"]['queue_length{instrument="lab"}']
    assert rec["r2"] > 0.9 and rec["cum_residual_steady"] < 0.5 < rec["cum_residual_ratio"], rec


def test_a_gauge_that_changed_twice_is_no_stock_whatever_counters_rise():
    # requests polled every 30 s that changed twice in the hour, beside two bytes counters that rise
    # steadily: read as ramps between its changes and balanced on its two stretches, this was a
    # stock at R² 1.000 (review r1 F3)
    rng = random.Random(4)
    gauge = [(T0 + 30 * i, 16777216011.85 if i < 40 else (16777216011.85 + 5.2e6 if i < 90 else 16777216011.85 - 2.6e6))
             for i in range(N // 2 + 1)]
    dump = [("resource_requests", {"instrument": "ksm"}, gauge),
            _counter("rx_bytes_total", [rng.randint(100_000, 200_000) for _ in range(N + 1)]),
            _counter("tx_bytes_total", [rng.randint(100_000, 200_000) for _ in range(N + 1)])]
    m = discover(dump, start=T0, end=T0 + N * STEP, step=STEP)
    assert not m.stocks
    assert "changed in only 2 steps" in m.discovery["left_out"]['resource_requests{instrument="ksm"}']


def test_a_count_of_reporters_balanced_by_its_own_turnover_is_marked_and_split_by_outcome_left_out():
    rng = random.Random(6)
    prov, dump = {}, []
    for labels in ({"job": "frontend"}, {"code": "404"}):
        n, started, stopped, pts, ups, downs = 3, 0, 0, [], [], []
        for i in range(N + 1):
            if rng.random() < 0.08:
                if rng.random() < 0.5 and n > 1:
                    n, stopped = n - 1, stopped + 1
                else:
                    n, started = n + 1, started + 1
            pts.append((T0 + STEP * i, float(n)))
            ups.append((T0 + STEP * i, float(started)))
            downs.append((T0 + STEP * i, float(stopped)))
        lab = {"instrument": "lab", **labels}
        key = ",".join(f'{k}="{v}"' for k, v in sorted(lab.items()))
        dump += [("http_requests_pods", lab, pts), ("http_requests_pods_started_total", lab, ups),
                 ("http_requests_pods_stopped_total", lab, downs)]
        prov[f"http_requests_pods{{{key}}}"] = {"view": "count", "unit": "pods"}
        prov[f"http_requests_pods_started_total{{{key}}}"] = {"view": "starts", "unit": "pods"}
        prov[f"http_requests_pods_stopped_total{{{key}}}"] = {"view": "stops", "unit": "pods"}
    m = discover(dump, start=T0, end=T0 + N * STEP, step=STEP, provenance=prov)
    [st] = m.stocks
    assert st.series.labels["job"] == "frontend"
    ev = st.evidence
    assert ev["by_construction"] is True and ev["balance_r2"] is None and ev["exact_steps"] is None
    assert ev["trust"]["kind"] == "by_construction" and ev["trust"]["score"] == 0.0
    assert m.discovery["by_construction"] == [st.id] and m.discovery["stocks"] == 0, "not counted as a discovered stock"
    why = m.discovery["left_out"]['http_requests_pods{code="404",instrument="lab"}']
    assert "by construction" in why and "code" in why


def test_cpu_seconds_never_balance_a_queue_of_messages():
    # a counter of CPU seconds that happens to count what the queue gains is in another unit
    rng = random.Random(7)
    ins, outs, lv = _queue(rng)
    dump = [_counter("process_cpu_seconds_total", ins), _counter("delivered_total", outs), ("queue_messages", {"instrument": "lab"}, lv)]
    m = discover(dump, start=T0, end=T0 + N * STEP, step=STEP)
    assert not any("process_cpu_seconds_total" in b["series"] for s in m.stocks for b in s.evidence.get("balance", []))


def test_units_are_read_from_labels_declarations_and_names():
    assert from_name("node_cpu_seconds_total") == "seconds"
    assert from_name("container_cpu_usage_seconds_total:sum_irate") == "seconds"
    assert from_name("http_request_duration_seconds_count") == "count"
    assert from_name("node_network_receive_bytes_total") == "bytes"
    assert from_name("kafka_broker_topic_bytes_in_total") == "count"     # "in" after the unit: not a unit word last
    assert from_name("envoy_cluster_upstream_cx_destroy") == "count"
    assert from_name("lab:kubelet_volume_stats_available_bytes") == "bytes"
    assert unit_of("kube_pod_container_resource_requests", {"unit": "core"}) == "cores"
    assert unit_of("kube_pod_container_resource_requests", {"unit": "byte"}) == "bytes"
    assert unit_of("throughput", {}, "KiB") == "kibibytes"
    assert unit_of("http_requests_pods", {}, "pods") == "count"


def test_a_hidden_state_has_no_r2(tmp_path):
    m = chain(FileMetrics(tmp_path / "m.jsonl"), write_x=False, split=True)
    hidden = [s for s in m.stocks if s.series is None]
    assert hidden, [s.id for s in m.stocks]
    for s in hidden:
        assert s.evidence["balance_r2"] is None and s.evidence["exact_steps"] is None and s.evidence["measured"] is False
        assert s.evidence["trust"]["kind"] == "unmeasured" and s.evidence["trust"]["score"] == 0.0


def test_a_net_flow_stock_records_its_trust_with_a_shift_null():
    from test_discover_net_flow import HOURS, _outside, _room
    rng = random.Random(1)
    outside = _outside(rng)
    dump = [("outside_celsius", {"machine": "weather"}, outside), ("room_celsius", {"machine": "thermostat"}, _room(outside, rng))]
    m = discover(dump, start=T0, end=T0 + HOURS * 3600, step=5.0)
    room = m.stock("room_celsius")
    tr = room.evidence["trust"]
    assert tr["kind"] == "net_flow" and tr["null_shifts"] > 0 and 0 < tr["p_null"] <= 1
    assert set(tr["components"]) >= {"null", "held_out", "level", "units", "fit"}
    assert tr["score"] == min(tr["components"].values()) and tr["held_out_r2"] > 0.5, tr


def test_persistence_is_the_share_of_recent_discoveries_that_found_the_stock_the_same_way(tmp_path):
    from orchestra.sd import persistence
    from orchestra.sd.store import ModelStore
    rng = random.Random(3)
    ins, outs, lv = _queue(rng)
    dump = [_counter("in_total", ins), _counter("out_total", outs), ("queue_length", {"instrument": "lab"}, lv)]
    store = ModelStore.for_state(tmp_path)
    scores = []
    for k in range(5):
        m = discover(dump, start=T0, end=T0 + N * STEP, step=STEP)
        persistence.apply(store, m, at=1000.0 + k)
        scores.append(m.stocks[0].evidence["trust"])
    assert [t["persistence_of"] for t in scores] == [0, 1, 2, 3, 4]
    assert scores[-1]["persistence"] == 1.0 and "persistence" in scores[-1]["components"]
    assert "persistence" not in scores[1]["components"], "a component only once enough discoveries are remembered"
    # a stock found another way (another counter) is not the same finding
    m = discover(dump, start=T0, end=T0 + N * STEP, step=STEP)
    m.stocks[0].evidence["balance"] = [{"series": "other_total", "sign": 1}]
    persistence.apply(store, m, at=2000.0)
    assert m.stocks[0].evidence["trust"]["persistence"] == 0.0 and m.stocks[0].evidence["trust"]["score"] == 0.0


def test_a_level_split_by_a_one_valued_label_and_its_total_are_one_stock():
    # the lag of the one group that reads a topic, read by group and by topic: equal at every step
    # (review r1 F5: every window held two or three copies of one stock); two groups stay two
    rng = random.Random(9)
    ins, outs, lv = _queue(rng)
    dump = [_counter("in_total", ins), _counter("out_total", outs),
            ("lag", {"instrument": "lab", "group": "analytics"}, lv), ("lag", {"instrument": "lab", "topic": "clicks"}, list(lv))]
    m = discover(dump, start=T0, end=T0 + N * STEP, step=STEP)
    [st] = [s for s in m.stocks if s.series and s.series.name == "lag"]
    assert len(st.evidence["twins"]) == 1, st.evidence
    two = [("lag", {"instrument": "lab", "group": g}, list(lv)) for g in ("a", "b")]
    m = discover([_counter("in_total", ins), _counter("out_total", outs), *two], start=T0, end=T0 + N * STEP, step=STEP)
    assert len([s for s in m.stocks if s.series and s.series.name == "lag"]) == 2


def test_of_a_total_and_the_one_part_that_moves_the_part_is_kept():
    # at night the email queue is empty and the dead-letter queue is all the total holds: the two read
    # the same, and the stock is the dead-letter queue, which the labels name
    rng = random.Random(10)
    ins, outs, lv = _queue(rng)
    dump = [_counter("in_total", ins), _counter("out_total", outs), ("queue_messages", {"instrument": "lab"}, lv),
            ("queue_messages", {"instrument": "lab", "queue": "dlq"}, list(lv))]
    m = discover(dump, start=T0, end=T0 + N * STEP, step=STEP)
    [st] = [s for s in m.stocks if s.series and s.series.name == "queue_messages"]
    assert st.series.labels.get("queue") == "dlq" and len(st.evidence["twins"]) == 1
