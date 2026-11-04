"""A series read from a source carries its selector as the store spells it (the store's own metric
name and label spellings, from the definition it was read by, never rebuilt from Orchestra's
prefixed, lower-cased name) and the query a view of it opens with: a counter's ``rate()``, a
gauge's bare selector. The discovery record lists them for the pages (``sourced``), and the
Instruments page's source row carries them."""

from __future__ import annotations

import math
import time

from fake_prometheus import FakePrometheus
from helpers import project, source_toml, world

from orchestra.metrics import for_project
from orchestra.sd.rediscover import rediscover
from orchestra.sources.selector import base, of_series, plain, view_query
from orchestra.sources.views import Definition
from orchestra.web.instruments import instruments_view


def now_grid(step: float = 60.0) -> float:
    return math.floor(time.time() / step) * step


def _d(**kw) -> Definition:
    return Definition(**{"id": "x", "source": "chrono", "name": "n", "family": "f", "view": "sum_by", "kind": "level", "query": "", **kw})


def test_the_selector_is_the_stores_own_spelling():
    d = _d(inner='last_over_time(Lens:Requests_Total{namespace="shop"}[151s])', query="sum by (service_name) (…)",
           group_by=["service"], by_real=["service_name"])
    assert base(d) == 'Lens:Requests_Total{namespace="shop"}'
    assert of_series(d, {"service": "checkout", "instance": "x"}, "chrono") == 'Lens:Requests_Total{namespace="shop",service_name="checkout"}'
    assert view_query(d, of_series(d, {"service": "a"}, "chrono"), 60) == 'Lens:Requests_Total{namespace="shop",service_name="a"}'
    # a machine label is prefixed by Orchestra (fetch._finish); the store holds it bare
    m = _d(inner="up", group_by=["machine"], by_real=["app"])
    assert of_series(m, {"machine": "chrono.api"}, "chrono") == 'up{app="api"}'


def test_a_counter_opens_as_its_rate_and_a_written_query_as_written():
    c = _d(view="increments", kind="counter", inner='http_requests_total{job="api"}', query='http_requests_total{job="api"}',
           group_by=["status"], by_real=["code"], resolution_s=15.0)
    sel = of_series(c, {"status": "500"}, "chrono")
    assert sel == 'http_requests_total{job="api",code="500"}'
    assert view_query(c, sel, 120) == f"rate({sel}[120s])"
    assert view_query(c, sel, 10).startswith(f"rate({sel}[") and not view_query(c, sel, 10).endswith("[10s])")   # two samples at least
    q = _d(view="declared", query='sum(rate(http_errors_total{svc="checkout"}[5m]))')
    assert base(q) is None and of_series(q, {}, "chrono") is None and view_query(q, None, 60) == q.query
    assert plain('{__name__="a:b",x="y"}') and not plain("sum(x)")


def test_discovery_records_each_remote_series_selector(tmp_path, monkeypatch):
    dump, _ = world(now_grid(), 240, regions={"us-east": 1.0, "eu-west": 0.5}, deploy_every=30)
    fake = FakePrometheus(dump)
    try:
        p = project(tmp_path, monkeypatch, source_toml(fake.url, window="240m"))
        r = rediscover(p, for_project(p))
    finally:
        fake.close()
    sourced = r.model.discovery["sourced"]
    assert sourced and all(v["source"] == "rig" for v in sourced.values())
    store_names = {name for name, _, _ in dump}
    for key, v in sourced.items():
        sel = v["selector"]
        metric = sel.split("{", 1)[0]
        assert metric in store_names and not metric.startswith("rig:"), (key, sel)
        if v["kind"] == "counter" and "_started_total" not in key and "_stopped_total" not in key:
            assert v["store_query"].startswith(f"rate({sel}[") and v["store_query"].endswith("s])")
        elif v["kind"] == "level":
            assert v["store_query"] == sel
    pods = [s for s in r.model.stocks if s.series and s.series.name.endswith("_pods")]
    # each spelled as the store spells it: app= or service=, zone= or region=, never the canonical names it was renamed to
    assert pods and all(f'="{s.series.labels["service"]}"' in s.series.selector and "rig." not in s.series.selector for s in pods)
    assert any('app="' in s.series.selector for s in pods)
    row = next(x for x in instruments_view(p, r.model.discovery)["instruments"] if x["kind"] == "source")
    assert {x["key"] for x in row["series"]} == set(sourced) and row["window"]["end"] > row["window"]["start"]
