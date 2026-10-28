"""What reading another company's store costs it (review r3, cost): one bucket and one daily cap per
store, a share for the web server, reads that ask only for what is new, refusals remembered, and
inference that stops paying for rounds that cannot succeed. Pure, with fake clocks and sources."""

from __future__ import annotations

import json
import time

import pytest

from orchestra.sources import SourceError
from orchestra.sources import cache as cache_mod
from orchestra.sources.cache import STOP_AFTER, attempt, definitions
from orchestra.sources.infer import Inference
from orchestra.sources.limits import DailyCap, RateLimit, store_key
from orchestra.sources.listing import TooManyNames
from orchestra.sources.readcache import REFILL, RESETTLE, ReadCache
from orchestra.sources.spec import DECLARED_INFER_EVERY, load
from orchestra.sources.transport import TooBig, time_helps


class Clock:
    def __init__(self, t: float = 1_800_000_000.0):
        self.t = t
        self.slept: list[float] = []

    def __call__(self) -> float:
        return self.t

    def sleep(self, s: float) -> None:
        self.slept.append(s)
        self.t += s


# -- one store, one bucket ------------------------------------------------------------------------

def test_a_store_is_its_url_and_tenant_never_the_source_name_or_credential():
    a = store_key("https://t.example/data/metrics/")
    assert a == store_key("HTTPS://t.example:443/data/metrics")          # one store however it is spelled
    assert a != store_key("https://t.example/other")
    assert a != store_key("https://t.example/data/metrics", [{"name": "X-Scope-OrgID", "value": "team-a"}])
    # a credential is never part of the key: two readers with their own tokens read one tenant
    assert a == store_key("https://t.example/data/metrics", [{"name": "API-Token", "value_env": "TOKEN"}])


def test_two_sources_and_two_projects_on_one_store_share_one_bucket(tmp_path, monkeypatch):
    monkeypatch.setenv("ORCHESTRATOR_HOME", str(tmp_path / "home"))
    from orchestra.sources.limits import for_store
    specs = load({"sources": [{"name": "shop", "url": "http://127.0.0.1:9/x"}, {"name": "undeclared", "url": "http://127.0.0.1:9/x/"}]},
                 tmp_path)
    a, b = (for_store(s) for s in specs.sources)
    assert a.path == b.path and a.path.is_relative_to(tmp_path / "home" / "stores")
    a.take()
    b.take()
    assert a.today() == 2 == b.today()


def test_the_daily_cap_refuses_with_what_to_do_and_resets_the_next_day(tmp_path):
    c = Clock()
    rl = RateLimit(100, 100, tmp_path / "rate", per_day=3, sleep=c.sleep, clock=c)
    for _ in range(3):
        rl.take()
    with pytest.raises(DailyCap, match="max_requests_per_day") as e:
        rl.take(where="http://x/api/v1/query")
    assert "raise" not in str(e.value) and "00:00 UTC" in str(e.value)
    other = RateLimit(100, 100, tmp_path / "rate", per_day=3, sleep=c.sleep, clock=c)   # another process: the same count
    with pytest.raises(DailyCap):
        other.take()
    c.t += 86400
    rl.take()
    assert rl.today() == 1


def test_the_web_share_paces_the_web_and_counts_against_the_store(tmp_path):
    c = Clock()
    store = RateLimit(10, 10, tmp_path / "rate", per_day=1000, sleep=c.sleep, clock=c)
    web = RateLimit(2, 2, tmp_path / "web.rate", per_day=200, parent=store, sleep=c.sleep, clock=c)
    for _ in range(6):
        web.take()
    assert sum(c.slept) == pytest.approx(2.0)          # two at once, then two a second
    assert store.today() == 6 and web.today() == 6
    for _ in range(10):                                # discovery still has the store's own burst
        store.take()
    assert store.today() == 16


# -- reads that ask only for what is new ----------------------------------------------------------

