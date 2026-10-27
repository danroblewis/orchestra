"""What the checks against real sources found (2026-10-27): two services' pods in one region taken
for one stock during an outage; regions' turnover counters taken for the same events because
deploys reach every region in the same minutes; a publisher fitted as publishing faster the fuller
a queue its own messages fill; and a backlog its consumer keeps near empty left out of a fan-out."""

import random

from orchestra.sd.discover import discover
from orchestra.sd.series import Declared, series_key

T0 = 1_800_000_000.0


def _pods(rng: random.Random, minutes: int, base: int, deploys: list[int], outage: tuple[int, int] | None = None,
          surge: bool = False):
    """A count of pods written every minute, with its turnover: a deploy replaces one pod, one
    stopping and its replacement starting a minute later (or, with ``surge``, the replacement
    starting a minute before the old one stops), and an outage stops every pod and starts them
    again after."""
    pods, started, stopped = base, 0, 0
    level, st, sp = [], [], []
    for m in range(minutes):
        if m in (deploys if not surge else [d + 1 for d in deploys]):
            stopped, pods = stopped + 1, pods - 1
        if m in ([d + 1 for d in deploys] if not surge else deploys):
            started, pods = started + 1, pods + 1
        if outage and m == outage[0]:
            stopped, pods = stopped + pods, 0
        if outage and m == outage[1]:
            started, pods = started + base, base
        t = T0 + 60 * m
        level.append((t, float(pods)))
        st.append((t, float(started)))
        sp.append((t, float(stopped)))
    return level, st, sp


def _dump(groups: dict[tuple[str, str], tuple]) -> tuple[list, dict]:
    dump, kinds = [], {}
    for (service, region), (level, st, sp) in groups.items():
        lab = {"machine": service, "service": service, "region": region}
        for name, pts, kind in ((f"{service}_pods", level, "level"), (f"{service}_pods_started_total", st, "counter"),
                                (f"{service}_pods_stopped_total", sp, "counter")):
            dump.append((name, lab, pts))
            kinds[series_key(name, lab)] = Declared(kind)
    return dump, kinds


def test_two_services_pods_in_one_region_are_two_stocks_through_an_outage():
    # both run two pods in eu-west, and the region's outage takes both to none for half an hour:
    # their values agree almost always. Each is balanced exactly by its own turnover
    rng = random.Random(1)
    minutes = 470
    groups = {("authz", "eu-west"): _pods(rng, minutes, 2, sorted(rng.sample(range(10, 460), 5)), (200, 230)),
              ("checkout", "eu-west"): _pods(rng, minutes, 2, sorted(rng.sample(range(10, 460), 5)), (200, 230))}
    dump, kinds = _dump(groups)
    m = discover(dump, start=T0, end=T0 + 60 * minutes, step=60.0, kinds=kinds)
    assert {s.id for s in m.stocks} == {"authz_pods_eu_west_authz", "checkout_pods_eu_west_checkout"}, m.discovery["left_out"]


def test_regions_turnover_is_never_the_same_events_however_often_it_coincides():
    # a rolling deploy reaches every region in the same minute, so each region's starts and stops
    # come a minute apart at most; us-west starts the new pod first, so it holds two or three
    rng = random.Random(2)
    minutes = 470
    deploys = sorted(rng.sample(range(10, 460), 12))
    groups = {("authz", "us-east"): _pods(rng, minutes, 2, deploys),
              ("authz", "us-west"): _pods(rng, minutes, 2, deploys, surge=True)}
    dump, kinds = _dump(groups)
    m = discover(dump, start=T0, end=T0 + 60 * minutes, step=60.0, kinds=kinds)
    assert {s.id for s in m.stocks} == {"authz_pods_us_east_authz", "authz_pods_us_west_authz"}, m.discovery["left_out"]
    west = m.stock("authz_pods_us_west_authz")
    assert {b["series"] for b in west.evidence["balance"]} == {
        'authz_pods_started_total{machine="authz",region="us-west",service="authz"}',
        'authz_pods_stopped_total{machine="authz",region="us-west",service="authz"}'}


