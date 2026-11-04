"""``names`` on a source: templates that name what a series becomes (``sources/naming.py``), the
base of its title (``sd.titles``), matched as ``kinds`` are; a declared name still wins."""

from __future__ import annotations

from pathlib import Path

import pytest
from test_source_occupancy import NOW, T0, rules, store  # noqa: F401 - the fixture

from orchestra.sd.titles import Places
from orchestra.sources.infer import settings_key
from orchestra.sources.naming import name_of, render
from orchestra.sources.prometheus import PrometheusSource
from orchestra.sources.schema import read
from orchestra.sources.spec import load
from orchestra.sources.views import Definition, views

SUB = "gcp_pubsub_subscription_num_undelivered_messages"


def _d(query: str, family: str = "f", **kw) -> Definition:
    return Definition(id="x", source="work", name="x", family=family, view="sum_by", kind="level", query=query, **kw)


def test_templates_fill_labels_and_leave_a_missing_one_out():
    assert render("{subscription_id} messages waiting", SUB, {"subscription_id": "orders"}) == "orders messages waiting"
    assert render("{method} calls ({status})", "m", {"method": "Get"}) == "Get calls"
    assert render("{method} calls ({status}, {region})", "m", {"method": "Get", "region": "eu"}) == "Get calls (eu)"
    assert render("{metric} by {svc}", "queue_depth", {"service": "a"}, {"svc": "service"}) == "queue_depth by a"   # the store's spelling
    assert render("{nothing}", "queue_depth", {}) == "queue_depth"


def test_precedence_is_kinds_own_exact_then_longest_pattern():
    names = {"gcp_pubsub_*": "{metric}", "*_num_undelivered_messages": "{subscription_id} messages waiting",
             SUB: "{subscription_id} backlog"}
    d = _d(f'sum by (subscription_id) (last_over_time({SUB}{{project="p"}}[151s]))')
    assert name_of(names, d, {"subscription_id": "orders"}) == ("orders backlog", SUB)
    del names[SUB]
    assert name_of(names, d, {"subscription_id": "orders"}) == ("orders messages waiting", "*_num_undelivered_messages")
    other = _d("sum(last_over_time(gcp_pubsub_topic_send_request_count[151s]))")
    assert name_of(names, other, {}) == ("gcp_pubsub_topic_send_request_count", "gcp_pubsub_*")
    assert name_of(names, _d("sum(last_over_time(unrelated[1m]))"), {}) is None


def test_a_sum_names_the_occupancy_view_and_a_count_its_completions(store, tmp_path):   # noqa: F811
    fake = store(rules())
    specs = load({"sources": [{"name": "work", "url": fake.url, "match": ['{__name__=~"[a-zA-Z_:].*"}'],
                               "names": {"*:sum": "{method} calls in progress", "grpc_client_callMillis:count": "{method} calls completed"}}]},
                 tmp_path)
    spec = specs.sources[0]
    defs = [d for f in read(PrometheusSource(spec), spec, T0, NOW).families for d in views(f, spec)]
    busy = {d.occupancy["busy"] for d in defs if d.occupancy}
    occ = next(d for d in defs if d.view == "occupancy" and d.group_by == ["method"])
    assert name_of(spec.names, occ, {"method": "Get"}, busy) == ("Get calls in progress", "*:sum")
    done = next(d for d in defs if d.view == "increments" and "grpc_client_callMillis:count" in d.query)
    assert name_of(spec.names, done, {"method": "Put", "status": "failed"}, busy) == ("Put calls completed", "grpc_client_callMillis:count")
    own_sum = [d for d in defs if d.view == "rollup" and ":sum" in d.query]
    assert all(name_of(spec.names, d, {"method": "Get"}, busy) is None for d in own_sum)     # the sum itself is not the occupancy


def test_the_title_is_the_template_its_tags_as_before():
    prov = {"k1": {"source": "work", "kind": "level", "named_as": "orders messages waiting", "named_by": "*_num_undelivered_messages"},
            "k2": {"source": "work", "kind": "level"}}
    places = Places([("chrono:" + SUB, {"subscription_id": "orders"}, "k1"), ("chrono:" + SUB, {"subscription_id": "pay"}, "k2")], prov)
    assert places.sourced("chrono:" + SUB, {"subscription_id": "orders"}, "k1") == "orders messages waiting"
    assert places.sourced_tags("chrono:" + SUB, {"subscription_id": "orders"}, "k1") == ["source=work", "subscription_id=orders"]
    assert places.sourced("chrono:" + SUB, {"subscription_id": "pay"}, "k2") == "gcp pubsub subscription num undelivered messages (pay)"


def test_a_declared_name_still_wins():
    from orchestra.web.intended import lend_names
    m = {"stocks": [{"id": "s1", "name": "orders messages waiting"}], "flows": []}
    lend_names(m, {"names": {"stocks": {"s1": {"name": "Orders backlog", "provenance": {}}}}})
    assert m["stocks"][0]["declared_name"]["name"] == "Orders backlog"
    js = (Path(__file__).parents[2] / "orchestra/web/static/sd-graph.js").read_text()
    assert "name: d.name, label: d.name" in js and "generated: v.label" in js           # the page shows the declared name, the generated beneath


def test_names_need_no_new_inference_round(tmp_path):
    spec = lambda names: load({"sources": [{"name": "w", "url": "http://127.0.0.1:9", "match": ['{__name__=~"x.*"}'], "names": names}]},
                              tmp_path).sources[0]
    assert settings_key(spec({}), [], tmp_path) == settings_key(spec({"x*": "{metric}"}), [], tmp_path)


def test_names_must_be_templates(tmp_path):
    specs = load({"sources": [{"name": "w", "url": "http://127.0.0.1:9", "match": ['{__name__=~"x.*"}'], "names": {"x": 3}}]}, tmp_path)
    assert "w" in specs.refused and "names" in specs.refused["w"]


@pytest.mark.parametrize("q", ["sum by (a) (increase(x_total{s=\"1\"}[5m]))"])
def test_a_query_reads_its_selected_metric(q):
    from orchestra.sources.naming import metrics_read
    assert metrics_read(_d(q)) == ["x_total"]


def test_a_reading_carries_the_name_and_its_entry(tmp_path, monkeypatch):
    import math
    import time

    from fake_prometheus import FakePrometheus
    from helpers import project, source_toml

    from orchestra.metrics import for_project
    from orchestra.sd.rediscover import aligned
    from orchestra.sources.catalogue import Catalogue

    end = math.floor(time.time() / 60) * 60
    dump = [(SUB, {"subscription_id": s}, [(end - 7200 + 60 * k, float(500 + (k * (i + 3)) % 7)) for k in range(121)])
            for i, s in enumerate(("orders", "pay"))]
    fake = FakePrometheus(dump)
    try:
        p = project(tmp_path, monkeypatch, source_toml(fake.url, extra='[sources.names]\n"*_num_undelivered_messages" = "{subscription_id} messages waiting"\n'))
        start, stop = aligned(end - 7200, end, 60.0)
        reading = Catalogue(p, for_project(p)).read(start, stop, 60.0)
    finally:
        fake.close()
    named = {v["named_as"]: v["named_by"] for v in reading.provenance.values() if v.get("named_as")}
    assert named.get("orders messages waiting") == "*_num_undelivered_messages" and "pay messages waiting" in named, reading.provenance
