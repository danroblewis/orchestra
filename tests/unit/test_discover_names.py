"""A stock's id and name leave out label values with nothing to say (RabbitMQ's vhost ``/``)."""

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
