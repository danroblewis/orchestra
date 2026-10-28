"""A Chronosphere-like tenant, reproduced by the fake: busy (429/503 with Retry-After, dropped
connections), size-limited (a 422 above a per-query series limit), and leaned on by two
processes. Reads are batched and split under the limit; counters are read server-side and agree
with the client-side computation; only one caller infers, once at a time, backing off after a
failure and never narrowing; a source with a few reads failed is partial, not missing."""

from __future__ import annotations

import email.utils
import math
import threading
import time
from itertools import pairwise

import pytest
from fake_prometheus import Busy, FakePrometheus

from orchestra.sources import SourceError
from orchestra.sources.batch import Part, run
from orchestra.sources.cache import attempt, cached, definitions
from orchestra.sources.fetch import increments, read_many
from orchestra.sources.listing import listing
from orchestra.sources.prometheus import PrometheusSource
from orchestra.sources.spec import load
from orchestra.sources.views import Definition

NOW = math.floor(time.time() / 60) * 60
T0 = NOW - 3600


def every(seconds, fn, start=T0, end=NOW):
    out, t = [], start
    while t <= end:
        out.append((t, float(fn(t - start))))
        t += seconds
    return out


def spec_for(fake, tmp_path, **kw):
    specs = load({"sources": [{"name": "lab", "url": fake.url, **kw}]}, tmp_path)
    assert not specs.refused, specs.refused
    return specs.sources[0]


def quick(spec) -> PrometheusSource:
    src = PrometheusSource(spec)
    src.slept = []
    src._sleep = src.slept.append
    src.limiter.hold = lambda s: None
    return src


@pytest.fixture
def made():
    fakes = []

    def make(dump, **kw):
        f = FakePrometheus(dump, **kw)
        fakes.append(f)
        return f
    yield make
    for f in fakes:
        f.close()


QUEUES = [("queue_depth", {"queue": q, "pod": f"p{i}"}, every(15, lambda s, k=k: (k * s / 15) % 40)) for k, q in enumerate("abc", 1)
          for i in range(4)]


# Asking a busy store


def test_retry_after_as_an_http_date_is_waited_for(made, tmp_path):
    f = made(QUEUES)
    when = email.utils.formatdate(time.time() + 4, usegmt=True)
    f.refuse = [(429, {"Retry-After": when}, b'{"status":"error","error":"quota"}', "application/json")]
    src = quick(spec_for(f, tmp_path))
    assert src.query_range("count(queue_depth)", T0, NOW, 60)
    assert len(src.slept) == 1 and 2.0 <= src.slept[0] <= 6.0


def test_a_429_pauses_every_reader_of_the_source(made, tmp_path):
    f = made(QUEUES)
    f.refuse = [(429, {"Retry-After": "2"}, b"{}", "application/json")]
    spec = spec_for(f, tmp_path)
    src = PrometheusSource(spec)
    src._sleep = lambda s: None                  # this reader does not wait itself
    held = []
    src.limiter.hold = held.append
    src.query_range("count(queue_depth)", T0, NOW, 60)
    assert held == [2.0]                          # ... but every reader of the bucket is held for the server's wait


def test_a_dropped_connection_is_asked_again(made, tmp_path):
    f = made(QUEUES)
    answer, calls = f.answer, []

    def drop_once(endpoint, form):
        calls.append(endpoint)
        if len(calls) == 1:
            raise ConnectionResetError("dropped")
        return answer(endpoint, form)
    f.answer = drop_once
    src = quick(spec_for(f, tmp_path))
    assert src.query_range("count(queue_depth)", T0, NOW, 60)
    assert src.retries == 1 and len(calls) == 2


def test_the_round_budget_stops_requests_and_counts_retries(made, tmp_path):
    from orchestra.sources.limits import Budget, OverBudget
    f = made(QUEUES)
    f.refuse = [(503, {"Retry-After": "0"}, b"<html/>", "text/html")] * 2
    src = quick(spec_for(f, tmp_path))
    src.budget = Budget(requests=2)
    with pytest.raises(OverBudget):
        src.query_range("count(queue_depth)", T0, NOW, 60)
    assert f.requests == 2


# Batches under the per-query series limit


