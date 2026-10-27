"""How a view's results are put on discovery's grid: a count reads 0 where a group has no
reporters, and stays empty where the store had nothing at all."""

from __future__ import annotations

from fake_prometheus import FakePrometheus

from orchestra.sources.fetch import read
from orchestra.sources.prometheus import PrometheusSource
from orchestra.sources.spec import load
from orchestra.sources.views import Definition

T0 = 1_800_000_000.0


def _pods(region: str, n: int, gone: range, nothing: range) -> list:
    """``n`` pods of ``region`` reporting every minute for two hours, except the minutes in
    ``gone`` (that region is down) and ``nothing`` (the store holds nothing at all)."""
    return [("lat", {"region": region, "pod": f"{region}-{k}"},
             [(T0 + 60 * m, 0.1) for m in range(120) if m not in gone and m not in nothing]) for k in range(n)]


def test_a_group_that_vanishes_reads_zero_and_a_stretch_with_nothing_stays_a_gap(tmp_path):
    down, empty = range(40, 60), range(90, 100)
    fake = FakePrometheus(_pods("a", 2, range(0), empty) + _pods("b", 3, down, empty))
    try:
        spec = load({"sources": [{"name": "rig", "url": fake.url}]}, tmp_path).sources[0]
        d = Definition(id="c0", source="rig", name="lat_pods", family="lat", view="count", kind="level",
                       query="count by (region) (last_over_time(lat[61s]))", group_by=["region"], by_real=["region"],
                       resolution_s=60.0)
        got = {labels["region"]: dict(pts) for _, labels, pts, _ in read(PrometheusSource(spec), d, "rig", None, T0, T0 + 119 * 60, 60.0)}
    finally:
        fake.close()
    b = got["b"]
    assert [b[T0 + 60 * m] for m in range(41, 60)] == [0.0] * 19        # minute 40 still counts the pods of minute 39
    assert b[T0 + 30 * 60] == 3.0 and got["a"][T0 + 50 * 60] == 2.0
    assert not any(T0 + 60 * m in b or T0 + 60 * m in got["a"] for m in range(91, 100))
