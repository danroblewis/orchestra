"""Which form a flow gets, and which stocks may drive it: a second parameter must earn its
place, a rate may not be negative at a level the stock held, and a stock whose counter records
the flow's events after the fact may still drive it."""

import math
import random

from orchestra.metrics import Point
from orchestra.metrics.file import FileMetrics
from orchestra.sd.discover import AIC_MARGIN, Path, Series, discover, fit_flow
from orchestra.sd.drivers import co_counting, leads

T0 = 1_800_000_000.0
LIVE = [(T0, T0 + 3600)]


def poisson_events(rng, rate_per_min, level=None):
    """Events over an hour, one per second at most, at ``rate_per_min`` (times ``level(t)``)."""
    out = []
    for i in range(3600):
        if rng.random() < rate_per_min * (level(T0 + i) if level else 1.0) / 60:
            out.append((T0 + i, 1.0))
    return out


def test_a_constant_stream_beside_an_uncorrelated_flag_stays_constant():
    # a flag that flips every minute or so has nothing to do with the stream: the linear form in it
    # fits a little better by chance, never by the margin a second parameter must earn
    rng = random.Random(3)
    flag = Path.of([(T0 + i, float((i // rng.randint(40, 90)) % 2)) for i in range(0, 3600, 7)], LIVE, 60.0)
    forms = fit_flow(poisson_events(rng, 6.0), 60.0, {"flag": flag}, None, {"flag"})
    assert forms[0]["form"] == "constant", [(f["form"], round(f["aic"], 2)) for f in forms]
    linear = next(f for f in forms if f["form"] == "linear")
    assert linear["aic"] > forms[0]["aic"] - AIC_MARGIN


def test_one_event_per_level_unit_is_proportional_not_linear_with_a_negative_intercept():
    rng = random.Random(4)
    level = lambda t: 1.0 + ((t - T0) // 600) % 4        # 1, 2, 3, 4 and round again, ten minutes each
    stock = Path.of([(T0 + i, level(T0 + i)) for i in range(0, 3600, 5)], LIVE, 60.0)
    forms = fit_flow(poisson_events(rng, 2.0, level), 60.0, {"s": stock}, "s", {"s"})
    assert forms[0]["form"] == "proportional", [(f["form"], f["params"], round(f["aic"], 2)) for f in forms]
    assert abs(forms[0]["params"]["k"] - 2.0) < 0.5


def test_a_line_below_zero_where_the_stock_barely_was_is_rejected():
    # the stock is at 1 for a minute of the hour, during which, by chance, nothing arrived; the
    # best line in it is negative at 1, which the data had no chance to show (a tenth of an event
    # was due in that minute): rejected, with the reason, and the constant chosen
    rng = random.Random(5)
    at_one = set(range(1800, 1860))
    stock = Path.of([(T0 + i, 1.0 if i in at_one else 0.0) for i in range(0, 3600, 5)], LIVE, 60.0)
    events = [(T0 + i, 1.0) for i in range(3600) if i not in at_one and rng.random() < 0.1 / 60]
    forms = fit_flow(events, 60.0, {"s": stock}, None, {"s"})
    linear = next(f for f in forms if f["form"] == "linear")
    assert linear["params"]["k"] < 0 and "below zero from level 1" in linear["rejected"], linear
    assert forms[0]["form"] == "constant" and forms[-1] is linear


def test_a_line_below_zero_where_the_stock_stayed_long_is_a_measured_floor():
    # the stock is at 2 for half the hour and nothing arrives then (a full shelf: no order), at
    # 0 the rest and arrivals come steadily: the line is negative at 2, and the data showed it
    rng = random.Random(6)
    at_two = {i for i in range(3600) if (i // 300) % 2}
    stock = Path.of([(T0 + i, 2.0 if i in at_two else 0.0) for i in range(0, 3600, 5)], LIVE, 60.0)
    events = [(T0 + i, 1.0) for i in range(3600) if i not in at_two and rng.random() < 6.0 / 60]
    forms = fit_flow(events, 60.0, {"s": stock}, None, {"s"})
    assert forms[0]["form"] == "linear" and forms[0]["params"]["k"] < 0 and "rejected" not in forms[0]


def series(name, deltas, machine="m"):
    values = [0.0]
    for d in deltas:
        values.append(values[-1] + d)
    return Series(name, {"machine": machine}, [], values, True)


def test_a_counter_leads_another_when_its_events_fall_in_the_earlier_step():
    steps = list(range(8))
    a = series("a", [1, 0, 1, 0, 1, 0, 1, 0])
    b = series("b", [0, 1, 0, 1, 0, 1, 0, 1])
    assert leads(a, b, steps) and not leads(b, a, steps)
    same = series("c", [1, 0, 1, 0, 1, 0, 1, 0])
    assert leads(a, same, steps) and leads(same, a, steps)      # the same step: at, which counts as leading


def test_a_stock_whose_counter_records_the_flows_events_afterwards_may_drive_it():
    # a reviewer starts on what waits (the flow), and the scheduler records the ticket leaving the
    # queue a moment later (the stock's counter, a part of the flow's events): the queue drives the
    # flow. Stamped first, the queue's counter would be the flow's cause reversed, and barred.
    steps = list(range(20))
    flow = series("turns_started_total", [1, 0, 1, 1, 0, 1, 0, 1, 1, 0, 1, 0, 1, 1, 0, 1, 0, 1, 1, 0], "reviewer")
    after = series("left_queue_total", [1, 0, 1, 0, 1, 1, 0, 1, 1, 0, 1, 0, 1, 1, 0, 1, 0, 1, 1, 0], "scheduler")    # the fourth a step later
    before = series("left_queue_total", [1, 1, 0, 1, 0, 1, 0, 1, 1, 0, 1, 0, 1, 1, 0, 1, 0, 1, 1, 0], "scheduler")   # the second a step earlier
    queue = Series("queue", {"machine": "scheduler"}, [], [0.0] * 21, False)
    same_flow = lambda a, b: False
    assert co_counting(flow, None, "working", [(queue, [(after, -1)], 1.0, 1.0)], {queue.key: "queue"}, steps, same_flow) == {}
    barred = co_counting(flow, None, "working", [(queue, [(before, -1)], 1.0, 1.0)], {queue.key: "queue"}, steps, same_flow)
    assert "leads them" in barred["queue"]


def test_a_counter_of_the_same_events_is_recorded_on_the_flow_that_stands_for_it(tmp_path):
    # the scheduler stamps "review → approved" and "approved → done" at the same instant: one flow,
    # measured twice; the kept counter's flow records the other, so a reader sees both label sets
    rng = random.Random(6)
    lab = lambda **kw: {"project": "p", "machine": "scheduler", **kw}
    review = done = moved = sent = 0
    pts = []
    for i in range(3600):
        t = T0 + i
        if rng.random() < 0.1:
            review, sent = review + 1, sent + 1
        if review and rng.random() < 0.08:
            review, done, moved = review - 1, done + 1, moved + 1
        pts += [Point("tickets", review, t, lab(state="review")), Point("tickets", done, t, lab(state="done")),
                Point("transitions_total", sent, t, lab(**{"from": "ready", "to": "review"})),
                Point("transitions_total", moved, t, lab(**{"from": "review", "to": "approved"})),
                Point("transitions_total", moved, t, lab(**{"from": "approved", "to": "done"}))]
    store = FileMetrics(tmp_path / "m.jsonl")
    store.write(pts)
    m = discover(store.dump("", {"project": "p"}), start=T0, end=T0 + 3600, step=30)
    [f] = [f for f in m.flows if f.counter.labels["to"] in ("approved", "done")]
    assert f.src == "tickets_review" and f.dst == "tickets_done"
    [other] = f.evidence["same_as"]
    assert {other["labels"]["from"], f.counter.labels["from"]} == {"review", "approved"}
    assert any(v.startswith("the same as") for v in m.discovery["left_out"].values())
    assert math.isfinite(f.current().quality["aic"])