def rows(t0: float, t1: float, step: float, f=lambda t: t) -> list:
    return [({"q": "a"}, [(t, f(t)) for t in range(int(t0), int(t1) + 1, int(step))])]


def test_a_sliding_window_is_read_whole_once_then_only_its_new_end():
    c = Clock(10_000.0)
    cache = ReadCache("s", clock=c)
    assert cache.plan("k", 6390, 9990, 30) == (6390, 9990)
    cache.put("k", rows(6390, 9990, 30), 6390, 9990, whole=True)
    assert cache.plan("k", 6390, 9990, 30) is None                       # nothing new: nothing asked
    a, b = cache.plan("k", 6690, 10_290, 30, resettle=60)
    assert b == 10_290 and a == (9990 - RESETTLE) // 30 * 30            # the new end, and a little before it, on the grid
    cache.put("k", rows(a, b, 30, lambda t: -t), a, b)                   # what the store says now replaces what was kept
    got = cache.get("k", 6690, 10_290)[0][1]
    assert got[0] == (6690, 6690) and got[-1] == (10_290, -10_290) and dict(got)[a] == -a and dict(got)[a - 30] == a - 30
    assert [t for t, _ in got] == list(range(6690, 10_291, 30))


def test_a_window_reaching_before_what_is_kept_or_an_hour_old_entry_is_read_whole():
    c = Clock(10_000.0)
    cache = ReadCache("s", clock=c)
    cache.put("k", rows(7000, 10_000, 30), 7000, 10_000, whole=True)
    assert cache.plan("k", 6400, 10_300, 30) == (6400, 10_300)
    c.t += REFILL + 1
    assert cache.plan("k", 7300, 10_300, 30) == (7300, 10_300)


def test_the_hosts_reads_are_kept_in_a_file_others_start_from(tmp_path):
    c = Clock(10_000.0)
    host = ReadCache("store-a", tmp_path / "s.reads.json", clock=c)
    host.plan("k", 6400, 10_000, 30)
    host.put("k", rows(6400, 10_000, 30), 6400, 10_000, whole=True)
    host.refuse("big", "over the store's per-query series limit: HTTP 422")
    host.save()
    web = ReadCache("store-a", clock=c)
    web.absorb(tmp_path / "s.reads.json")
    assert web.get("k", 6400, 10_000) == host.get("k", 6400, 10_000)
    assert web.plan("k", 6400, 10_000, 30) is None and "not asked again" in web.refusal("big")
    elsewhere = ReadCache("store-b", tmp_path / "s.reads.json", clock=c)  # the file of another store is of no use
    elsewhere.load()
    assert elsewhere.entries == {}


def test_a_refusal_is_remembered_for_an_hour():
    c = Clock()
    cache = ReadCache("s", clock=c)
    cache.refuse("k", "over the store's per-query series limit: HTTP 422")
    assert cache.refusal("k").startswith("over the store's per-query series limit")
    c.t += REFILL + 1
    assert cache.refusal("k") is None


def test_a_series_refusal_is_halved_by_time_only_while_that_sheds_series():
    first = TooBig("HTTP 422: query matched 6490 series, over the limit of 2500 series per query")
    assert first.by_series and first.matched == 6490
    assert time_helps(first, None)                                       # once
    same = TooBig("HTTP 422: query matched 6400 series, over the limit of 2500 series per query")
    assert not time_helps(same, first)                                   # a stable metric: the half touches as many
    churned = TooBig("HTTP 422: query matched 3000 series, over the limit of 2500 series per query")
    assert time_helps(churned, first)                                    # pods replaced: halving sheds them
    assert time_helps(TooBig("HTTP 422: exceeded maximum resolution of 11,000 points"), first)


# -- inference that cannot succeed stops ----------------------------------------------------------

def _spec(tmp_path, **extra):
    return load({"sources": [{"name": "big", "url": "http://127.0.0.1:9", **extra}]}, tmp_path).sources[0]