def test_many_reads_go_in_one_request_and_come_back_apart(made, tmp_path):
    f = made(QUEUES + [("jobs_total", {"queue": q}, every(15, lambda s: s)) for q in "ab"])
    src = quick(spec_for(f, tmp_path))
    got, failed = run(src, [Part("depth", "sum by (queue) (queue_depth)", 12), Part("jobs", "sum(jobs_total)", 2)], T0, NOW, 60)
    assert not failed and f.requests == 1 and " or " in f.queries[0]
    assert {lab["queue"] for lab, _ in got["depth"]} == {"a", "b", "c"} and len(got["jobs"]) == 1
    assert all("orchestra_part" not in lab for rows in got.values() for lab, _ in rows)


def test_a_request_refused_for_its_size_is_split_and_a_part_too_big_alone_is_named(made, tmp_path):
    f = made(QUEUES + [("big", {"i": str(i)}, every(60, lambda s: 1.0)) for i in range(30)])
    f.max_series = 20
    src = quick(spec_for(f, tmp_path, series_per_query=100))     # the source does not know the limit yet
    parts = [Part(f"q{q}", f'sum(queue_depth{{queue="{q}"}})', 4) for q in "abc"] + [Part("big", "sum(big)", 30)]
    got, failed = run(src, parts, T0, NOW, 60)
    assert set(got) == {"qa", "qb", "qc"} and set(failed) == {"big"}
    assert "over the store's per-query series limit" in failed["big"]
    assert src.series_limit == 20                                 # learned from the refusal: later batches stay under it
    f.queries.clear()
    run(src, [Part(f"q{q}", f'sum(queue_depth{{queue="{q}"}})', 4) for q in "abc"] * 2, T0, NOW, 60)
    assert max(f.queries_touched[-len(f.queries):]) <= 18


def test_names_come_from_the_index_and_series_in_batches_split_on_a_422(made, tmp_path):
    dump = [(f"m{k:02d}", {"i": str(i)}, every(60, lambda s: 1.0)) for k in range(40) for i in range(10)]
    dump += [("lat_bucket", {"le": le, "i": str(i)}, every(60, lambda s: 1.0)) for le in ("0.1", "1", "+Inf") for i in range(10)]
    dump += [("lat_count", {"i": str(i)}, every(60, lambda s: 1.0)) for i in range(10)]
    dump += [("huge", {"i": str(i)}, every(60, lambda s: 1.0)) for i in range(120)]
    f = made(dump)
    f.max_series = 100
    src = quick(spec_for(f, tmp_path))
    got = listing(src, ['{__name__=~".+"}'], T0, NOW)
    assert len(got.names) == 42 and all(len(got.names[f"m{k:02d}"]) == 10 for k in range(40))
    assert got.names["lat_bucket"] == [] and len(got.names["lat_count"]) == 10     # buckets are never read: not listed
    assert "huge" in got.too_big and any("huge" in n for n in got.notes)
    assert not any("lat_bucket" in q for q in f.queries)


def test_a_store_without_the_name_index_is_listed_by_series(made, tmp_path):
    f = made(QUEUES)
    f.missing.add("label_values")
    got = listing(quick(spec_for(f, tmp_path)), ['{__name__=~".+"}'], T0, NOW)
    assert len(got.names["queue_depth"]) == 12


# Counters read server-side


def _counter_defn(by: list[str]) -> Definition:
    return Definition(id="c0", source="lab", name="jobs_total", family="jobs_total", view="increments", kind="counter",
                      query="jobs_total", inner="jobs_total", agg="increase", group_by=by, by_real=by, resolution_s=15.0)


def test_a_counter_read_server_side_matches_the_raw_computation_across_resets_and_gaps(made, tmp_path):
    def worker(rate, reset_at, gap):
        pts, v = [], 1000.0
        for t, _ in every(15, lambda s: 0):
            if gap[0] <= t - T0 < gap[1]:
                continue                                   # the scrape failed for a while
            v = (v + rate * 15) if not (reset_at <= t - T0 < reset_at + 15) else 3.0
            pts.append((t, v))
        return pts
    dump = [("jobs_total", {"queue": "a", "pod": "x"}, worker(2.0, 1200, (2000, 2120))),
            ("jobs_total", {"queue": "a", "pod": "y"}, worker(0.5, 2700, (0, 0))),
            ("jobs_total", {"queue": "b", "pod": "z"}, worker(1.0, 99999, (600, 900)))]
    f = made(dump)
    src = quick(spec_for(f, tmp_path))
    d = _counter_defn(["queue"])
    got, errors = read_many(src, [d], "lab", None, T0 + 300, NOW, 30.0)
    assert not errors and "increase(jobs_total[30s])" in f.queries[-1]
    server = {lab["queue"]: pts for _, lab, pts, _ in got["c0"]}
    raw = {lab["queue"]: pts for lab, pts in increments(src.select("jobs_total", T0 + 300 - 15, NOW), ["queue"], T0 + 300)}
    for q in ("a", "b"):
        assert server[q][0][1] == 0.0
        assert server[q][-1][1] == pytest.approx(raw[q][-1][1], rel=0.01)        # the same events over the window
        assert all(b >= a for (_, a), (_, b) in zip(server[q], server[q][1:], strict=False))   # resets never subtract


