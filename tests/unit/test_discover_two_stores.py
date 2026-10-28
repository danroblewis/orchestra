"""A stock whose level and flows come from two stores at different resolutions, the late tail of the
slower store, two stocks whose changes correlate but whose levels differ, and stocks the operator
declared. The fixture is the metrics lab's (reports/03-live-supervisor.md, check 4): the email
queue read every 15 s from one store with its publishes, the emails sent counted in a second store
once a minute, about a minute late, everything read every 30 s; and two warehouses drained in
proportion to one order stream."""

import json
import random
from pathlib import Path

from orchestra.sd.discover import Series, discover, levels_match
from orchestra.sd.live import arrived
from orchestra.sd.resolution import counted_every
from orchestra.sd.series import Declared, sample, series_key
from orchestra.sources.spec import load

DATA = json.loads((Path(__file__).parent / "data" / "two_stores.json").read_text())
T0 = 1_800_000_000.0
LEVEL, PUB, SENT = "shop:email_queue_backlog", "shop:email_queue_published", "biz:emails_sent"


def _reading(names=None, stock: dict | None = None):
    dump, kinds = [], {}
    for s in DATA["series"]:
        if names and s["name"] not in names:
            continue
        dump.append((s["name"], {}, [(T0 + t, v) for t, v in s["points"]]))
        kinds[s["name"]] = Declared(s["kind"], baseline=s["baseline"])
    prov = {k: {"stock": v} for k, v in (stock or {}).items()}
    return dump, kinds, prov


def _discover(names=None, stock=None):
    dump, kinds, prov = _reading(names, stock)
    w = DATA["end"] - DATA["start"]
    return discover(dump, start=T0, end=T0 + w, step=DATA["step"], kinds=kinds, provenance=prov)


def test_a_counter_reported_once_a_minute_and_read_every_30_s_is_known_by_its_moves():
    sent = next(s for s in DATA["series"] if s["name"] == SENT)
    pts = [(T0 + t, v) for t, v in sent["points"]]
    assert counted_every(pts, 30.0) == 60.0
    pub = next(s for s in DATA["series"] if s["name"] == PUB)
    assert counted_every([(T0 + t, v) for t, v in pub["points"]], 30.0) is None       # moves at every read
    rng, total, rare = random.Random(1), 0.0, []
    for i in range(120):                                                               # rare events, no schedule
        total += rng.random() < 0.2
        rare.append((T0 + 30 * i, total))
    assert counted_every(rare, 30.0) is None


