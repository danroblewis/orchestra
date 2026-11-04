"""The Core page's external stores against the fake Prometheus: every query within the source's
match and bounded, the labels endpoints with ``match[]`` and ``limit``, the store's daily cap, the
asked log, and the section's rows (orchestra/sources/asking.py, stores.py; web/core_stores.py)."""

from __future__ import annotations

import json
import math
import time

import pytest
from fake_prometheus import FakePrometheus
from helpers import project

from orchestra.events import Events
from orchestra.sources import asking
from orchestra.sources.spec import for_project
from orchestra.web.core import CoreProbe
from orchestra.web.core_stores import Stores

NOW = math.floor(time.time() / 60) * 60


def pts(v=1.0):
    return [(NOW - 3600 + 60 * i, v + i) for i in range(61)]


DUMP = [("queue_depth", {"namespace": "shop", "service": "worker", "pod": "w-1"}, pts()),
        ("queue_depth", {"namespace": "shop", "service": "worker", "pod": "w-2"}, pts(5)),
        ("queue_depth", {"namespace": "shop", "service": "api", "pod": "a-1"}, pts(9)),
        ("queue_depth", {"namespace": "bank", "service": "worker", "pod": "b-1"}, pts(100)),
        ("up", {"namespace": "shop", "job": "worker"}, pts()),
        ("up", {"namespace": "bank", "job": "ledger"}, pts())]


def toml(url: str, extra: str = "") -> str:
    return f"""
[[sources]]
name = "shop"
url = "{url}"
match = ['{{namespace="shop"}}']
max_series = 20
{extra}
"""


@pytest.fixture
def fake():
    f = FakePrometheus(DUMP)
    yield f
    f.close()


@pytest.fixture
def made(fake, tmp_path, monkeypatch):
    p = project(tmp_path, monkeypatch, toml(fake.url))
    return p, for_project(p).sources[0]


def test_a_query_carries_the_match_and_the_page_sees_only_its_part(made, fake):
    p, spec = made
    out = asking.query(p.state_dir, spec, "queue_depth", now=NOW)
    assert out["ok"], out
    assert out["query"] == 'queue_depth{namespace="shop"}'
    assert {ln["labels"]["pod"] for ln in out["lines"]} == {"w-1", "w-2", "a-1"}
    assert all('namespace="shop"' in q for q in fake.queries)
    # counted first, bounded: one series listing with limit + 1 over the window
    series = [f for path, f in fake.seen if path.endswith("/series")]
    assert len(series) == 1 and out["requests"] == 2


def test_a_bare_selector_is_refused_before_any_request(made, fake):
    p, spec = made
    for q in ("{}", '{__name__=~".+"}', '{namespace="shop"}'):
        out = asking.query(p.state_dir, spec, q, now=NOW)
        assert not out["ok"] and out["refused"] and "of its own" in out["error"]
    assert fake.requests == 0


def test_a_selector_over_the_limit_is_refused_before_the_query_runs(made, fake):
    p, spec = made
    out = asking.query(p.state_dir, spec, "queue_depth", limit_n=2, now=NOW)
    assert not out["ok"] and "selects more than 2 series" in out["error"]
    assert fake.queries == []                                   # the query itself was never sent
    asks = [form for path, form in fake.seen if path.endswith("/series")]
    assert len(asks) == 1


def test_the_limit_is_at_most_the_sources_cap(made):
    p, spec = made
    out = asking.query(p.state_dir, spec, "up", limit_n=10_000, now=NOW)
    assert out["ok"] and out["limit"] == 20


def test_an_instant_query_answers_at_the_windows_end(made, fake):
    p, spec = made
    out = asking.query(p.state_dir, spec, 'queue_depth{service="worker"}', instant=True, now=NOW)
    assert out["ok"] and out["instant"] and len(out["lines"]) == 2
    assert all(len(ln["points"]) == 1 for ln in out["lines"])


def test_labels_and_values_go_with_match_and_limit_bounded_by_the_window(made, fake):
    p, spec = made
    out = asking.labels(p.state_dir, spec, "queue_depth", minutes=30, limit_n=3, now=NOW)
    assert out["ok"] and len(out["values"]) <= 3
    endpoint, form = fake.label_asks[-1]
    assert endpoint == "labels"
    assert form["match[]"] == ['queue_depth{namespace="shop"}'] and form["limit"] == ["3"]
    assert float(form["end"][0]) - float(form["start"][0]) == pytest.approx(1800)
    vals = asking.values(p.state_dir, spec, "pod", "queue_depth", now=NOW)
    assert vals["ok"] and vals["values"] == ["a-1", "w-1", "w-2"]           # never the bank's pod
    endpoint, form = fake.label_asks[-1]
    assert endpoint == "label/pod" and form["match[]"] == ['queue_depth{namespace="shop"}'] and form["limit"] == ["20"]
    # no selector: the source's match alone; a bare selector is refused
    asking.values(p.state_dir, spec, "__name__", "", now=NOW)
    assert fake.name_asks[-1] == ['{namespace="shop"}']
    assert not asking.labels(p.state_dir, spec, "{}", now=NOW)["ok"]
    assert all(not path.endswith("/series") for path, _ in fake.seen)    # never a listing of series


