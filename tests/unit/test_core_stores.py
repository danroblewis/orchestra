"""The Core page's external stores, without a store: the selector guard, the window and limit
bounds, the daily cap's refusal, and the URL's redaction (orchestra/sources/console.py, stores.py)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from orchestra.sources.asking import _why
from orchestra.sources.console import MAX_WINDOW_S, Refused, conjoined, guard, limit, resets, window
from orchestra.sources.limits import DailyCap, RateLimit
from orchestra.sources.stores import redact

SHOP = ['{namespace="shop"}']


@pytest.mark.parametrize("q", ["{}", '{__name__=~".+"}', '{namespace="shop"}', '{ namespace = "shop" }', '{job=~".*"}',
                               'sum(rate({__name__=~".+"}[5m]))', 'up or {}'])
def test_a_selector_with_nothing_of_its_own_is_refused(q):
    why = guard(q, SHOP)
    assert why and "a selector needs a metric name or at least one label matcher of its own" in why
    assert '__name__=~".+" counts as none' in why


@pytest.mark.parametrize("q", ["{}", '{__name__=~".+"}', '{__name__!=""}'])
def test_under_the_match_everything_default_a_bare_selector_is_refused_too(q):
    assert guard(q, ['{__name__=~".+"}'])


def test_a_metric_name_or_a_label_matcher_of_its_own_is_allowed_and_the_match_conjoined():
    assert guard("up", SHOP) is None
    assert conjoined("up", SHOP) == 'up{namespace="shop"}'
    assert guard('queue_depth{service="worker"}', SHOP) is None
    assert conjoined('queue_depth{service="worker"}', SHOP) == 'queue_depth{service="worker",namespace="shop"}'
    assert conjoined('sum by (pod) (rate(http_total{code=~"5.."}[5m]))', SHOP) == \
        'sum by (pod) (rate(http_total{code=~"5..",namespace="shop"}[5m]))'
    assert conjoined('{app="a"}', SHOP) == '{app="a",namespace="shop"}'


def test_the_match_is_conjoined_even_on_a_label_the_query_constrains():
    # never widened: another namespace under the shop's match asks for both, and gets nothing
    assert conjoined('up{namespace="other"}', SHOP) == 'up{namespace="other",namespace="shop"}'


def test_a_match_with_a_metric_name_is_conjoined_inside_the_braces():
    assert conjoined("up", ['{__name__=~"http_.*",env="prod"}']) == '{__name__="up",__name__=~"http_.*",env="prod"}'


def test_a_match_of_selectors_that_differ_is_refused():
    why = guard("up", ['{a="1"}', '{b="2"}'])
    assert why and "differ" in why


def test_ranges_longer_than_a_day_are_refused():
    assert guard("rate(up[5m])", SHOP) is None
    assert "at most 24 h" in guard("rate(up[30d])", SHOP)
    assert "at most 24 h" in guard("max_over_time(up[2d:1h])", SHOP)


def test_a_query_with_no_selector_is_allowed_and_an_empty_one_is_not():
    assert guard("time()", SHOP) is None
    with pytest.raises(Refused, match="empty"):
        conjoined("  ", SHOP)


def test_the_window_is_an_hour_by_default_and_a_day_at_most():
    assert window(None, now=10_000.0) == (10_000.0 - 3600, 10_000.0)
    assert window(15, now=10_000.0) == (10_000.0 - 900, 10_000.0)
    s, e = window(60 * 24 * 30, now=1e9)
    assert e - s == MAX_WINDOW_S
    assert window(-5, now=1e9) == (1e9 - 3600, 1e9) and window(float("nan"), now=1e9) == (1e9 - 3600, 1e9)


def test_the_limit_is_fifty_by_default_and_at_most_the_sources_cap():
    spec = SimpleNamespace(max_series=200)
    assert limit(None, spec) == 50 and limit(0, spec) == 50
    assert limit(10, spec) == 10 and limit(10_000, spec) == 200
    assert limit(None, SimpleNamespace(max_series=20)) == 20


def test_a_spent_daily_cap_is_refused_with_when_it_resets():
    b = RateLimit(100, 100, per_day=2, what="the store at http://prom:9090")
    b.take()
    b.take()
    with pytest.raises(DailyCap) as e:
        b.take()
    said = _why(e.value)
    assert "made its 2 requests today" in said and "00:00 UTC" in said and "it resets at 00:00 UTC, in" in said
    assert resets(now=86400 * 100 + 3600 * 22 + 60 * 30) == "it resets at 00:00 UTC, in 1 h 30 min"


def test_peek_reads_the_bucket_without_writing_it(tmp_path):
    path = tmp_path / "stores" / "k" / "rate"
    b = RateLimit(5, 10, path, per_day=100)
    assert b.peek()["today"] == 0 and not path.exists()        # never created by looking
    b.take()
    assert b.peek() == {**b.peek(), "today": 1, "per_day": 100}


def test_the_url_is_shown_without_a_password():
    assert redact("https://user:secret@prom.example:9090/api/prom") == "https://user:•••@prom.example:9090/api/prom"
    assert redact("http://127.0.0.1:8920") == "http://127.0.0.1:8920"
    assert "secret" not in redact("https://u:secret@h/p?token=secret")


@pytest.mark.parametrize("match", [SHOP, ['{__name__=~"grpc_.*"}'], ["a:b"], ['{__name__="a:b"}'], ['a:b{env="p"}']])
@pytest.mark.parametrize("q", ["a:b", "count(a:b)", "sum by (status) (rate(a:b[5m]))", '{__name__="a:b"}',
                               "count(grpc_client_callMillis:count)"])
def test_a_metric_name_with_colons_is_a_name_of_its_own_even_when_the_match_names_it(q, match):
    # the owner's field report (2026-11-04): count(grpc_client_callMillis:count) refused under a
    # match of that one metric family
    assert guard(q, match) is None


@pytest.mark.parametrize("match", [SHOP, ["a:b"], ['{__name__="a:b"}']])
@pytest.mark.parametrize("q", ["{}", '{__name__=~".+"}'])
def test_with_colons_allowed_match_everything_is_still_refused(q, match):
    assert guard(q, match)


def test_a_metric_the_match_names_is_asked_once_and_within_the_match():
    assert conjoined("count(a:b)", ['a:b{env="p"}']) == 'count({__name__="a:b",env="p"})'
    assert conjoined("rate(a:b[5m])", SHOP) == 'rate(a:b{namespace="shop"}[5m])'
