"""What the metrics lab's cleanup round found in reading a store (reports/05-identification.md):

- a family whose series churn (pods replaced every few minutes) lists many series that have no
  samples in the window: its type is still judged, on the series that report now;
- a type recorded by a round that read no samples judged nothing, so it never holds a new verdict."""

from __future__ import annotations

import math
import time

import pytest
from fake_prometheus import FakePrometheus

from orchestra.sources.prometheus import PrometheusSource
from orchestra.sources.schema import read
from orchestra.sources.spec import load

NOW = math.floor(time.time() / 60) * 60
T0 = NOW - 3600


def every(seconds, fn, start=T0, end=NOW):
    out, t = [], start
    while t <= end:
        out.append((t, float(fn(t - start))))
        t += seconds
    return out


class ByDay(FakePrometheus):
    """A store whose listing is by day (as VictoriaMetrics' index): every series of the day is
    named, whether or not it has samples in the range asked."""

    def answer(self, endpoint, form):
        if endpoint in ("series", "label_values"):
            form = {**form, "start": [str(NOW - 86400)]}
        return super().answer(endpoint, form)


@pytest.fixture
def store(tmp_path):
    made = []

    def make(dump, cls=FakePrometheus, **kw):
        f = cls(dump)
        f.meta = {}
        made.append(f)
        specs = load({"sources": [{"name": "lab", "url": f.url, **kw}]}, tmp_path)
        src = PrometheusSource(specs.sources[0])
        src._sleep = lambda s: None
        src.limiter.hold = lambda s: None
        return f, src, specs
    yield make
    for f in made:
        f.close()


def _pods():
    """A hundred pods of the morning, replaced long ago, and three that report now, listed between
    them where no pick of the listing falls: each counts the messages it processed since it started."""
    gone = [("worker_processed_messages", {"pod": f"w-old-{i:02d}"}, every(15, lambda s, i=i: 10 * i + s / 10, start=T0 - 7200 - 30 * i,
                                                                             end=T0 - 3600)) for i in range(100)]
    live = [("worker_processed_messages", {"pod": f"w-old-00{'abc'[i]}"}, every(15, lambda s, i=i: 100 * i + s / 5)) for i in range(3)]
    return gone + live


def test_a_churning_familys_type_is_judged_on_the_series_reporting_now(store):
    _, src, specs = store(_pods(), cls=ByDay, history="1h")
    got = {fam.name: fam for fam in read(src, specs.sources[0], T0, NOW).families}["worker_processed_messages"]
    assert got.kind == "counter" and got.resolution_s == 15.0, (got.kind, got.resolution_s, got.retyped)


def test_a_type_recorded_without_samples_does_not_hold(store):
    _, src, specs = store(_pods(), cls=ByDay, history="1h")
    known = {"worker_processed_messages": {"kind": "gauge", "resolution_s": None, "labels": {}}}
    got = {fam.name: fam for fam in read(src, specs.sources[0], T0, NOW, known=known).families}["worker_processed_messages"]
    assert got.kind == "counter"
