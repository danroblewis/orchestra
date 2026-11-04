"""``explore`` on a source and ``orchestra sources explore`` against the fake Prometheus: the scope
validated beside ``match``, the survey of families beyond the match with their labels, value
counts, metadata and kinds, every request bounded, within ``explore`` and logged ``by`` explore,
and the daily cap's refusal before anything is sent (orchestra/sources/exploring.py, within.py)."""

from __future__ import annotations

import json
import math
import time

import pytest
from fake_prometheus import FakePrometheus
from helpers import project

from orchestra import cli
from orchestra.sources import exploring, reqlog
from orchestra.sources.spec import for_project, load
from orchestra.sources.within import within

NOW = math.floor(time.time() / 60) * 60


def rising(v=0.0, k=1.0):
    return [(NOW - 3600 + 60 * i, v + k * i) for i in range(61)]


def wavy(v=10.0):
    return [(NOW - 3600 + 60 * i, v + (i % 7) - 3 * (i % 3)) for i in range(61)]


DUMP = [("queue_depth", {"namespace": "shop", "service": "worker", "pod": "w-1"}, wavy()),
        ("orders_total", {"namespace": "shop", "service": "api", "pod": "a-1"}, rising()),
        ("payments_backlog", {"namespace": "payments", "queue": "q1", "pod": "p-1"}, wavy(40)),
        ("payments_backlog", {"namespace": "payments", "queue": "q2", "pod": "p-2"}, wavy(50)),
        ("payments_acked_total", {"namespace": "payments", "queue": "q1", "pod": "p-1"}, rising(0, 3)),
        ("payments_acked_total", {"namespace": "payments", "queue": "q2", "pod": "p-2"}, rising(5, 2)),
        ("ledger_rows", {"namespace": "bank", "pod": "b-1"}, wavy(7))]


def toml(url: str, extra: str = "") -> str:
    return f"""
[[sources]]
name = "shop"
url = "{url}"
match = ['{{namespace="shop"}}']
explore = ['{{namespace=~"shop|payments"}}']
rate = 500.0
burst = 500.0
{extra}
"""


@pytest.fixture
def fake():
    f = FakePrometheus(DUMP)
    f.meta = {"payments_acked_total": [{"type": "counter", "help": "messages acknowledged", "unit": ""}]}
    yield f
    f.close()


@pytest.fixture
def made(fake, tmp_path, monkeypatch):
    p = project(tmp_path, monkeypatch, toml(fake.url))
    return p, for_project(p).sources[0]


def _load(extra: str):
    raw = {"sources": [{"name": "s", "url": "http://x:1", "match": ['{namespace="shop"}'], **extra}]}
    return load(raw, "/tmp")


def test_explore_defaults_to_match_and_holds_it():
    specs = _load({})
    assert specs.sources[0].explore == ['{namespace="shop"}']
    assert _load({"explore": ['{namespace=~"shop|pay"}']}).sources[0].explore == ['{namespace=~"shop|pay"}']
    assert _load({"explore": ['{env="prod"}', '{namespace="shop"}']}).sources


@pytest.mark.parametrize("explore,why", [(["{}"], "selects everything"), (['{__name__=~".+"}'], "selects everything"),
                                         (['{namespace="pay"}'], "does not lie within explore"),
                                         (['{namespace=~"sh.*", env="prod"}'], "does not lie within explore"), ([], "explore = ")])
def test_explore_refused_with_its_reason(explore, why):
    specs = _load({"explore": explore})
    assert not specs.sources and why in specs.refused["s"]


def test_within_by_the_matchers_as_written():
    assert within('{namespace="shop", __name__=~"http_.*"}', '{namespace="shop"}')
    assert within("http_requests_total", '{__name__=~"http_.*"}')
    assert within('{namespace="a"}', '{namespace!="b"}')
    assert not within('{namespace=~"a|b"}', '{namespace="a"}')
    assert not within('{namespace=~"a"}', '{namespace=~"a|b"}')          # two regexes: not proved
    assert not within("{}", '{namespace="a"}')


