"""Counted traffic: series definitions (hand-written or from a preset) that mark a count as what a
machine produced into or consumed from a channel on another system's bus, or that channel's
backlog. The catalogue resolves the channel and machine per result series, discovery attributes
the flows to them, and the Machines page gets producers, channels and consumers with counted edges,
the unattributed share drawn as such. No event is ever made from a count."""

from __future__ import annotations

import math
import random
import time

import pytest
from fake_prometheus import FakePrometheus
from helpers import project

from orchestra.events import Events
from orchestra.sd.rediscover import rediscover
from orchestra.sources import traffic
from orchestra.sources.catalogue import Catalogue
from orchestra.sources.fetch import increments
from orchestra.sources.spec import load
from orchestra.web.traffic import merge, summarise

PRESET = '''
[source]
infer = false

[[series]]
name = "published_total"
select = '{__name__="broker_published_total"}'
by = ["exchange"]
kind = "counter"
traffic = { direction = "out", channel = "{exchange}" }

[[series]]
name = "acked_total"
query = 'sum by (exchange, queue, consumer) (broker_acked_total)'
kind = "counter"
traffic = { direction = "in", channel = "{exchange}", machine = "{consumer}" }

[[series]]
name = "backlog"
query = 'sum by (exchange, queue, consumer) (broker_backlog)'
kind = "level"
traffic = { direction = "backlog", channel = "{exchange}", machine = "{consumer}" }
'''


def broker(end: float, minutes: int = 30):
    """Two exchanges: orders (fanout to billing and shipping) and clicks (to analytics, which
    lags). The orders publisher's channel closes halfway and a new one opens (its counter starts
    again at 0): read from raw samples, the count runs on."""
    rng = random.Random(7)
    dump, start = [], end - minutes * 60
    pub = {"orders": [], "clicks": []}
    acked = {("orders", "billing.orders", "billing"): [], ("orders", "shipping.orders", "shipping"): [],
             ("clicks", "analytics.clicks", "analytics"): []}
    back = {k: [] for k in acked}
    n = {"orders": 0, "clicks": 0}
    a = dict.fromkeys(acked, 0)
    for i in range(minutes * 4 + 1):
        t = start + i * 15
        n["orders"] += 3 if i < 2 else rng.randint(0, 6)
        n["clicks"] += 6
        for k, pts in acked.items():
            take = 3 if i < 2 else min(n[k[0]] - a[k], rng.randint(0, 7)) if k[0] == "orders" else 4
            a[k] += take
            pts.append((t, a[k]))
            back[k].append((t, n[k[0]] - a[k]))
        for x, pts in pub.items():
            pts.append((t, n[x]))
    half = len(pub["orders"]) // 2
    first, second = pub["orders"][:half], pub["orders"][half:]
    base = first[-1][1]
    dump.append(("broker_published_total", {"channel": "<0.1.0>", "exchange": "orders"}, first))
    dump.append(("broker_published_total", {"channel": "<0.2.0>", "exchange": "orders"}, [(t, v - base) for t, v in second]))
    dump.append(("broker_published_total", {"channel": "<0.3.0>", "exchange": "clicks"}, pub["clicks"]))
    for (ex, q, who), pts in acked.items():
        dump.append(("broker_acked_total", {"exchange": ex, "queue": q, "consumer": who}, pts))
    for (ex, q, who), pts in back.items():
        dump.append(("broker_backlog", {"exchange": ex, "queue": q, "consumer": who}, pts))
    return dump, start


def toml(url: str, preset: str, extra: str = "") -> str:
    return f'''
[discovery]
window = "30m"
step = "15s"
strategy = "conservation"

[[sources]]
name = "mq"
url = "{url}"
preset = "{preset}"
{extra}
[sources.producers]
orders = "orders-api"
'''


@pytest.fixture
def rig(tmp_path, monkeypatch):
    end = math.floor(time.time() / 15) * 15
    dump, start = broker(end)
    fake = FakePrometheus(dump)
    (tmp_path / "rabbit.toml").write_text(PRESET)
    p = project(tmp_path, monkeypatch, toml(fake.url, str(tmp_path / "rabbit.toml")))
    yield p, fake, start, end
    fake.close()


def test_a_preset_declares_the_series_and_turns_inference_off(rig):
    p, fake, start, end = rig
    cat = Catalogue(p, None)
    [spec] = cat.specs.sources
    assert spec.infer is False and spec.producers == {"orders": "orders-api"} and not cat.specs.refused
    assert [(d.name, d.traffic["direction"]) for d in cat.specs.declared] == [("published_total", "out"), ("acked_total", "in"), ("backlog", "backlog")]
    inf = cat.inference("mq", start, end)
    assert [d.view for d in inf.kept] == ["increments", "declared", "declared"]
    assert all(d.origin == [f"declared in the preset {spec.preset}"] for d in inf.kept)
    assert not any("series?" in q or "/series" in q for q in fake.queries)            # the schema is never read