def _fanout(seed: int, minutes: int = 40, slow: float = 0.06, keep: float = 0.35):
    """A publisher into one channel whose rate swings with a twenty-minute day; three queues get
    every message. Two consumers keep up (their backlogs stay near empty); the third takes about
    ``slow`` a second, so its backlog fills at each peak. The broker is scraped every five seconds,
    each series a moment apart, and its queue lengths are a few seconds older than its counts."""
    rng = random.Random(seed)
    published, acked, backlog = 0, {"billing": 0, "shipping": 0, "analytics": 0}, {"billing": 0, "shipping": 0, "analytics": 0}
    pts = {("published_total", None): [], **{(n, q): [] for n in ("acked_total", "backlog") for q in backlog}}
    was = []                                    # the broker's queue statistics lag its message counts by a few seconds
    for i in range(minutes * 60):
        was.append(dict(backlog))
        day = (i % 1200) / 1200
        if rng.random() < (0.05 if day < 0.5 else 0.25):
            published += 1
            backlog = {q: v + 1 for q, v in backlog.items()}
        for q in backlog:
            if backlog[q] and rng.random() < (slow if q == "analytics" else keep):
                backlog[q] -= 1
                acked[q] += 1
        if i % 5 == 0:
            pts[("published_total", None)].append((T0 + i + 0.2, float(published)))
            for q in backlog:
                pts[("acked_total", q)].append((T0 + i + 0.4, float(acked[q])))
                pts[("backlog", q)].append((T0 + i + 0.7, float(was[max(0, i - 1)][q])))
    dump, kinds = [], {}
    for (name, q), p in pts.items():
        lab = {"exchange": "orders"} if q is None else {"queue": q, "machine": q}
        dump.append((name, lab, p))
        kinds[series_key(name, lab)] = Declared("counter" if name.endswith("_total") else "level", direction=(
            "out" if q is None else "in" if name == "acked_total" else "backlog"), channel="rabbit:orders")
    return dump, kinds


def test_a_fan_out_fills_every_backlog_even_one_kept_near_empty():
    # every consumer keeps up, so each backlog holds a message or two at most, and the queue
    # statistics' lag is most of how it moves from one step to the next
    dump, kinds = _fanout(5, slow=0.8, keep=0.8)
    m = discover(dump, start=T0, end=T0 + 2400, step=15.0, kinds=kinds)
    backlogs = {s.id for s in m.stocks if s.series and s.series.name == "backlog"}
    assert backlogs == {"backlog_billing", "backlog_shipping", "backlog_analytics"}, m.discovery["left_out"]
    pub = [f for f in m.flows if f.counter and f.counter.name == "published_total"]
    assert {f.dst for f in pub} == backlogs and sum("copy_of" in f.evidence for f in pub) == 2
    for s in m.stocks:
        assert s.evidence["balance_r2"] >= 0.9 > s.evidence["balance_r2_level"], "judged on the traffic through it"


def test_a_publisher_is_not_driven_by_a_queue_its_own_messages_fill():
    # every queue fills when the publisher's day peaks, so each looks like a cause of its rate
    dump, kinds = _fanout(4, minutes=60, slow=0.05)
    m = discover(dump, start=T0, end=T0 + 3600, step=15.0, kinds=kinds)
    pub = [f for f in m.flows if f.counter and f.counter.name == "published_total"]
    assert pub
    for f in pub:
        eq = f.current()
        assert not (eq.inputs and eq.inputs[0].removeprefix("input:").startswith("backlog") and eq.params.get("k", 0) > 0), (f.id, eq)


def test_a_level_that_follows_a_flow_does_not_drive_it():
    # a dashboard counts the orders of the last two minutes; orders come faster and slower through
    # a twenty-minute day nobody measures. The count is high after each rush began, and fits the
    # orders' rate as a cause would until the two are compared a minute apart
    import math

    rng = random.Random(9)
    orders = served = waiting = 0
    times, pts_o, pts_s, pts_w, pts_y = [], [(T0, 0.0)], [(T0, 0.0)], [(T0, 0.0)], []
    for i in range(7200):
        t = T0 + i
        if rng.random() < 0.2 + 0.18 * math.sin(2 * math.pi * i / 1200):
            orders, waiting = orders + 1, waiting + 1
            times.append(t)
            pts_o.append((t, float(orders)))
            pts_w.append((t, float(waiting)))
        if waiting and rng.random() < 0.3:
            served, waiting = served + 1, waiting - 1
            pts_s.append((t, float(served)))
            pts_w.append((t, float(waiting)))
        if i % 5 == 0:
            pts_y.append((t + 0.5, float(sum(1 for x in times[-200:] if x > t - 120))))
    shop = {"machine": "shop"}
    dump = [("orders_total", shop, pts_o), ("served_total", shop, pts_s), ("orders_waiting", shop, pts_w),
            ("recent_orders", {"machine": "dashboard"}, pts_y)]
    m = discover(dump, start=T0, end=T0 + 7200, step=5.0)
    [f] = [f for f in m.flows if f.counter and f.counter.name == "orders_total"]
    assert "input:recent_orders" not in f.current().inputs, f.current()