def test_the_survey_lists_families_beyond_the_match_with_labels_counts_and_kinds(made, fake):
    p, spec = made
    out = exploring.explore(p.state_dir, spec, now=NOW)
    assert "refused" not in out and "error" not in out, out
    fams = {r["family"]: r for r in out["families"]}
    assert set(fams) == {"payments_backlog", "payments_acked_total", "queue_depth", "orders_total"}   # never ledger_rows (bank)
    assert [r["in_match"] for r in out["families"]] == [False, False, True, True]                     # beyond the match first
    acked, backlog = fams["payments_acked_total"], fams["payments_backlog"]
    assert acked["labels"]["queue"]["values"] == 2 and acked["labels"]["pod"]["values"] == 2 and "namespace" in acked["labels"]
    assert acked["type"] == "counter" and acked["help"] == "messages acknowledged"
    assert acked["kind"] == "counter" and acked["reads_as"] == "flow"
    assert backlog["kind"] == "gauge" and backlog["reads_as"] == "level" and backlog["series_sampled"] == 2
    assert out["requests"] <= exploring.cost(spec, out["limit"])


def test_every_request_is_within_explore_bounded_and_logged_by_explore(made, fake):
    p, spec = made
    out = exploring.explore(p.state_dir, spec, now=NOW)
    assert fake.requests == out["requests"] > 0
    for path, form in fake.asks:
        sels = form.get("match[]") or form.get("query") or []
        assert sels or path == "metadata", (path, form)
        assert all('namespace=~"shop|payments"' in s or 'namespace="shop"' in s for s in sels), (path, form)
        if path.startswith("label") or path == "series":
            assert form.get("limit"), (path, form)
        if path == "metadata":
            assert form.get("metric"), form
    lines = reqlog.last(p.state_dir, "shop", 200)
    assert len(lines) == out["requests"] and {x["by"] for x in lines} == {"explore"}


def test_family_glob_and_limit(made, fake):
    p, spec = made
    out = exploring.explore(p.state_dir, spec, family="payments_*", limit=1, now=NOW)
    assert [r["family"] for r in out["families"]] == ["payments_acked_total"]
    assert out["not_surveyed"] == [{"family": "payments_backlog", "in_match": False}]
    text = "\n".join(exploring.table(out))
    assert "family" in text and "in match" in text and "reads as" in text and "queue=2" in text and "payments_backlog" in text


def test_the_daily_cap_refuses_before_anything_is_sent(fake, tmp_path, monkeypatch):
    p = project(tmp_path, monkeypatch, toml(fake.url, "max_requests_per_day = 30"))
    spec = for_project(p).sources[0]
    out = exploring.explore(p.state_dir, spec, now=NOW)
    assert "refused" in out and "may need" in out["refused"] and "it resets at 00:00 UTC" in out["refused"]
    assert fake.requests == 0
    [line] = reqlog.last(p.state_dir, "shop", 5)
    assert line["sent"] is False and line["by"] == "explore"
    assert exploring.explore(p.state_dir, spec, limit=1, now=NOW).get("refused") is None     # one family fits the cap


def test_the_command_prints_the_table_and_json(made, fake, capsys):
    p, _ = made
    assert cli.main(["--repo", str(p.repo_root), "sources", "explore", "--source", "shop", "--json"]) == 0
    got = json.loads(capsys.readouterr().out)
    assert got["source"] == "shop" and len(got["families"]) == 4
    assert cli.main(["--repo", str(p.repo_root), "sources", "explore", "--source", "shop", "--family", "queue_*"]) == 0
    assert "queue_depth" in capsys.readouterr().out
    assert cli.main(["--repo", str(p.repo_root), "sources", "explore", "--source", "nope"]) == 1