def test_the_reading_resolves_channel_and_machine_per_series(rig):
    p, fake, start, end = rig
    r = Catalogue(p, None).read(start, end, 15.0)
    assert not r.missing
    by = {(k.split("{")[0], v["channel"], v["machine"]): v for k, v in r.traffic.items()}
    assert set(by) == {("mq:published_total", "mq:orders", "mq.orders-api"), ("mq:published_total", "mq:clicks", None),
                       ("mq:acked_total", "mq:orders", "mq.billing"), ("mq:acked_total", "mq:orders", "mq.shipping"),
                       ("mq:acked_total", "mq:clicks", "mq.analytics"), ("mq:backlog", "mq:orders", "mq.billing"),
                       ("mq:backlog", "mq:orders", "mq.shipping"), ("mq:backlog", "mq:clicks", "mq.analytics")}
    assert by[("mq:published_total", "mq:orders", "mq.orders-api")]["attributed"] == "declared in [sources.producers]"
    assert by[("mq:published_total", "mq:clicks", None)]["attributed"] == "unattributed"
    pub = {labels.get("exchange"): (labels, pts) for name, labels, pts in r.dump if name == "mq:published_total"}
    assert pub["orders"][0]["machine"] == "mq.orders-api" and "machine" not in pub["clicks"][0]
    # the channel's restart is no reset of the count: the old channel's first sample in the window
    # (a range selector's window is open at its start) is its baseline; the new one began inside
    # the window, from 0, so its first sample counts
    old, new = ([v for t, v in pts if t > start] for name, labels, pts in fake.dump
                if name == "broker_published_total" and labels["exchange"] == "orders")
    assert pub["orders"][1][-1][1] == (old[-1] - old[0]) + new[-1]
    for key, prov in r.provenance.items():
        assert prov["traffic"] == r.traffic[key]


def test_counted_traffic_makes_no_events(rig):
    p, _, start, end = rig
    Catalogue(p, None).read(start, end, 15.0)
    Catalogue(p, None).counted(start, end, 15.0)
    assert Events.for_project(p).end() == 0


def test_the_machines_view_gets_producers_channels_and_consumers(rig):
    p, fake, _, end = rig
    got, failed = Catalogue(p, None).counted(end - 1800, end, 15.0)
    assert not failed and {c["direction"] for c in got} == {"out", "in", "backlog"}
    s = summarise(got, end)
    ch = {c["id"]: c for c in s["channels"]}
    assert set(ch) == {"mq:orders", "mq:clicks"}
    assert ch["mq:orders"]["out_per_min"] == pytest.approx(12, rel=0.3) and ch["mq:orders"]["in_per_min"] == pytest.approx(24, rel=0.3)
    assert ch["mq:clicks"]["backlog"] == next(pts[-1][1] for name, labels, pts in fake.dump if name == "broker_backlog" and labels["exchange"] == "clicks")
    view = {"machines": [{"id": "mq.billing", "publishes": [{"type": "invoice.sent"}], "active": False, "last_seen": None}]}
    merge(view, s, end)
    m = {x["id"]: x for x in view["machines"]}
    assert set(m) == {"mq.orders-api", "mq.billing", "mq.shipping", "mq.analytics"}
    assert m["mq.billing"]["publishes"] and "counted_only" not in m["mq.billing"]          # seen on the bus too: one machine
    assert m["mq.analytics"]["counted_only"] and m["mq.analytics"]["active"]
    assert {(t["channel"], t["direction"]) for t in m["mq.analytics"]["counted"]} == {("mq:clicks", "in"), ("mq:clicks", "backlog")}
    edges = {(e["from"], e["to"]) for e in view["counted"]}
    assert ("mq.orders-api", "mq:orders") in edges and (None, "mq:clicks") in edges      # the clicks publisher is not named
    assert ("mq:orders", "mq.billing") in edges and ("mq:clicks", "mq.analytics") in edges
    assert all(e["direction"] != "backlog" for e in view["counted"])


@pytest.mark.parametrize("bad, why", [
    ('traffic = { direction = "sideways", channel = "{q}" }', "direction"),
    ('traffic = { direction = "out" }', "channel"),
    ('traffic = { direction = "backlog", channel = "{q}" }', "kind = level"),
    ('traffic = { direction = "out", channel = "{q}", colour = "red" }', "unknown keys"),
])
def test_a_bad_traffic_table_refuses_the_series_with_why(tmp_path, bad, why):
    raw = {"sources": [{"name": "mq", "url": "http://127.0.0.1:9"}],
           "series": [{"source": "mq", "name": "x_total", "query": "x", "kind": "counter", **_toml_table(bad)}]}
    specs = load(raw, tmp_path)
    assert not specs.declared and why in specs.refused["series[0]"]