def test_every_grouping_of_a_family_is_one_read(made, tmp_path):
    f = made(QUEUES)
    src = quick(spec_for(f, tmp_path))
    sel = "last_over_time(queue_depth[46s])"
    defs = [Definition(id=f"d{i}", source="lab", name="queue_depth", family="queue_depth", view="sum_by", kind="level",
                       query="", inner=sel, agg="sum", group_by=by, by_real=by, resolution_s=15.0)
            for i, by in enumerate([[], ["queue"]])]
    defs.append(Definition(id="n", source="lab", name="pods", family="queue_depth", view="count", kind="level", query="",
                           inner=sel, agg="count", group_by=["queue"], by_real=["queue"], resolution_s=15.0))
    got, errors = read_many(src, defs, "lab", None, T0 + 600, NOW, 60.0)
    assert not errors and f.requests == 1                        # the sum and the count, by queue, in one request
    total = got["d0"][0][2]
    by_queue = {lab["queue"]: pts for _, lab, pts, _ in got["d1"]}
    assert total[-1][1] == pytest.approx(sum(p[-1][1] for p in by_queue.values()))
    direct = src.query_range(f"sum({sel})", math.floor((T0 + 600) / 60) * 60, NOW, 60)[0][1]
    assert total == direct
    assert {lab["queue"]: pts[-1][1] for _, lab, pts, _ in got["n"]} == {"a": 4.0, "b": 4.0, "c": 4.0}


# Who infers, and when


def _lab(made, tmp_path, **kw):
    f = made(QUEUES + [("jobs_total", {"queue": q}, every(15, lambda s, k=k: k * s)) for k, q in enumerate("ab", 1)])
    spec = spec_for(f, tmp_path, **kw)
    return f, spec, quick(spec)


def test_a_reader_that_may_not_infer_reads_the_cache_and_never_the_store(made, tmp_path):
    f, spec, src = _lab(made, tmp_path)
    with pytest.raises(SourceError, match="not inferred yet"):
        definitions(src, spec, [], tmp_path, tmp_path / "state", T0, NOW, infer_ok=False)
    assert f.requests == 0
    inf = definitions(src, spec, [], tmp_path, tmp_path / "state", T0, NOW)
    n = f.requests
    again = definitions(src, spec, [], tmp_path, tmp_path / "state", T0, NOW, infer_ok=False)
    assert f.requests == n and [d.name for d in again.kept] == [d.name for d in inf.kept]


def test_a_failed_round_backs_off_instead_of_hammering_the_store(made, tmp_path):
    f, spec, src = _lab(made, tmp_path)
    f.fail_status = 500
    with pytest.raises(SourceError):
        definitions(src, spec, [], tmp_path, tmp_path / "state", T0, NOW)
    n = f.requests
    with pytest.raises(SourceError, match="the next is not before"):
        definitions(src, spec, [], tmp_path, tmp_path / "state", T0, NOW)
    assert f.requests == n and attempt(tmp_path / "state", "lab")["failures"] == 1
    f.fail_status = None
    assert definitions(src, spec, [], tmp_path, tmp_path / "state", T0, NOW, refresh=True).kept   # the CLI's refresh tries at once
    assert attempt(tmp_path / "state", "lab") == {}


def test_a_narrower_round_never_replaces_a_broader_one(made, tmp_path):
    f, spec, src = _lab(made, tmp_path, infer_every="1s")
    broad = definitions(src, spec, [], tmp_path, tmp_path / "state", T0, NOW)
    time.sleep(1.1)
    n = f.requests
    narrow = definitions(src, spec, [], tmp_path, tmp_path / "state", NOW - 900, NOW)
    assert f.requests == n and narrow.at == broad.at and "would replace one over 60 min" in narrow.error
    assert cached(tmp_path / "state", "lab").window == [T0, NOW]


