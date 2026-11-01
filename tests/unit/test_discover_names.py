"""A stock's id and name leave out label values with nothing to say (RabbitMQ's vhost ``/``), and
values another value already says (a queue named for its consumer and exchange)."""

import random

from orchestra.sd.discover import discover

T0 = 1_800_000_000.0


def test_a_vhost_of_slash_is_not_in_a_stocks_id_or_name():
    rng = random.Random(2)
    lab = {"machine": "rabbit.billing", "queue": "orders", "vhost": "/"}
    level, ins, outs = [0], [0], [0]
    for _ in range(240):
        a, b = rng.randint(0, 3), rng.randint(0, 2) if level[-1] > 2 else 0
        ins.append(ins[-1] + a)
        outs.append(outs[-1] + b)
        level.append(level[-1] + a - b)
    pts = lambda vs: [(T0 + 60 * i, float(v)) for i, v in enumerate(vs)]
    dump = [("backlog", lab, pts(level)), ("published_total", lab, pts(ins)), ("acked_total", lab, pts(outs))]
    m = discover(dump, start=T0, end=T0 + 240 * 60, step=60.0)
    assert [(s.id, s.name) for s in m.stocks] == [("backlog_orders", "backlog (orders)")]
    assert all(not f.id.endswith("_") for f in m.flows), [f.id for f in m.flows]


def test_a_queue_named_for_its_consumer_and_exchange_is_said_once():
    rng = random.Random(3)
    lab = {"machine": "rabbit.analytics", "consumer": "analytics", "exchange": "clicks", "queue": "analytics.clicks", "vhost": "/"}
    level, ins, outs = [0], [0], [0]
    for _ in range(240):
        a, b = rng.randint(0, 3), rng.randint(0, 2) if level[-1] > 2 else 0
        ins.append(ins[-1] + a)
        outs.append(outs[-1] + b)
        level.append(level[-1] + a - b)
    pts = lambda vs: [(T0 + 60 * i, float(v)) for i, v in enumerate(vs)]
    dump = [("backlog", lab, pts(level)), ("published_total", lab, pts(ins)), ("acked_total", lab, pts(outs))]
    m = discover(dump, start=T0, end=T0 + 240 * 60, step=60.0)
    assert [(s.id, s.name) for s in m.stocks] == [("backlog_analytics_clicks", "backlog (analytics.clicks)")]


def test_a_series_that_names_a_step_is_named_by_it_and_its_place():
    """The owner (2026-11-01) read the pile ``write.held`` as a disk write: a series that names a
    ``step`` and its ``place`` there is named by them, then by what they do not spell."""
    rng = random.Random(4)
    lab = {"instrument": "piles", "workflow": "delivery_sail", "pile": "write.held", "step": "write", "place": "held"}
    move = {"instrument": "piles", "workflow": "delivery_sail"}
    level, ins, outs = [0], [0], [0]
    for _ in range(240):
        a, b = rng.randint(0, 3), rng.randint(0, 2) if level[-1] > 2 else 0
        ins.append(ins[-1] + a)
        outs.append(outs[-1] + b)
        level.append(level[-1] + a - b)
    pts = lambda vs: [(T0 + 60 * i, float(v)) for i, v in enumerate(vs)]
    dump = [("workflow_pile_items", lab, pts(level)),
            ("workflow_pile_moves_total", {**move, "from": "write.waiting", "to": "write.held"}, pts(ins)),
            ("workflow_pile_moves_total", {**move, "from": "write.held", "to": "open_pr.waiting"}, pts(outs))]
    m = discover(dump, start=T0, end=T0 + 240 * 60, step=60.0)
    assert [(s.id, s.name) for s in m.stocks] == [("workflow_pile_items_write_held_delivery_sail", "write (held) · delivery_sail")]


def test_a_series_of_the_age_view_is_the_age_of_its_place_never_its_name():
    from orchestra.sd.discover import _title
    from orchestra.sd.series import Series

    lab = {"workflow": "delivery_sail", "pile": "write.held", "step": "write", "place": "held"}
    pile, age = Series("workflow_pile_items", lab, [], [], False), Series("workflow_pile_oldest_seconds", lab, [], [], False)
    prov = {age.key: {"source": "own", "instrument": "piles", "view": "age"}}
    assert _title(pile, prov) == "write (held) · delivery_sail"
    assert _title(age, prov) == "age of write (held) · delivery_sail"