def _toml_table(line: str) -> dict:
    import tomllib
    return tomllib.loads(line)


def test_a_select_is_a_counter_and_a_missing_preset_refuses_its_source(tmp_path):
    raw = {"sources": [{"name": "mq", "url": "http://127.0.0.1:9"}, {"name": "gone", "url": "http://127.0.0.1:9", "preset": "nope.toml"}],
           "series": [{"source": "mq", "name": "x", "select": "{__name__=\"x\"}", "kind": "level"},
                      {"source": "mq", "name": "y_total", "select": "{__name__=\"y\"}", "query": "y", "kind": "counter"}]}
    specs = load(raw, tmp_path)
    assert [s.name for s in specs.sources] == ["mq"] and "nope.toml" in specs.refused["gone"]
    assert "kind = \"counter\"" in specs.refused["series[0]"] and "one of them" in specs.refused["series[1]"]


def test_templates_render_from_labels_and_leave_a_missing_label_unattributed():
    t = traffic.parse({"direction": "in", "channel": "{exchange}", "machine": "svc-{consumer}"}, "counter")
    assert traffic.resolve(t, {"exchange": "orders", "consumer": "billing"}, "mq") == {
        "direction": "in", "channel": "mq:orders", "machine": "mq.svc-billing", "attributed": "from its labels"}
    assert traffic.resolve(t, {"exchange": "orders"}, "mq")["machine"] is None
    assert traffic.render("{a}.{b}", {"a": "x", "b": ""}) is None


def test_discovery_finds_each_backlog_filled_by_its_channel_and_drained_by_its_consumer(rig):
    m = rediscover(rig[0], None).model
    backlogs = {s.id: s for s in m.stocks if s.series and s.series.name == "mq:backlog"}
    orders = {sid for sid, s in backlogs.items() if s.series.traffic["channel"] == "mq:orders"}
    assert len(orders) == 2, m.discovery["left_out"]
    pub = [f for f in m.flows if f.counter and f.counter.name == "mq:published_total" and f.counter.labels.get("exchange") == "orders"]
    assert {f.dst for f in pub} == orders and sum(1 for f in pub if "copy_of" in f.evidence) == 1
    assert all(f.counter.traffic["machine"] == "mq.orders-api" for f in pub)
    # each drain is counted as one consumer's traffic; the label naming it is kept as provenance
    # and associates no machine with the flow (AGENTS.md rule 7): only events on the bus do
    drains = {f.counter.traffic["machine"] for f in m.flows if f.src in orders and f.counter}
    assert drains == {"mq.billing", "mq.shipping"}
    assert m.machines == [] and all(f.evidence["machines"]["hypotheses"] == [] for f in m.flows if "machines" in f.evidence)


def test_a_counter_that_began_inside_the_window_counts_its_first_value():
    t0 = 1_000_000.0
    old = ({"ch": "1"}, [(t0 + 5 * i, 100.0 + 3 * i) for i in range(10)])           # there at the start: a baseline
    new = ({"ch": "2"}, [(t0 + 300 + 5 * i, 4.0 + 3 * i) for i in range(10)])       # opened at +300 s, from 0
    gap = ({"ch": "3"}, [(t0 + 300 + 5 * i, 900.0 + 3 * i) for i in range(10)])     # old, but missing at the start
    [(_, pts)] = increments([old, new], [], start=t0)
    assert pts[-1][1] == 27 + 4 + 27
    [(_, pts)] = increments([gap], [], start=t0)
    assert pts[-1][1] == 27
    [(_, pts)] = increments([new], [])                                              # without a start: always a baseline
    assert pts[-1][1] == 27


def test_settle_ends_every_read_of_a_source_together(tmp_path, monkeypatch):
    end = math.floor(time.time() / 15) * 15
    dump, start = broker(end)
    fake = FakePrometheus(dump)
    (tmp_path / "rabbit.toml").write_text(PRESET)
    try:
        p = project(tmp_path, monkeypatch, toml(fake.url, str(tmp_path / "rabbit.toml"), extra='settle = "60s"'))
        r = Catalogue(p, None).read(start, end, 15.0)
    finally:
        fake.close()
    assert r.dump and max(t for _, _, pts in r.dump for t, _ in pts) <= end - 60
    assert r.status["mq"]["gaps"] == []                    # the settled minute is not a gap in what it returned