def test_with_the_match_everything_default_a_labels_request_naming_nothing_is_refused_unsent(fake, tmp_path, monkeypatch):
    p = project(tmp_path, monkeypatch, f'[[sources]]\nname = "all"\nurl = "{fake.url}"\n')
    spec = for_project(p).sources[0]
    before = len(fake.label_asks)
    for out in (asking.labels(p.state_dir, spec, "", now=NOW), asking.values(p.state_dir, spec, "pod", "", now=NOW)):
        assert not out["ok"] and "whole store" in out["error"]
    assert len(fake.label_asks) == before                                # never a labels request with no match[]
    out = asking.labels(p.state_dir, spec, "queue_depth", now=NOW)
    assert out["ok"] and fake.label_asks[-1][1]["match[]"] == ["queue_depth"]


def test_a_spent_daily_cap_is_refused_with_when_it_resets(fake, tmp_path, monkeypatch):
    p = project(tmp_path, monkeypatch, toml(fake.url, "max_requests_per_day = 5\nweb_share = 0.2"))
    spec = for_project(p).sources[0]
    assert asking.labels(p.state_dir, spec, "up", now=NOW)["ok"]       # the web share: 1 a day
    out = asking.labels(p.state_dir, spec, "up", now=NOW)
    assert not out["ok"] and out["cap"] and "it resets at 00:00 UTC, in" in out["error"]
    assert fake.requests == 1


def test_every_request_and_refusal_is_logged_with_the_page_as_reader(made):
    p, spec = made
    asking.query(p.state_dir, spec, "up", now=NOW)
    asking.query(p.state_dir, spec, "{}", now=NOW)
    lines = [json.loads(x) for x in asking.log_path(p.state_dir, "shop").read_text().splitlines()]
    assert [x["reader"] for x in lines] == ["core page", "core page"]
    assert lines[0]["ok"] and lines[0]["sent"] == 'up{namespace="shop"}' and lines[0]["requests"] == 2
    assert not lines[1]["ok"] and "of its own" in lines[1]["error"]


def test_the_section_shows_each_store_from_files_and_never_asks_it(fake, tmp_path, monkeypatch):
    p = project(tmp_path, monkeypatch, toml(fake.url, 'auth = { bearer_env = "SHOP_TOKEN" }'))
    monkeypatch.setenv("SHOP_TOKEN", "s3cret-token")
    stores = Stores(CoreProbe(p, Events.for_project(p)))
    st = stores.status()
    assert st["ok"] and fake.requests == 0
    (row,) = st["stores"]
    assert row["name"] == "shop" and row["type"] == "prometheus" and row["url"] == fake.url
    assert row["match"] == ['{namespace="shop"}'] and row["max_series"] == 20 and row["per_day"] == 20000
    assert row["bucket"]["store"]["today"] == 0 and row["inferred"] is None and row["last_error"] is None
    assert row["auth"]["kinds"] == ["bearer"] and row["auth"]["credentials"][0]["from"] == "environment variable SHOP_TOKEN"
    stores.query("shop", "up", instant=False, minutes=60, limit=50)
    stores.query("shop", "{}", instant=False, minutes=60, limit=50)
    row = stores.status()["stores"][0]
    assert row["bucket"]["store"]["today"] == 2 and row["bucket"]["web"]["today"] == 2
    assert row["last_ok"] and row["last_error"]["from"] == "this page"
    assert any(x["component"] == "store shop" for x in stores.core.log)
    assert "s3cret" not in json.dumps(stores.status())


def test_the_section_says_when_there_are_none_and_when_a_store_is_down(tmp_path, monkeypatch):
    p = project(tmp_path, monkeypatch, "")
    stores = Stores(CoreProbe(p, Events.for_project(p)))
    assert stores.status() == {**stores.status(), "ok": True, "stores": [], "refused": []}
    (tmp_path / "b").mkdir()
    down = project(tmp_path / "b", monkeypatch, toml("http://127.0.0.1:9"))
    s = Stores(CoreProbe(down, Events.for_project(down)))
    assert s.status()["ok"]                                    # files only: the rows stand
    out = s.query("shop", "up", instant=True, minutes=60, limit=5)
    assert not out["ok"] and "127.0.0.1:9" in out["error"]
    assert not s.query("nope", "up", instant=True, minutes=60, limit=5)["ok"]


def test_a_broken_sources_package_shows_on_the_section_only(made, monkeypatch):
    p, _ = made
    import orchestra.sources.stores as mod
    monkeypatch.setattr(mod, "status", lambda project: (_ for _ in ()).throw(ImportError("broken")))
    out = Stores(CoreProbe(p, Events.for_project(p))).status()
    assert not out["ok"] and "the external stores cannot be read" in out["error"] and "broken" in out["error"]


def test_a_refused_entry_is_listed_with_why(fake, tmp_path, monkeypatch):
    p = project(tmp_path, monkeypatch, toml(fake.url) + '\n[[sources]]\nname = "bad"\nurl = "http://u:pw@h"\n')
    st = Stores(CoreProbe(p, Events.for_project(p))).status()
    assert [r["name"] for r in st["refused"]] == ["bad"] and "pw" not in json.dumps(st)
