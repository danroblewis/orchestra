"""A managed store is busy, rate-limited and size-limited: a 429 or 503 is waited out for the
``Retry-After`` the server gave (never past the read's deadline, and an HTML body is no problem);
a read refused for its size (422) is narrowed, by metric name and by time, and joined, never
abandoned and never answered with less; a timeout says which setting to change."""

from __future__ import annotations

import email.utils
import time

import pytest
from fake_prometheus import FakePrometheus

from orchestra.sources import PastDeadline, SourceError
from orchestra.sources.prometheus import RETRIES, PrometheusSource, TooBig, _with_name, retry_after
from orchestra.sources.spec import load

T0 = 1_800_000_000.0
HTML = b"<html><body><h1>503 Service Unavailable</h1></body></html>"


def _source(fake: FakePrometheus, tmp_path, **extra) -> PrometheusSource:
    specs = load({"sources": [{"name": "busy", "url": fake.url, **extra}]}, tmp_path)
    assert not specs.refused, specs.refused
    src = PrometheusSource(specs.sources[0])
    src.slept = []
    src._sleep = src.slept.append            # no real waiting in tests: record what it would wait
    src.limiter.hold = lambda seconds: None  # nor for the other readers' pause (tests/unit/test_sources_limits.py)
    return src


@pytest.fixture
def fake():
    dump = [("queue_depth", {"queue": q}, [(T0 + 15 * i, float(i)) for i in range(240)]) for q in ("a", "b", "c")]
    dump += [("jobs_done_total", {"queue": q}, [(T0 + 15 * i, float(2 * i)) for i in range(240)]) for q in ("a", "b", "c")]
    f = FakePrometheus(dump)
    yield f
    f.close()


def test_a_429_is_retried_after_the_seconds_the_server_gave(fake, tmp_path):
    fake.refuse = [(429, {"Retry-After": "3"}, b'{"status":"error","error":"quota exhausted"}', "application/json")]
    src = _source(fake, tmp_path)
    got = src.query_range("queue_depth", T0, T0 + 600, 15)
    assert len(got) == 3 and len(src.slept) == 1 and 3.0 <= src.slept[0] <= 3.6 and src.retries == 1   # plus jitter


def test_a_503_with_an_html_page_is_retried_and_never_parsed(fake, tmp_path):
    fake.refuse = [(503, {"Retry-After": "1"}, HTML, "text/html"), (503, {}, HTML, "text/html")]
    src = _source(fake, tmp_path)
    assert len(src.series(['{__name__="queue_depth"}'], T0, T0 + 600)) == 3
    first, then = src.slept                  # the server's wait (plus jitter), then the doubling pause without one
    assert 1.0 <= first <= 1.2 and 1.0 <= then <= 2.0


def test_a_store_that_stays_busy_is_named_by_its_status_after_the_last_try(fake, tmp_path):
    fake.refuse = [(503, {"Retry-After": "1"}, HTML, "text/html")] * (RETRIES + 1)
    src = _source(fake, tmp_path)
    with pytest.raises(SourceError, match=r"HTTP 503$"):
        src.query_range("queue_depth", T0, T0 + 600, 15)
    assert len(src.slept) == RETRIES and fake.requests == RETRIES + 1


def test_a_wait_that_would_pass_the_deadline_stops_the_read_without_waiting(fake, tmp_path):
    fake.refuse = [(429, {"Retry-After": "20"}, b"{}", "application/json")]
    src = _source(fake, tmp_path)
    with pytest.raises(PastDeadline, match="deadline"):
        src.query_range("queue_depth", T0, T0 + 600, 15, until=time.monotonic() + 5)
    assert src.slept == []


def test_retry_after_reads_seconds_and_dates_and_caps_neither_here():
    now = 1_000_000.0
    assert retry_after("7") == 7.0 and retry_after(" 2.5 ") == 2.5 and retry_after(None) is None
    assert retry_after(email.utils.formatdate(now + 12, usegmt=True), now) == pytest.approx(12, abs=1)
    assert retry_after("soon") is None


def test_a_listing_refused_for_its_size_is_read_metric_by_metric(fake, tmp_path):
    fake.max_series = 4                      # six series in all, three per metric
    src = _source(fake, tmp_path)
    got = src.series(['{__name__=~"queue_depth|jobs_done_total"}'], T0, T0 + 3600)
    assert len(got) == 6 and src.narrowed == 1 and src.left_out == []


