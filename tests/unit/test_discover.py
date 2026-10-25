"""Discovery finds a system's stocks, flows, equations and machines from its metrics alone.

The system is the bakery in examples/bakery, simulated here without sleeping so the right
answer is known: the rates below."""

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


def simulate(store, minutes=90, seed=1, t0=1_800_000_000.0):
    rng = random.Random(seed)
    lab = lambda m: {"project": "p", "machine": m}
    shelf = pending = 0
    baked = filled = sold = stale = ordered = 0
    temp, last_order = 15.0, -1e9
    pts = []
    for i in range(minutes * 60):
        t, dt = t0 + i, 1 / 60
        base = DAY if (i // (SHIFT_MIN * 60)) % 2 == 0 else NIGHT     # the oven's shifts
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
    assert "weather_temperature_celsius" in m.discovery["left_out"], "the unrelated series is left out"
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

    machines = {mc.id: set(mc.attributed) for mc in m.machines}
    assert machines["oven"] == {"bakery_loaves_baked_total", "bakery_orders_filled_total"}
    assert machines["shop"] == {"bakery_loaves_sold_total", "bakery_loaves_discarded_total", "bakery_loaves_ordered_total"}
    assert "weather" not in machines


def test_nothing_to_find_in_noise(tmp_path):
    store = FileMetrics(tmp_path / "m.jsonl")
    rng = random.Random(1)
    store.write([Point("noise_level", rng.random(), 1_800_000_000 + i, {"project": "p"}) for i in range(600)]
                + [Point("noise_total", i // 7, 1_800_000_000 + i, {"project": "p"}) for i in range(600)])
    m = discover(store.dump("", {"project": "p"}), start=1_800_000_000, end=1_800_000_600, step=10)
    assert m.stocks == [] and m.flows == []
    assert set(m.discovery["left_out"]) == {"noise_level", "noise_total"}
