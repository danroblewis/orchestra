"""One conformance suite for every source: the own store, the fake Prometheus, and a real server.

The own store (the file backend) and the fake always run. A real Prometheus-compatible server
runs when its URL is set (see README.md):
  ORCHESTRA_TEST_PROM_URL          where it is read, e.g. the rig's proxy http://127.0.0.1:8432
  ORCHESTRA_TEST_PROM_TOKEN_FILE   the bearer token for it, e.g. ~/.orchestra-sources-rig/token
  ORCHESTRA_TEST_PROM_IMPORT_URL   a VictoriaMetrics to write the test's points to, e.g. http://127.0.0.1:8431
Each test writes series of its own names and removes them afterwards."""

from __future__ import annotations

import json
import os
import time
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

import pytest
from fake_prometheus import FakePrometheus

from orchestra.metrics import Point
from orchestra.metrics.file import FileMetrics
from orchestra.sources import SourceError
from orchestra.sources.auth import AuthSpec
from orchestra.sources.fetch import increments
from orchestra.sources.own import OwnSource
from orchestra.sources.prometheus import PrometheusSource
from orchestra.sources.spec import SourceSpec

REAL = os.environ.get("ORCHESTRA_TEST_PROM_URL")
TOKEN_FILE = os.environ.get("ORCHESTRA_TEST_PROM_TOKEN_FILE")
IMPORT = os.environ.get("ORCHESTRA_TEST_PROM_IMPORT_URL")
T0 = (int(time.time()) // 3600 - 2) * 3600          # two hours ago, on the hour: inside any retention


def _vm(path: str, body: bytes | None = None, params: dict | None = None) -> None:
    url = IMPORT.rstrip("/") + path + ("?" + urllib.parse.urlencode(params, doseq=True) if params else "")
    with urllib.request.urlopen(urllib.request.Request(url, data=body, method="POST" if body is not None else "GET"), timeout=30):
        pass


@pytest.fixture(params=["own", "fake", "prometheus"])
def make(request, tmp_path):
    """A source holding exactly ``dump`` (name, labels, points), with the series' names made
    unique for the test; returns (source, the unique prefix of the names)."""
    kind = request.param
    pre = f"conf_{uuid.uuid4().hex[:8]}_"
    closers = []

    def build(dump, **spec_kw):
        dump = [(pre + n, labels, pts) for n, labels, pts in dump]
        if kind == "own":
            store = FileMetrics(tmp_path / "metrics.jsonl")
            store.write([Point(n, v, t, {**labels, "project": "p"}) for n, labels, pts in dump for t, v in pts])
            return OwnSource(store, "p")
        if kind == "fake":
            fake = build.fake = FakePrometheus(dump, token="t0ken")
            closers.append(fake.close)
            (tmp_path / "tok").write_text("t0ken")
            return PrometheusSource(SourceSpec("fake", "prometheus", fake.url, "fake", AuthSpec(bearer_file=str(tmp_path / "tok")), **spec_kw))
        if not (REAL and IMPORT):
            pytest.skip("set ORCHESTRA_TEST_PROM_URL and ORCHESTRA_TEST_PROM_IMPORT_URL to run against a real server")
        body = "".join(json.dumps({"metric": {"__name__": n, **labels}, "values": [v for _, v in pts],
                                   "timestamps": [int(t * 1000) for t, _ in pts]}) + "\n" for n, labels, pts in dump)
        _vm("/api/v1/import", body.encode())
        _vm("/internal/force_flush")
        closers.append(lambda: _vm("/api/v1/admin/tsdb/delete_series", b"", {"match[]": f'{{__name__=~"{pre}.*"}}'}))
        return PrometheusSource(SourceSpec("real", "prometheus", REAL, "real",
                                           AuthSpec(bearer_file=TOKEN_FILE) if TOKEN_FILE else AuthSpec(), **spec_kw))

    build.kind, build.pre = kind, pre
    yield build
    for c in closers:
        c()


def gauge(n=10, start=T0, every=60.0, f=lambda k: float(k % 5)):
    return [(start + every * k, f(k)) for k in range(n)]


def test_query_range_samples_the_grid(make):
    src = make([("level", {"svc": "a"}, gauge()), ("level", {"svc": "b"}, gauge(f=lambda k: 10.0 + k))])
    got = {lab["svc"]: pts for lab, pts in src.query_range(f"{make.pre}level", T0, T0 + 540, 60)}
    assert got["a"] == gauge() and got["b"] == gauge(f=lambda k: 10.0 + k)


def test_aggregations_and_counts(make):
    pods = [("lat", {"svc": "a", "pod": "a1", "stat": "p95"}, gauge(f=lambda k: 1.0 + k)),
            ("lat", {"svc": "a", "pod": "a2", "stat": "p95"}, gauge(n=5, f=lambda k: 20.0)),        # stops after 5 minutes
            ("lat", {"svc": "a", "pod": "a3", "stat": "p95"}, gauge(n=5, start=T0 + 300, f=lambda k: 3.0)),   # starts then
            ("lat", {"svc": "a", "pod": "a1", "stat": "p50"}, gauge(f=lambda k: 0.5))]
    src = make(pods)
    sel = f'last_over_time({make.pre}lat{{stat="p95"}}[61s])'
    mx = src.query_range(f"max by (svc) ({sel})", T0, T0 + 540, 60)
    assert [lab for lab, _ in mx] == [{"svc": "a"}]
    # a2's last sample is at minute 4: a window of 61 s still holds it at minute 5, as a3 starts
    assert [v for _, v in mx[0][1]] == [20.0] * 6 + [7.0, 8.0, 9.0, 10.0]
    n = src.query_range(f"count by (svc) ({sel})", T0, T0 + 540, 60)
    assert [v for _, v in n[0][1]] == [2.0] * 5 + [3.0] + [2.0] * 4
    total = src.query_range(f'count(count by (pod) (last_over_time({make.pre}lat[61s])))', T0 + 240, T0 + 300, 60)
    assert [v for _, v in total[0][1]] == [2.0, 3.0]             # at the hand-over, a2 is still within the window


def test_select_keeps_real_sample_times(make):
    pts = [(T0 + 7.25, 1.0), (T0 + 61.5, 2.0), (T0 + 133.0, 0.0), (T0 + 190.0, 4.0)]
    src = make([("jobs_total", {"svc": "a", "pod": "p1"}, pts)])
    got = src.select(f'{make.pre}jobs_total{{svc="a"}}', T0, T0 + 600)
    assert got == [({"__name__": f"{make.pre}jobs_total", "svc": "a", "pod": "p1"}, pts)]
    assert src.select(f"{make.pre}jobs_total", T0 + 100, T0 + 600)[0][1] == pts[2:]
    # increments, reset-safe, the first sample a baseline: 1→2 is 1, the drop to 0 is a reset (0 counted), 0→4 is 4
    assert increments(got, ["svc"]) == [({"svc": "a"}, [(T0 + 7.25, 0.0), (T0 + 61.5, 1.0), (T0 + 133.0, 1.0), (T0 + 190.0, 5.0)])]


def test_series_lists_label_sets(make):
    src = make([("lat", {"svc": "a", "stat": "p95"}, gauge()), ("lat", {"svc": "b", "stat": "p95"}, gauge()),
                ("other", {"x": "1"}, gauge())])
    got = src.series([f'{{__name__=~"{make.pre}lat"}}'], T0, T0 + 600)
    assert sorted(x["svc"] for x in got) == ["a", "b"] and all(x["__name__"] == f"{make.pre}lat" for x in got)
    assert len(src.series([f'{{__name__=~"{make.pre}.*"}}'], T0, T0 + 600, limit=2)) == 2


def test_health(make):
    src = make([("level", {}, gauge())])
    h = src.health()
    assert h.ok and h.endpoints["query_range"] and h.endpoints["query"] and h.endpoints["series"], h


def test_long_ranges_are_read_in_chunks(make):
    if make.kind == "own":
        pytest.skip("the own store has no point limit")
    src = make([("level", {"svc": "a"}, gauge(n=60))], max_points=7)
    got = src.query_range(f"{make.pre}level", T0, T0 + 59 * 60, 60)
    assert got[0][1] == gauge(n=60) and src.requests >= 9


def test_wrong_credentials_are_refused_without_showing_them(make, tmp_path):
    if make.kind == "own" or (make.kind == "prometheus" and not TOKEN_FILE):
        pytest.skip("needs a server that demands a token")
    src = make([("level", {}, gauge())])
    (tmp_path / "bad").write_text("not-the-token")
    bad = PrometheusSource(SourceSpec("x", "prometheus", src.spec.url, "x", AuthSpec(bearer_file=str(tmp_path / "bad"))))
    with pytest.raises(SourceError, match="401") as e:
        bad.query_range(f"{make.pre}level", T0, T0 + 60, 60)
    assert "not-the-token" not in str(e.value) and Path(tmp_path / "bad").read_text() not in str(e.value)


def test_nan_and_inf_are_dropped(make):
    if make.kind != "fake":
        pytest.skip("only the fake can serve NaN on request")
    src = make([("level", {}, gauge())])
    make.fake.nan_at = {T0 + 60.0, T0 + 120.0}
    got = src.query_range(f"{make.pre}level", T0, T0 + 540, 60)
    assert [t for t, _ in got[0][1]] == [T0 + 60.0 * k for k in range(10) if k not in (1, 2)]
