"""Which series drives a flow's rate (sd.driverchoice): the search is priced, a driver that stands in
for time, that does not carry from one half of the window to the other, or that explains as much
read far from the events is refuted, and ties go to the series nearest the flow."""

import math
import random

from orchestra.sd.discover import Path, fit_flow
from orchestra.sd.driverchoice import adjacency

T0 = 1_800_000_000.0
LIVE = [(T0, T0 + 3600)]


def events_at(rng, rate):
    """Events over an hour, at most one a second, at ``rate(t)`` per minute."""
    return [(T0 + i, 1.0) for i in range(3600) if rng.random() < rate(T0 + i) / 60]


def gauge(values_at):
    return Path.of([(T0 + i, values_at(T0 + i)) for i in range(0, 3600, 15)], LIVE, 60.0)


def switching(rng, low=1.0, high=4.0, hold=(60, 300)):
    """A level that jumps between two values at random times: a demand that comes and goes."""
    out, t, v = [], 0, low
    while t < 3600:
        d = rng.randint(*hold)
        out.append((t, v))
        t += d
        v = high if v == low else low
    return lambda t: next(val for start, val in reversed(out) if start <= t - T0)


def test_a_driver_that_sets_the_rate_is_chosen_and_its_evidence_kept():
    rng = random.Random(1)
    demand = switching(rng)
    forms = fit_flow(events_at(rng, lambda t: 2.0 * demand(t)), 60.0, {"input:demand": gauge(demand)}, None, {"input:demand"})
    best = forms[0]
    assert best["inputs"] == ["input:demand"], best["driver"]
    ev = best["driver"]
    assert ev["chosen"] == "input:demand" and ev["tried"] == 2 and ev["gain"] >= ev["price"] and ev["over_trend"] >= ev["price"]
    assert "shifted" in ev


def test_a_hundred_unrelated_series_buy_no_driver():
    # a steady stream beside a hundred random walks: the best of them beats the constant by chance,
    # and pays for being the best of two hundred forms
    rng = random.Random(2)
    walks = {}
    for j in range(100):
        x, pts = 0.0, []
        for i in range(0, 3600, 15):
            x += rng.gauss(0, 1)
            pts.append((T0 + i, 10 + x))
        walks[f"input:w{j}"] = Path.of(pts, LIVE, 60.0)
    forms = fit_flow(events_at(rng, lambda t: 5.0), 60.0, walks, None, set(walks))
    assert forms[0]["inputs"] == [], forms[0]["driver"]
    assert forms[0]["driver"]["tried"] == 200 and forms[0]["driver"]["price"] > 2 + 2 * math.log(199)


def test_a_series_that_only_follows_the_clock_is_refuted_as_time():
    # the rate falls all hour, and so does a gauge that has nothing to do with it (free disk
    # filling up): it fits, and a steady trend in time fits as well; the flow keeps its own form
    rng = random.Random(3)
    disk = gauge(lambda t: 1000.0 - 0.05 * (t - T0) + rng.gauss(0, 0.5))
    forms = fit_flow(events_at(rng, lambda t: 5.0 - 4.0 * (t - T0) / 3600), 60.0, {"input:disk": disk}, None, {"input:disk"})
    assert forms[0]["inputs"] == [], forms[0]["driver"]
    assert all("a steady trend in time explains the events as well" in r["why"] for r in forms[0]["driver"]["refuted"])
    assert forms[0]["driver"]["why"].startswith("rate not explained")


def test_a_driver_that_does_not_carry_to_the_other_half_is_refuted():
    # in the first half the rate follows the gauge closely, in the second it ignores it: on the
    # whole window the gauge pays for itself, and fitted on the first half it predicts the second
    # worse than the flow's own constant does
    rng = random.Random(4)
    level = switching(rng, low=0.0, high=1.0, hold=(60, 200))
    rate = lambda t: (0.5 + 8.0 * level(t)) if t < T0 + 1800 else 3.0  # noqa: E731
    forms = fit_flow(events_at(rng, rate), 60.0, {"input:x": gauge(level)}, None, {"input:x"})
    ev = forms[0]["driver"]
    assert forms[0]["inputs"] == [] and ev["beat_price"] >= 1, ev
    assert any("the other half" in r["why"] for r in ev["refuted"]), ev


def test_of_two_drivers_alike_the_one_nearest_the_flow_is_chosen():
    rng = random.Random(5)
    demand = switching(rng)
    near = gauge(demand)
    far = Path.of([(t, v * 1.0001) for t, v in zip(near.times, near.values)], LIVE, 60.0)
    events = events_at(rng, lambda t: 2.0 * demand(t))
    forms = fit_flow(events, 60.0, {"input:far": far, "input:near": near}, None, {"input:far", "input:near"},
                     near={"input:near": 3, "input:far": 0})
    assert forms[0]["inputs"] == ["input:near"], forms[0]["driver"]
    assert forms[0]["driver"]["tie_break"]["adjacency"] == {"input:far": 0, "input:near": 3} or \
        set(forms[0]["driver"]["tie_break"]["among"]) == {"input:far", "input:near"}


def test_adjacency_counts_a_shared_service_and_words_not_who_wrote_it():
    a = ("orders_consumed_total", {"service": "worker", "instance": "a", "job": "x"})
    b = ("orders_lag", {"service": "worker", "instance": "b", "job": "y"})
    c = ("node_filesystem_avail_bytes", {"instance": "a", "job": "x"})
    assert adjacency(*a, *b, same_unit=False) == 2         # the service, and "orders"
    assert adjacency(*a, *c, same_unit=False) == 0


def test_an_outflow_fitted_as_falling_while_its_stock_climbed_steadily_keeps_its_plain_form():
    # the stock climbs all hour because what drains it slowed: a line in the stock, falling, fits
    # the drain as well as the steady trend in time does, and run forward would run away
    rng = random.Random(6)
    stock = gauge(lambda t: 1000.0 + 2.0 * (t - T0))
    events = events_at(rng, lambda t: 10.0 - 6.0 * (t - T0) / 3600)
    forms = fit_flow(events, 60.0, {"s": stock}, "s", {"s"})
    assert forms[0]["form"] != "linear", (forms[0]["form"], forms[0]["driver"])
    line = next(f for f in forms if f["form"] == "linear")
    assert "trend in time" in line.get("refuted", "") or "rejected" in line, line