def test_the_slower_store_s_newest_steps_are_missing_not_zero():
    # the second store is read 90 s before the window's end: its counts there have not arrived, so
    # a balance it is in is judged only up to its last observation, never on steps where it reads
    # as no emails sent; one it is not in keeps every step
    dump, kinds, _ = _reading()
    w = DATA["end"] - DATA["start"]
    n = int(w // DATA["step"])
    by = {s.key: s for s in sample(dump, T0, DATA["step"], n, kinds)}
    sent, level, pub = by[SENT], by[LEVEL], by[PUB]
    assert sent.until <= T0 + w - 90 and level.until is None and sent.blocks   # a slow counter: its counts arrive every other step
    steps = list(range(n))
    assert max(arrived(steps, [level, pub, sent], T0, DATA["step"])) < n - 3
    assert arrived(steps, [level, pub], T0, DATA["step"]) == steps


def test_a_queue_is_balanced_by_its_publishes_and_the_other_store_s_sends():
    # on single steps the sends come two minutes' worth at a time (R² −0.98 before); on the stretches
    # between the sends' writes the queue's change is the publishes less the sends, but for a few
    # seconds of timing either way, which cancel from one minute to the next
    m = _discover([LEVEL, PUB, SENT, "shop:email_dlq_published"])
    st = next(s for s in m.stocks if s.series and s.series.name == LEVEL)
    assert {(b["series"], b["sign"]) for b in st.evidence["balance"]} == {(PUB, 1), (SENT, -1)}
    assert st.evidence["balance_on"].startswith("the stretches between the writes of its slowest series")
    idn = st.evidence["identification"]
    assert idn["misses_rho"] <= -0.3 and idn["cum_residual_ratio"] < 0.05 and idn["p_null"] <= 0.2


def test_two_warehouses_drained_by_one_order_stream_are_two_stocks():
    # their changes correlate by 1.00, but one holds 1.25 M units and the other 0.8 M, and they
    # lose 0.6 and 0.4 of the picks: the levels do not match, so neither is the other measured twice
    m = _discover(["biz:inventory_units_ams", "biz:inventory_units_fra", "biz:orders_shipped", SENT])
    ids = {s.series.name for s in m.stocks if s.series}
    assert ids == {"biz:inventory_units_ams", "biz:inventory_units_fra"}, m.discovery["left_out"]
    dump, kinds, _ = _reading(["biz:inventory_units_ams", "biz:inventory_units_fra"])
    a, b = sample(dump, T0, 30.0, 120, kinds)
    assert not levels_match(a, b)


def test_levels_that_match_are_one_stock_whatever_their_balances():
    # a copy a step behind (now and then) and a copy three items apart both read as the level
    rng = random.Random(4)
    vals, v = [], 50.0
    for _ in range(121):
        v += rng.choice([-2, -1, 0, 1, 2])
        vals.append(v)
    a = Series("a", {}, [], vals, False)
    behind = Series("b", {}, [], [vals[i - 1] if i % 7 == 0 and i else x for i, x in enumerate(vals)], False)
    apart = Series("c", {}, [], [x + 3 for x in vals], False)
    double = Series("d", {}, [], [2 * x for x in vals], False)
    assert levels_match(a, behind) and levels_match(a, apart) and not levels_match(a, double)


def test_a_declared_stock_is_tried_first_and_judged_like_any():
    roles = {LEVEL: {"name": "email_queue", "role": "level"}, PUB: {"name": "email_queue", "role": "inflow"},
             SENT: {"name": "email_queue", "role": "outflow"}}
    m = _discover([LEVEL, PUB, SENT, "shop:email_dlq_published"], roles)
    st = next(s for s in m.stocks if s.series and s.series.name == LEVEL)
    assert st.evidence["declared"]["origin"] == "declared" and st.evidence["declared"]["stock"] == "email_queue"
    assert st.evidence["identification"]["pinned"] is True
    assert any("declared in [[series]]" in w for w in st.evidence["trust"]["why"])
    assert m.discovery["declared"]["stocks"]["email_queue"]["outcome"] == "a stock"


def test_a_declared_stock_that_does_not_fit_is_searched_and_says_so():
    # the dead letters are declared as the queue's outflow: they do not balance it, so the queue is
    # searched like any level, and finds its balance
    roles = {LEVEL: {"name": "email_queue", "role": "level"}, "shop:email_dlq_published": {"name": "email_queue", "role": "outflow"}}
    m = _discover([LEVEL, PUB, SENT, "shop:email_dlq_published"], roles)
    st = next(s for s in m.stocks if s.series and s.series.name == LEVEL)
    assert "declared" not in st.evidence and {b["series"] for b in st.evidence["balance"]} == {PUB, SENT}
    roles = {LEVEL: {"name": "email_queue", "role": "level"}, "shop:email_dlq_published": {"name": "email_queue", "role": "outflow"}}
    m = _discover([LEVEL, "shop:email_dlq_published"], roles)
    why = m.discovery["left_out"][LEVEL]
    assert "the balance declared for stock email_queue" in why, why


def test_series_declare_a_stock_s_level_and_flows():
    base = {"sources": [{"name": "work", "url": "http://127.0.0.1:9"}]}
    ok = load({**base, "series": [
        {"source": "work", "name": "backlog", "query": "q", "kind": "level", "stock": "email", "role": "level"},
        {"source": "work", "name": "sent", "query": "q", "kind": "counter", "stock": "email", "role": "outflow"}]}, Path("."))
    assert [d.stock for d in ok.declared] == [{"name": "email", "role": "level"}, {"name": "email", "role": "outflow"}]
    bad = load({**base, "series": [
        {"source": "work", "name": "backlog", "query": "q", "kind": "level", "stock": "email", "role": "inflow"},
        {"source": "work", "name": "sent", "query": "q", "kind": "counter", "role": "outflow"}]}, Path("."))
    assert not bad.declared and set(bad.refused) == {"series[0]", "series[1]"}
    assert series_key("x", {}) == "x"
