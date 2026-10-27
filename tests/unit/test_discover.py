"""Discovery finds a system's stocks, flows and equations from its metrics alone.

The system is a small bakery (an early version of ~/orchestra-bakery), simulated here without
sleeping so the right answer is known: the rates below."""

import itertools
import math
import random

from orchestra.metrics import Point
from orchestra.metrics.file import FileMetrics
from orchestra.sd.discover import discover

DAY, NIGHT, SHIFT_MIN, ORDER_BAKE, SELL, STALE, LOW, ORDER = 6.0, 1.5, 10, 0.5, 0.20, 0.05, 10, 20


def poisson(rng, mean):
    limit, k, p = math.exp(-mean), 0, 1.0
    while True:
        p *= rng.random()
        if p <= limit:
            return k
        k += 1


def simulate(store, minutes=90, seed=1, t0=1_800_000_000.0, outage=None):
    rng = random.Random(seed)
    lab = lambda m: {"project": "p", "machine": m}
    shelf = pending = 0
    baked = filled = sold = stale = ordered = 0
    temp, last_order = 15.0, -1e9
    pts = []
    for i in range(minutes * 60):
        t, dt = t0 + i, 1 / 60
        base = DAY if (i // (SHIFT_MIN * 60)) % 2 == 0 else NIGHT     # the oven's shifts
        if outage and outage[0] <= i < outage[1]:
            continue          # the machines are down: nothing happens and nothing is written
        b = poisson(rng, (base + ORDER_BAKE * pending) * dt)
        f = min(pending, b)
        pending -= f
        baked, filled = baked + b, filled + f
        shelf += b
        s = min(shelf, poisson(rng, SELL * shelf * dt))
        shelf -= s
        d = min(shelf, poisson(rng, STALE * shelf * dt))
        shelf -= d
        sold, stale = sold + s, stale + d
        if shelf < LOW and t - last_order > 60:
            pending += ORDER
            ordered += ORDER
            last_order = t
        temp += rng.gauss(0, 0.15) + (15 - temp) * 0.01
        if outage and i == outage[1]:
            sold = stale = ordered = 0          # the shop restarts and its counters start again from zero
        pts += [Point("bakery_loaves_baked_total", baked, t, lab("oven")), Point("bakery_orders_filled_total", filled, t, lab("oven")),
                Point("bakery_oven_orders_pending", pending, t, lab("oven")), Point("bakery_shelf_loaves", shelf, t, lab("shop")),
                Point("bakery_loaves_sold_total", sold, t, lab("shop")), Point("bakery_loaves_discarded_total", stale, t, lab("shop")),
                Point("bakery_loaves_ordered_total", ordered, t, lab("shop")), Point("weather_temperature_celsius", round(temp, 2), t, lab("weather"))]
    store.write(pts)
    return t0, t0 + minutes * 60


def test_discovers_the_bakery(tmp_path):
    store = FileMetrics(tmp_path / "m.jsonl")
    start, end = simulate(store)
    m = discover(store.dump("", {"project": "p"}), start=start, end=end, step=30)
    assert m.check() == []
    assert {s.id for s in m.stocks} == {"bakery_shelf_loaves", "bakery_oven_orders_pending"}
    assert 'weather_temperature_celsius{machine="weather"}' in m.discovery["left_out"], "the unrelated series is left out"
    f = {x.id: x for x in m.flows}
    assert (f["bakery_loaves_baked_total"].src, f["bakery_loaves_baked_total"].dst) == (None, "bakery_shelf_loaves")
    assert f["bakery_loaves_sold_total"].src == "bakery_shelf_loaves" and f["bakery_loaves_sold_total"].dst is None
    assert f["bakery_orders_filled_total"].src == "bakery_oven_orders_pending"
    assert f["bakery_loaves_ordered_total"].dst == "bakery_oven_orders_pending"

    # Which of two close forms AIC picks is partly chance; what must hold is that the flow reads its
    # source and that the proportional rate, the exact events ÷ loaf-minutes, is the true one.
    sold = f["bakery_loaves_sold_total"].current()
    assert sold.inputs == ["bakery_shelf_loaves"], (sold.form, sold.params)
    assert abs(sold.quality["proportional_k"] - SELL) < 0.03, sold.quality
    stale = f["bakery_loaves_discarded_total"].current()
    assert stale.inputs == ["bakery_shelf_loaves"] and abs(stale.quality["proportional_k"] - STALE) < 0.02
    baked = f["bakery_loaves_baked_total"].current()
    assert baked.form == "linear" and baked.inputs == ["bakery_oven_orders_pending"], "the order backlog drives the oven"
    assert NIGHT < baked.params["c"] < DAY and abs(baked.params["k"] - ORDER_BAKE) < 0.25, baked.params
    assert baked.quality["dispersion"] > 1.2, "the shifts are a driver the model lacks, and the fit says so"
    ordered = f["bakery_loaves_ordered_total"].current()
    assert ordered.form == "linear" and ordered.inputs == ["bakery_shelf_loaves"] and ordered.params["k"] < 0, \
        "a low shelf raises orders: the balancing loop"

    # the series' machine labels say who wrote them, never which machine's work a flow reflects:
    # with no events on the bus, no machine is associated with any flow (AGENTS.md rule 7)
    assert m.machines == []
    assert all(x.evidence["machines"]["hypotheses"] == [] and "no machine associated yet" in x.evidence["machines"]["why"]
               for x in m.flows)


def test_nothing_to_find_in_noise(tmp_path):
    store = FileMetrics(tmp_path / "m.jsonl")
    rng = random.Random(1)
    store.write([Point("noise_level", rng.random(), 1_800_000_000 + i, {"project": "p"}) for i in range(600)]
                + [Point("noise_total", i // 7, 1_800_000_000 + i, {"project": "p"}) for i in range(600)])
    m = discover(store.dump("", {"project": "p"}), start=1_800_000_000, end=1_800_000_600, step=10)
    assert m.stocks == [] and m.flows == []
    assert set(m.discovery["left_out"]) == {"noise_level", "noise_total"}


def counted(m) -> set[str]:
    """The stocks counters balance, and a check that any other stock (the weather, which relaxes
    toward its mean: a stock of its own by its fitted net flow) is an island no counted flow
    touches or reads."""
    net = {s.id for s in m.stocks if "net_flow" in s.evidence}
    for f in m.flows:
        if f.counter is not None or f.measured_by:
            assert not ({f.src, f.dst} & net) and not (set(f.current().inputs) & net), f
    return {s.id for s in m.stocks} - net


def test_an_outage_is_missing_data_not_a_rate_of_zero(tmp_path):
    """While the machines are down nothing is written; levels must not be carried through the gap
    as if the shelf sat still with no sales, and counters that restart from zero are resets."""
    store = FileMetrics(tmp_path / "m.jsonl")
    start, end = simulate(store, minutes=100, outage=(40 * 60, 55 * 60))
    m = discover(store.dump("", {"project": "p"}), start=start, end=end, step=30)
    assert counted(m) == {"bakery_shelf_loaves", "bakery_oven_orders_pending"}
    f = {x.id: x for x in m.flows}
    assert "bakery_loaves_sold_total" in f, "the shop's counters still count after their reset"
    sold = f["bakery_loaves_sold_total"].current()
    assert abs(sold.quality["proportional_k"] - SELL) < 0.03, sold.quality
    assert 80 < m.discovery["live_minutes"] < 90, m.discovery["live_minutes"]


def test_event_driven_counters_do_not_shrink_the_live_time(tmp_path):
    """A counter written only when an event happens is silent most of the time; that is not an
    outage, and must not cut the time the fit uses."""
    store = FileMetrics(tmp_path / "m.jsonl")
    start, end = simulate(store, minutes=60)
    sparse = [Point("orchestra_events_total", n + 1, start + 600 + 900 * n, {"project": "p", "type": "bread.ordered", "source": "shop"})
              for n in range(3)]
    store.write(sparse)
    m = discover(store.dump("", {"project": "p"}), start=start, end=end, step=30)
    assert m.discovery["live_minutes"] > 55, m.discovery["live_minutes"]
    assert len(m.flows) >= 4


def test_a_two_valued_level_is_a_stock_only_when_counters_balance_it_exactly(tmp_path):
    # a shelf that holds nothing or one item (in = put on it, out = picked up) is a stock; a
    # baker's busy flag that only moves with the work, with no counter of its own, is not
    rng, t0 = random.Random(3), 1_800_000_000.0
    lab = lambda m: {"project": "p", "machine": m}
    on, put, taken, busy, done = 0, 0, 0, 0, 0
    pts = []
    for i in range(60 * 60):
        t = t0 + i
        if on == 0 and rng.random() < 0.05:
            on, put = 1, put + 1
        elif on == 1 and rng.random() < 0.2:
            on, taken = 0, taken + 1
        if busy == 0 and rng.random() < 0.1:
            busy = 1
        elif busy == 1 and rng.random() < 0.1:
            busy, done = 0, done + 1
        pts += [Point("shelf_items", on, t, lab("shelf")), Point("shelf_put_total", put, t, lab("chef")),
                Point("shelf_taken_total", taken, t, lab("shelf")), Point("baker_busy", busy, t, lab("baker")),
                Point("baker_done_total", done, t, lab("baker"))]
    store = FileMetrics(tmp_path / "m.jsonl")
    store.write(pts)
    m = discover(store.dump("", {"project": "p"}), start=t0, end=t0 + 3600, step=30)
    assert [s.series.name for s in m.stocks] == ["shelf_items"]
    assert any(k.startswith("baker_busy") and "flag" in why for k, why in m.discovery["left_out"].items()), m.discovery["left_out"]


def test_a_level_no_longer_written_is_left_out_not_a_reason_to_fit_nothing(tmp_path):
    store = FileMetrics(tmp_path / "m.jsonl")
    start, end = simulate(store, minutes=60)
    # an old machine's level, balanced by the same counters, that stopped being written a quarter
    # of an hour before the end: longer than a restart takes (a shorter silence may be one)
    pts = [Point("bakery_shelf_loaves", v, t, {"project": "p", "machine": "old_shop"})
           for t, v in [(p_t, p_v) for p_t, p_v in store.raw("bakery_shelf_loaves", {"project": "p", "machine": "shop"}, start=start, end=start + 2700)]]
    store.write(pts)
    m = discover(store.dump("", {"project": "p"}), start=start, end=end, step=30)
    assert m.flows and all(f.current() for f in m.flows)
    assert any("no longer written" in why for why in m.discovery["left_out"].values())


def test_two_counters_of_the_same_thing_are_one_flow(tmp_path):
    # Orchestra's count of an event and the machine's own count of it move together (here the
    # collector has not caught up with the last minute): both stocks the flow joins must use the same one, or the flow between them is lost
    store = FileMetrics(tmp_path / "m.jsonl")
    start, end = simulate(store, minutes=60)
    own = store.raw("bakery_loaves_baked_total", {"project": "p", "machine": "oven"}, start=start, end=end)
    changes = [(t, v) for i, (t, v) in enumerate(own) if i == 0 or v != own[i - 1][1]]     # written when an event comes, as Orchestra's collector does
    store.write([Point("orchestra_events_total", v, t, {"project": "p", "source": "oven", "type": "loaf.baked"}) for t, v in changes if t < end - 60])
    m = discover(store.dump("", {"project": "p"}), start=start, end=end, step=30)
    assert any(why.startswith("the same as bakery_loaves_baked_total") for k, why in m.discovery["left_out"].items() if k.startswith("orchestra_events_total"))
    assert not any(f.counter and f.counter.name == "orchestra_events_total" for f in m.flows)


def test_the_same_events_stamped_a_moment_later_are_still_one_flow(tmp_path):
    # Orchestra's count of an event is stamped a moment after the machine's own count, so near
    # a step's end it lands in the next step: many steps differ, the running totals never by more
    # than one event. Without this, discovery shares one flow's balance between the two.
    store = FileMetrics(tmp_path / "m.jsonl")
    start, end = simulate(store, minutes=60)
    own = store.raw("bakery_loaves_baked_total", {"project": "p", "machine": "oven"}, start=start, end=end)
    changes = [(t, v) for i, (t, v) in enumerate(own) if i == 0 or v != own[i - 1][1]]
    store.write([Point("orchestra_events_total", v, t + 29, {"project": "p", "source": "oven", "type": "loaf.baked"}) for t, v in changes])
    m = discover(store.dump("", {"project": "p"}), start=start, end=end, step=30)
    assert any(why.startswith("the same as bakery_loaves_baked_total") for k, why in m.discovery["left_out"].items() if k.startswith("orchestra_events_total"))
    assert not any(f.counter and f.counter.name == "orchestra_events_total" for f in m.flows)


def test_counters_of_a_machines_instances_are_summed_into_one_flow(tmp_path):
    # the shelf's loaves sold, counted by three instances of the shop (source shop/1..3) instead of one
    store = FileMetrics(tmp_path / "m.jsonl")
    start, end = simulate(store, minutes=60)
    sold = store.raw("bakery_loaves_sold_total", {"project": "p", "machine": "shop"}, start=start, end=end)
    rng = random.Random(5)
    per = {i: 0 for i in (1, 2, 3)}
    pts = []
    for (t0, a), (t1, b) in itertools.pairwise(sold):
        for _ in range(int(b - a)):
            per[rng.choice((1, 2, 3))] += 1
        pts += [Point("orchestra_events_total", per[i], t1, {"project": "p", "source": f"shop/{i}", "type": "loaf.sold"}) for i in per]
    store.write(pts)
    m = discover(store.dump("", {"project": "p"}), start=start, end=end, step=30)
    summed = [f for f in m.flows if f.measured_by and all(r.labels.get("source", "").startswith("shop/") for r in f.measured_by)]
    assert m.discovery["summed"], m.discovery.get("summed")
    if summed:                                           # when the sold flow is the summed one, it reads all three instances
        assert len(summed[0].measured_by) == 3 and summed[0].counter is None


def test_orchestras_own_series_are_plumbing(tmp_path):
    # the Core page's probes and the host's heartbeat land in the project's metrics store while
    # a browser is open; they measure Orchestra, not the system, and are no candidates. Its event
    # counters are: they count what the machines did.
    store = FileMetrics(tmp_path / "m.jsonl")
    start, end = simulate(store, minutes=60)
    store.write([Point("orchestra_core_bus_read_ms", 2.0 + (i % 3), start + 30 * i, {"project": "p"}) for i in range(120)]
                + [Point("orchestra_host_up", 1.0, start + 15 * i, {"project": "p", "machine": "orchestra-host"}) for i in range(240)])
    m = discover(store.dump("", {"project": "p"}), start=start, end=end, step=30)
    why = m.discovery["left_out"]
    assert why["orchestra_core_bus_read_ms"].startswith("Orchestra's own"), why
    assert why['orchestra_host_up{machine="orchestra-host"}'].startswith("Orchestra's own"), why
    assert counted(m) == {"bakery_shelf_loaves", "bakery_oven_orders_pending"}


def test_a_series_named_with_orchestras_prefix_is_left_out_with_why(tmp_path):
    store = FileMetrics(tmp_path / "m.jsonl")
    start, end = simulate(store, minutes=30)
    store.write([Point("orchestra_disk_free_bytes", 5e9 - i, start + 60 * i, {"project": "p", "machine": "telemetry"}) for i in range(30)]
                + [Point("orchestra_host_up", 1, start + 60 * i, {"project": "p", "machine": "orchestra-host"}) for i in range(30)])
    left_out = discover(store.dump("", {"project": "p"}), start=start, end=end, step=30).discovery["left_out"]
    assert "the orchestra_ prefix is Orchestra's own" in left_out['orchestra_disk_free_bytes{machine="telemetry"}']
    assert "rename it" in left_out['orchestra_disk_free_bytes{machine="telemetry"}']
    assert left_out['orchestra_host_up{machine="orchestra-host"}'].startswith("Orchestra's own")