def test_inference_failing_for_its_cost_backs_off_harder_then_stops_until_the_settings_change(tmp_path, monkeypatch):
    spec = _spec(tmp_path)
    calls = []

    def costly(*a, **k):
        calls.append(1)
        from orchestra.sources.limits import OverBudget
        raise OverBudget("the inference round made its 1500 requests (its budget)")
    monkeypatch.setattr(cache_mod, "infer", costly)
    waits = []
    for _ in range(STOP_AFTER):
        with pytest.raises(SourceError):
            definitions(None, spec, [], tmp_path, tmp_path, 0, 3600)
        a = attempt(tmp_path, "big")
        waits.append(a["next"] - a["at"])
        cache_mod._write(cache_mod._dir(tmp_path) / "big.attempt.json", json.dumps({**a, "next": 0}))   # its wait passed
    assert waits[1] == pytest.approx(4 * waits[0], rel=0.01) and attempt(tmp_path, "big")["stopped"]
    with pytest.raises(SourceError, match="none runs until"):
        definitions(None, spec, [], tmp_path, tmp_path, 0, 3600)
    assert len(calls) == STOP_AFTER
    narrowed = _spec(tmp_path, match=['{__name__=~"queue_.*"}'])        # the settings changed: one round runs
    with pytest.raises(SourceError):
        definitions(None, narrowed, [], tmp_path, tmp_path, 0, 3600)
    assert len(calls) == STOP_AFTER + 1


def test_a_store_too_big_to_list_stops_inference_at_once(tmp_path, monkeypatch):
    spec = _spec(tmp_path)
    monkeypatch.setattr(cache_mod, "infer", lambda *a, **k: (_ for _ in ()).throw(TooManyNames("the store holds 50000 metric names")))
    with pytest.raises(TooManyNames):
        definitions(None, spec, [], tmp_path, tmp_path, 0, 3600)
    assert attempt(tmp_path, "big")["stopped"]


def test_a_store_that_does_not_answer_is_tried_again_and_never_stopped(tmp_path, monkeypatch):
    spec = _spec(tmp_path)
    monkeypatch.setattr(cache_mod, "infer", lambda *a, **k: (_ for _ in ()).throw(SourceError("connection refused")))
    for _ in range(STOP_AFTER + 1):
        with pytest.raises(SourceError):
            definitions(None, spec, [], tmp_path, tmp_path, 0, 3600)
        a = attempt(tmp_path, "big")
        cache_mod._write(cache_mod._dir(tmp_path) / "big.attempt.json", json.dumps({**a, "next": 0}))
    assert not attempt(tmp_path, "big")["stopped"]


def test_a_stopped_source_keeps_its_cached_definitions(tmp_path, monkeypatch):
    spec = _spec(tmp_path)
    from orchestra.sources.infer import settings_key
    old = Inference("big", time.time() - 7200, settings_key(spec, [], tmp_path), window=[0, 3600])
    cache_mod.save(tmp_path, old)
    monkeypatch.setattr(cache_mod, "infer", lambda *a, **k: (_ for _ in ()).throw(TooManyNames("too many names")))
    got = definitions(None, spec, [], tmp_path, tmp_path, 0, 3600)
    assert got.at == old.at and "no next try until the settings change" in got.error
    got = definitions(None, spec, [], tmp_path, tmp_path, 0, 3600)
    assert "none runs until" in got.error


def test_a_source_that_declares_its_series_infers_less_often_unless_told():
    raw = {"sources": [{"name": "a", "url": "http://x:1"}, {"name": "b", "url": "http://x:2", "infer_every": "30m"},
                       {"name": "c", "url": "http://x:3"}],
           "series": [{"source": "a", "name": "q", "query": "sum(q)"}, {"source": "b", "name": "q", "query": "sum(q)"}]}
    a, b, c = load(raw, ".").sources
    assert a.infer_every == DECLARED_INFER_EVERY and b.infer_every == 1800 and c.infer_every == 3600