def test_a_metric_too_big_even_alone_is_split_by_time_then_named_as_left_out(tmp_path):
    churn = [("pod_info", {"pod": f"p{i}"}, [(T0 + 600 * i + 15 * k, 1.0) for k in range(40)]) for i in range(8)]
    wide = [("node_up", {"node": f"n{i}"}, [(T0 + 15 * k, 1.0) for k in range(400)]) for i in range(5)]
    f = FakePrometheus(churn + wide + [("queue_depth", {}, [(T0, 1.0)])])
    try:
        f.max_series = 4
        src = _source(f, tmp_path)
        got = src.series(['{__name__=~".+"}'], T0, T0 + 6000)
        names = [g["__name__"] for g in got]
        assert names.count("pod_info") == 8  # churning pods: few at a time, so halving the range answers
        assert names.count("queue_depth") == 1
        assert "node_up" not in names and len(src.left_out) == 1 and "node_up" in src.left_out[0]
    finally:
        f.close()


def test_a_range_query_and_a_raw_read_refused_for_their_size_are_split_by_time(tmp_path):
    churn = [("pod_info", {"pod": f"p{i}"}, [(T0 + 900 * i + 15 * k, 1.0) for k in range(50)]) for i in range(8)]
    f = FakePrometheus(churn)
    try:
        f.max_series = 3
        src = _source(f, tmp_path)
        whole = _source(f, tmp_path).select("pod_info", T0, T0 + 7200)
        f.max_series = 3
        src = _source(f, tmp_path)
        got = src.query_range("pod_info", T0, T0 + 7200, 15)
        assert len(got) == 8 and src.narrowed >= 1
        raw = src.select("pod_info", T0, T0 + 7200)
        assert sorted(raw, key=str) == sorted(whole, key=str)
    finally:
        f.close()


def test_a_query_too_big_at_the_shortest_range_is_raised_as_too_big(tmp_path):
    wide = [("node_up", {"node": f"n{i}"}, [(T0 + 15 * k, 1.0) for k in range(400)]) for i in range(5)]
    f = FakePrometheus(wide)
    try:
        f.max_series = 4
        with pytest.raises(TooBig, match="422"):
            _source(f, tmp_path).query_range("node_up", T0, T0 + 6000, 15)
    finally:
        f.close()


def test_a_timeout_names_the_setting(fake, tmp_path):
    fake.latency = 1.5
    src = _source(fake, tmp_path, timeout="1s")
    with pytest.raises(SourceError, match="timeout of 1 s"):
        src.series(['{__name__="queue_depth"}'], T0, T0 + 600)


def test_a_selector_is_narrowed_to_one_name_only_when_it_names_none():
    assert _with_name('{__name__=~"a.*"}', "ab") == '{__name__="ab",__name__=~"a.*"}'
    assert _with_name("{}", "x") == '{__name__="x"}'
    assert _with_name('up{job="a"}', "up") is None


class _Late(PrometheusSource):
    """A store slow on some queries: a probe of them (read at the series' resolution, unlike the
    schema's coarser reads) is past the deadline. One part a request (``series_per_query = 1``)."""

    late = ("jobs_done",)

    def query_range(self, query, start, end, step, until=None, **kw):
        if any(x in query for x in self.late) and step < 100 and end - start > step:
            raise PastDeadline("past the deadline")
        return super().query_range(query, start, end, step, until, **kw)


def test_probes_past_the_deadline_leave_their_candidates_out_and_the_round_partial(tmp_path):
    from orchestra.sources.infer import infer
    now = time.time()
    pts = lambda f: [(now - 3600 + 15 * i, f(i)) for i in range(240)]
    dump = [("queue_depth", {"queue": q}, pts(lambda i, k=k: float((i * k) % 17))) for k, q in enumerate("abc", 1)]
    dump += [("pods_running", {}, pts(lambda i: float(i % 5)))]
    dump += [("jobs_done_total", {"queue": q}, pts(lambda i, k=k: float(k * i))) for k, q in enumerate("abc", 1)]
    f = FakePrometheus(dump)
    try:
        spec = load({"sources": [{"name": "busy", "url": f.url, "series_per_query": 1}]}, tmp_path).sources[0]
        inf = infer(_Late(spec), spec, [], tmp_path, now - 3600, now)
        assert inf.partial and any("not probed this round" in d.why for d in inf.left_out)
        assert not any("jobs_done" in d.query for d in inf.kept) and inf.kept
        _Late.late = ("queue_depth", "jobs_done", "pods_running")
        with pytest.raises(SourceError, match="narrow match, or raise infer_deadline"):
            infer(_Late(spec), spec, [], tmp_path, now - 3600, now)
    finally:
        _Late.late = ("jobs_done",)
        f.close()
