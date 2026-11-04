"""A latency family with a sum and a count offers an **occupancy** view: the calls in progress, its
busy time over the interval (Little's law), by the family's groupings, its moves the completions
by status (``views.py``, ``sd.construction``); a summary's count per interval is a flow, never a
level; and ``kinds`` on a source says what a metric is over inference's reading (``kinds.py``).
Against the fake."""

from __future__ import annotations

import math
import time
from itertools import pairwise
from pathlib import Path

import pytest
from fake_prometheus import FakePrometheus

from orchestra.sources.catalogue import provenance
from orchestra.sources.fetch import read as read_definition
from orchestra.sources.prometheus import PrometheusSource
from orchestra.sources.schema import read
from orchestra.sources.spec import load
from orchestra.sources.views import LITTLE, views

NOW = math.floor(time.time() / 60) * 60
T0 = NOW - 3600
METHODS, STATUSES = ["Get", "Put"], ["passed", "failed"]
CALLS = {("Get", "passed"): 120, ("Get", "failed"): 6, ("Put", "passed"): 30, ("Put", "failed"): 3}   # calls a minute
MILLIS = {"Get": 50.0, "Put": 400.0}                                                                 # each call's latency


def wave(x: float) -> float:
    """Each minute's share of the usual calls: up and down, as a per-interval count is."""
    return 1.0 + ((x // 60) % 3) / 2


def every(fn, step=60):
    return [(float(t), float(fn(t - T0))) for t in range(int(T0), int(NOW) + 1, step)]


def rules(count_only: bool = False) -> list:
    """The owner's ``grpc_client_callMillis`` as recording rules: each minute's total milliseconds
    (``:sum``) and calls (``:count``), by method and status."""
    out = []
    for (m, st), n in CALLS.items():
        lab = {"method": m, "status": st}
        out.append(("grpc_client_callMillis:count", lab, every(lambda x, n=n: n * wave(x))))
        if not count_only:
            out.append(("grpc_client_callMillis:sum", lab, every(lambda x, n=n, m=m: n * wave(x) * MILLIS[m])))
    return out


def histogram() -> list:
    """A classic histogram in seconds: cumulative ``_sum`` and ``_count`` by method."""
    out = []
    for (m, st), n in CALLS.items():
        lab = {"method": m, "status": st}
        out.append(("rpc_duration_seconds_count", lab, every(lambda x, n=n: n * x / 60)))
        out.append(("rpc_duration_seconds_sum", lab, every(lambda x, n=n, m=m: n * x / 60 * MILLIS[m] / 1000)))
    return out


def _spec(url: str, tmp_path: Path):
    specs = load({"sources": [{"name": "work", "url": url, "match": ['{__name__=~"[a-zA-Z_:].*"}']}]}, tmp_path)
    assert not specs.refused, specs.refused
    return specs.sources[0]


@pytest.fixture
def store():
    made = []

    def make(dump):
        made.append(FakePrometheus(dump))
        return made[-1]
    yield make
    for f in made:
        f.close()


def _defs(fake, tmp_path):
    spec = _spec(fake.url, tmp_path)
    sch = read(PrometheusSource(spec), spec, T0, NOW)
    return spec, [d for f in sch.families for d in views(f, spec)]


def test_rules_sum_and_count_by_method_give_the_calls_in_progress_with_the_completions_as_moves(store, tmp_path):
    fake = store(rules())
    spec, defs = _defs(fake, tmp_path)
    occ = {tuple(d.group_by): d for d in defs if d.view == "occupancy"}
    d = occ[("method",)]
    assert d.kind == "level" and d.unit == "calls" and d.name == "grpc_client_callmillis_in_progress"
    assert d.query.startswith("sum by (method) (last_over_time(grpc_client_callMillis:sum[") and d.query.endswith(" / 60000)")
    assert d.occupancy == {"law": "Little's law", "derived": LITTLE, "busy": "grpc_client_callMillis:sum", "scale": 1000.0,
                           "completions": "grpc_client_callmillis_count", "by": "status", "driver": "grpc_client_callmillis_count"}
    assert "derived: busy time over the interval (Little's law)" in d.origin[0]
    # its moves: the count rule by method and status, each sample the calls of its minute: a flow, never a level
    [moves] = [x for x in defs if x.name == d.occupancy["completions"] and set(x.group_by) == {"method", "status"}]
    assert (moves.view, moves.kind, moves.counter_form) == ("increments", "counter", "delta") and "a flow" in moves.origin[0]
    assert not any(x.name == moves.name and x.kind == "level" for x in defs)
    src = PrometheusSource(spec)
    got = {lab["method"]: dict(pts) for _, lab, pts, _ in read_definition(src, d, "work", None, T0 + 600, NOW, 60.0)}
    # Little's law: a minute of 126 calls of 50 ms each kept 0.105 calls in progress; 33 of 400 ms, 0.22 (each times the wave)
    assert got["Get"] and all(v == pytest.approx(126 * 0.050 * wave(t - T0) / 60) for t, v in got["Get"].items())
    assert all(v == pytest.approx(33 * 0.400 * wave(t - T0) / 60) for t, v in got["Put"].items())
    done = {(lab["method"], lab["status"]): pts for _, lab, pts, _ in read_definition(src, moves, "work", None, T0 + 600, NOW, 60.0)}
    pts = done[("Get", "passed")]
    # each step (two samples' worth) adds the calls its minutes completed: 120 a minute, times the wave
    for (t0, a), (t1, b) in pairwise(pts):
        assert b - a == pytest.approx(sum(120 * wave(t - T0) for t in range(int(t0) + 60, int(t1) + 1, 60)))
    p = provenance(spec, d)
    assert p["view"] == "occupancy" and p["derived"] == LITTLE and p["occupancy"]["completions"] == moves.name


def test_a_count_alone_offers_no_occupancy(store, tmp_path):
    _, defs = _defs(store(rules(count_only=True)), tmp_path)
    assert defs and not any(d.view == "occupancy" for d in defs)
    assert all(d.kind == "level" for d in defs if d.view == "rollup")      # a count rule with no sum beside it: as before


def test_seconds_are_not_divided_and_a_cumulative_sum_is_read_by_its_rate(store, tmp_path):
    fake = store(histogram())
    spec, defs = _defs(fake, tmp_path)
    d = next(d for d in defs if d.view == "occupancy" and d.group_by == ["method"])
    assert d.query.startswith("sum by (method) (rate(rpc_duration_seconds_sum[") and "/" not in d.query
    assert d.occupancy["scale"] == 1.0 and d.occupancy["completions"] == "rpc_duration_seconds_count" and d.occupancy["by"] == "status"
    assert any(x.view == "increments" and x.name == "rpc_duration_seconds_count" for x in defs)
    got = {lab["method"]: [v for _, v in pts] for _, lab, pts, _ in read_definition(PrometheusSource(spec), d, "work", None, T0 + 600, NOW, 60.0)}
    # rate() extrapolates to its window's edges as Prometheus' does: the level is off by that much, alike for each method
    assert got["Get"][-1] == pytest.approx(126 * 0.050 / 60, rel=0.25)
    assert got["Put"][-1] / got["Get"][-1] == pytest.approx((33 * 0.400) / (126 * 0.050))


def test_millis_and_seconds_name_their_scale():
    from orchestra.sources.views import scale
    assert scale("grpc_client_callMillis") == 1000.0 and scale("rpc_latency_ms") == 1000.0
    assert scale("rpc_duration_seconds") == 1.0 and scale("io_wait_microseconds") == 1e6


def test_a_summarys_count_per_interval_typed_a_gauge_is_a_flow(store, tmp_path):
    from orchestra.sources.family import Family, LabelInfo
    fam = Family("rpc_latency_ms_count", "gauge", {"rpc_latency_ms_count": None}, busy="rpc_latency_ms_sum", resolution_s=60.0,
                 labels={"method": LabelInfo("method", 2, 0.0, "grouping")})
    spec = _spec("http://127.0.0.1:9", tmp_path)
    defs = views(fam, spec)
    assert not any(d.kind == "level" and d.view in ("sum_by", "max_by", "avg_by") for d in defs)
    inc = [d for d in defs if d.view == "increments"]
    assert inc and all(d.counter_form == "delta" for d in inc)
    occ = next(d for d in defs if d.view == "occupancy" and d.group_by == ["method"])
    assert occ.query == "sum by (method) (last_over_time(rpc_latency_ms_sum[151s]) / 60000)"


def _kinds_spec(url: str, tmp_path: Path, kinds: dict):
    specs = load({"sources": [{"name": "work", "url": url, "match": ['{__name__=~"[a-zA-Z_:].*"}'], "kinds": kinds}]}, tmp_path)
    assert not specs.refused, specs.refused
    return specs.sources[0]


def test_kinds_flip_a_family_each_way_and_ignore_leaves_it_out_with_the_reason(store, tmp_path):
    lab = {"method": "Get"}
    fake = store(rules() + [("rpc_inflight", lab, every(lambda x: 3 + (x // 60) % 4)),
                            ("rpc_requests_total", lab, every(lambda x: x / 6)),
                            ("rpc_noise", lab, every(lambda x: (x // 60) % 5))])
    kinds = {"rpc_inflight": "flow", "rpc_requests_total": "level", "rpc_noise": "ignore", "grpc_client_callMillis:count": "level"}
    spec = _kinds_spec(fake.url, tmp_path, kinds)
    sch = read(PrometheusSource(spec), spec, T0, NOW)
    by = {f.name: f for f in sch.families}
    defs = [d for f in sch.families for d in views(f, spec)]
    of = lambda fam: [d for d in defs if d.family == fam and d.view != "distinct"]
    assert by["rpc_inflight"].kind == "counter" and {(d.view, d.kind) for d in of("rpc_inflight")} == {("increments", "counter")}
    assert all(d.declared_kind == "flow" and d.counter_form == "delta" for d in of("rpc_inflight"))
    assert {(d.view, d.kind) for d in of("rpc_requests_total")} == {("sum_by", "level")} and by["rpc_requests_total"].kind == "gauge"
    [ignored] = of("rpc_noise")
    assert ignored.left == "declared ignore in [[sources]] kinds: never read" and not [d for d in defs if d.family == "rpc_noise" and not d.left]
    count = [d for d in defs if d.name == "grpc_client_callmillis_count"]
    assert count and all(d.view == "rollup" and d.kind == "level" and d.declared_kind == "level" for d in count)
    assert provenance(spec, of("rpc_inflight")[0])["declared_kind"] == "flow"


def test_kinds_must_say_flow_level_or_ignore(tmp_path):
    specs = load({"sources": [{"name": "work", "url": "http://127.0.0.1:9", "match": ['{__name__=~"x.*"}'], "kinds": {"x": "stock"}}]}, tmp_path)
    assert "work" in specs.refused and "flow" in specs.refused["work"]


def test_the_instruments_page_says_derived_and_declared():
    html = (Path(__file__).parents[2] / "orchestra/web/static/instruments.html").read_text()
    assert "derived: ${esc(r.derived)}" in html and "kind: ${esc(r.declared_kind)} (declared)" in html