def test_two_callers_never_infer_at_once(made, tmp_path):
    f, spec, _ = _lab(made, tmp_path)
    f.latency = 0.05
    out = []

    def go():
        out.append(definitions(quick(spec), spec, [], tmp_path, tmp_path / "state", T0, NOW))
    threads = [threading.Thread(target=go) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(out) == 2 and out[0].at == out[1].at           # the second waited for the first's round and used it


# A source with a few reads failed


def test_a_source_with_a_few_reads_failed_is_partial_and_names_them(tmp_path, monkeypatch, made):
    from helpers import project

    from orchestra.sources.catalogue import Catalogue
    dump = [(f"gauge_{k:02d}", {"queue": q}, every(15, lambda s, k=k: ((k + 1) * s / 15) % 40)) for k in range(12) for q in "ab"]
    f = made(dump)
    p = project(tmp_path, monkeypatch, f"""
[discovery]
window = "60m"
step = "60s"

[[sources]]
name = "lab"
url = "{f.url}"
""")
    cat = Catalogue(p, None)
    inf = cat.inference("lab", T0, NOW)
    assert len({d.family for d in inf.kept}) == 12
    answer = f.answer

    def one_busy(endpoint, form):
        if "gauge_03" in (form.get("query") or [""])[0]:
            raise Busy()
        return answer(endpoint, form)
    f.answer = one_busy
    p.config.raw["sources"][0]["series_per_query"] = 1          # one family a request, so one fails alone
    cat = Catalogue(p, None)
    cat.remotes["lab"]._sleep = lambda s: None
    r = cat.read(T0, NOW, 60.0)
    st = r.status["lab"]
    assert st["ok"] and st["partial"] and not r.missing
    assert st["failed"] and all("gauge_03" in x for x in st["failed"]) and "HTTP 503" in st["failed"][0]
    assert any(n == "lab:gauge_00" for n, _, _ in r.dump) and not any(n == "lab:gauge_03" for n, _, _ in r.dump)
    f.answer = lambda endpoint, form: (_ for _ in ()).throw(Busy()) if endpoint == "query_range" else answer(endpoint, form)
    r = Catalogue(p, None)
    r.remotes["lab"]._sleep = lambda s: None
    gone = r.read(T0, NOW, 60.0)
    assert "lab" in gone.missing and "reads failed" in gone.missing["lab"]


def test_a_counter_read_server_side_is_declared_at_the_grid_it_was_read_on(tmp_path, monkeypatch, made):
    """A counter scraped every 30 s is read on a 60 s grid (two samples a step): discovery must
    expect a point every 60 s, or it takes every other step for a silence."""
    from helpers import project

    from orchestra.sources.catalogue import Catalogue
    f = made([("jobs_total", {"queue": q}, every(30, lambda s, k=k: k * s)) for k, q in enumerate("ab", 1)]
             + [("queue_depth", {"queue": q}, every(30, lambda s, k=k: (k * s / 30) % 9)) for k, q in enumerate("ab", 1)])
    p = project(tmp_path, monkeypatch, f"""
[discovery]
window = "60m"
step = "30s"

[[sources]]
name = "lab"
url = "{f.url}"
""")
    r = Catalogue(p, None).read(T0, NOW, 30.0)
    counter = next(k for k in r.kinds if k.startswith("lab:jobs_total"))
    level = next(k for k in r.kinds if k.startswith("lab:queue_depth"))
    assert r.kinds[counter].resolution_s == 60.0 and r.provenance[counter]["resolution_s"] == 60.0
    assert r.kinds[level].resolution_s == 30.0
    pts = next(p for n, lab, p in r.dump if n == "lab:jobs_total" and not lab)
    assert {b - a for (a, _), (b, _) in pairwise(pts)} == {60.0}


def test_a_counter_that_began_inside_the_window_starts_there(made, tmp_path):
    """Pods started 50 minutes into the hour: their counter's running total starts one step before
    its first increase, not at the window's start (a 0 there would read as a write, then silence)."""
    f = made([("cart_requests_total", {"pod": "new"}, every(15, lambda s: 2 * s, start=T0 + 3000))])
    src = quick(spec_for(f, tmp_path))
    d = _counter_defn([])
    d.query = d.inner = d.name = d.family = "cart_requests_total"
    got, errors = read_many(src, [d], "lab", None, T0 + 60, NOW, 30.0)
    (_, _, pts, _), = got["c0"]
    assert not errors and pts[0][0] >= T0 + 3000 - 30 and pts[0][1] == 0.0
    assert all(b - a == 30.0 for (a, _), (b, _) in pairwise(pts))
