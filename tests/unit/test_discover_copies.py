"""Copies: one counter that fills several stocks at once (a fanout exchange's published count fills
every bound queue's backlog) is one flow per stock it fills, not a split and not a contest."""

import random

from orchestra.metrics import Point
from orchestra.metrics.file import FileMetrics
from orchestra.sd.discover import discover
from orchestra.sd.series import Declared

T0 = 1_800_000_000.0


def fanout(store, minutes: int = 60, seed: int = 3):
    """A producer publishes into an exchange at about 12 a minute; three queues are bound to it,
    each with its own consumer: two keep up, the third (analytics) takes about 10 a minute, so its
    backlog grows. Each queue's backlog is written by the broker every second."""
    rng = random.Random(seed)
    published, acked = 0, {"billing": 0, "shipping": 0, "analytics": 0}
    backlog = dict.fromkeys(acked, 0)
    rate = {"billing": 0.5, "shipping": 0.3, "analytics": 10 / 60}     # per waiting message per second, or per second for analytics
    pts = []
    for i in range(minutes * 60):
        t = T0 + i
        if rng.random() < 12 / 60:
            published += 1
            for q in backlog:
                backlog[q] += 1
        for q in backlog:
            p = rate[q] if q == "analytics" else rate[q] * min(backlog[q], 1)
            if backlog[q] and rng.random() < p:
                backlog[q] -= 1
                acked[q] += 1
        pts.append(Point("published_total", published, t, {"project": "p", "exchange": "orders"}))
        for q in backlog:
            pts.append(Point("acked_total", acked[q], t, {"project": "p", "queue": q, "machine": q}))
            pts.append(Point("backlog", backlog[q], t, {"project": "p", "queue": q, "machine": q}))
    store.write(pts)
    return T0, T0 + minutes * 60


def test_a_counter_that_fills_three_backlogs_is_a_flow_and_two_copies(tmp_path):
    store = FileMetrics(tmp_path / "m.jsonl")
    start, end = fanout(store)
    m = discover(store.dump("", {"project": "p"}), start=start, end=end, step=15)
    assert m.check() == []
    backlogs = {s.id for s in m.stocks if s.series and s.series.name == "backlog"}
    assert len(backlogs) == 3, m.discovery["left_out"]
    pub = [f for f in m.flows if f.counter and f.counter.name == "published_total"]
    assert len(pub) == 3 and {f.dst for f in pub} == backlogs and all(f.src is None for f in pub)
    main = next(f for f in pub if "copy_of" not in f.evidence)
    copies = [f for f in pub if f is not main]
    assert sorted(main.evidence["copies"]) == sorted(f.id for f in copies)
    assert all(f.evidence["copy_of"] == main.id and f.id == f"{main.id}>{f.dst}" for f in copies)
    assert all(f.current().params == main.current().params for f in copies)     # one count, one rate
    # each backlog is drained by its own consumer's acks
    for s in backlogs:
        [out] = [f for f in m.flows if f.src == s]
        assert out.counter.name == "acked_total" and out.counter.labels["queue"] in s



def test_a_backlog_is_balanced_by_its_own_channel_before_a_stand_in(tmp_path):
    # shipping keeps up, so its acks run a moment behind the publishes: as good a balance for any
    # backlog of the channel as the publishes. Told what each count is (counted traffic), discovery
    # balances each backlog with what was produced into its channel, less its own consumer's acks.
    store = FileMetrics(tmp_path / "m.jsonl")
    rng = random.Random(11)
    pub, acked, backlog = 0, {"shipping": 0, "analytics": 0}, {"shipping": 0, "analytics": 0}
    pts = []
    for i in range(3600):
        t = T0 + i
        if rng.random() < 0.3 * (1 + 0.8 * (i // 600 % 2)):        # quiet and busy ten-minute spells
            pub += 1
            backlog = {q: v + 1 for q, v in backlog.items()}
        if backlog["shipping"]:                                     # takes each as it comes
            backlog["shipping"] -= 1
            acked["shipping"] += 1
        if backlog["analytics"] and rng.random() < 0.35:            # about 21 a minute: behind when busy
            backlog["analytics"] -= 1
            acked["analytics"] += 1
        pts.append(Point("published_total", pub, t, {"project": "p", "exchange": "orders"}))
        for q in backlog:
            pts.append(Point("acked_total", acked[q], t, {"project": "p", "queue": q, "machine": q}))
            pts.append(Point("backlog", backlog[q], t, {"project": "p", "queue": q, "machine": q}))
    store.write(pts)
    kinds = {'published_total{exchange="orders"}': Declared("counter", direction="out", channel="orders")}
    for q in backlog:
        kinds[f'acked_total{{machine="{q}",queue="{q}"}}'] = Declared("counter", direction="in", channel="orders")
        kinds[f'backlog{{machine="{q}",queue="{q}"}}'] = Declared("level", direction="backlog", channel="orders")
    m = discover(store.dump("", {"project": "p"}), start=T0, end=T0 + 3600, step=15, kinds=kinds)
    [stock] = [s for s in m.stocks if s.series.labels.get("queue") == "analytics"]
    terms = {(x["series"].split("{")[0], x["sign"]) for x in stock.evidence["balance"]}
    assert terms == {("published_total", 1), ("acked_total", -1)}, stock.evidence["balance"]
    assert any('machine="analytics"' in x["series"] for x in stock.evidence["balance"] if x["sign"] < 0)


def test_two_backlogs_one_consumer_empties_at_once_are_two_stocks(tmp_path):
    # billing takes from two queues and acknowledges both in one batch every 20 s: the backlogs
    # rise and fall together, but they are two queues, filled from two channels
    store = FileMetrics(tmp_path / "m.jsonl")
    rng = random.Random(4)
    pub, acked, backlog = {"orders": 0, "payments": 0}, {"orders": 0, "payments": 0}, {"orders": 0, "payments": 0}
    rate = {"orders": 0.9, "payments": 0.6}
    pts = []
    for i in range(3600):
        t = T0 + i
        for q, r in rate.items():
            if rng.random() < r * (1.5 if i // 300 % 2 else 0.5):
                pub[q] += 1
                backlog[q] += 1
            if i % 20 == 19:
                acked[q] += backlog[q]
                backlog[q] = 0
            pts.append(Point("published_total", pub[q], t, {"project": "p", "exchange": q}))
            pts.append(Point("acked_total", acked[q], t, {"project": "p", "queue": q, "machine": "billing"}))
            pts.append(Point("backlog", backlog[q], t, {"project": "p", "queue": q, "machine": "billing"}))
    store.write(pts)
    kinds = {}
    for q in pub:
        kinds[f'published_total{{exchange="{q}"}}'] = Declared("counter", direction="out", channel=q)
        kinds[f'acked_total{{machine="billing",queue="{q}"}}'] = Declared("counter", direction="in", channel=q)
        kinds[f'backlog{{machine="billing",queue="{q}"}}'] = Declared("level", direction="backlog", channel=q)
    m = discover(store.dump("", {"project": "p"}), start=T0, end=T0 + 3600, step=15, kinds=kinds)
    assert {s.series.labels["queue"] for s in m.stocks} == {"orders", "payments"}, m.discovery["left_out"]
