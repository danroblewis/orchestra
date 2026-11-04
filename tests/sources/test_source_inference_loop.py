"""Inference as a loop (SPEC §4.4, "The inference loop"): the store's own labels rank every
family's groupings (``storewide.py``)."""

from __future__ import annotations

import math
import time

import pytest
from fake_prometheus import FakePrometheus

from orchestra.sources.infer import infer
from orchestra.sources.prometheus import PrometheusSource
from orchestra.sources.spec import load

NOW = math.floor(time.time() / 60) * 60
T0 = NOW - 3600
SVC = [f"svc-{i}" for i in range(5)]
LENS = [f"caller-{i}" for i in range(40)]


def every(fn, step=30):
    return [(float(t), float(fn(t - T0))) for t in range(int(T0), int(NOW) + 1, step)]


def common_store():
    """Six families carrying ``svc`` (five stable values); one of them also ``lens`` (forty)."""
    out = []
    for f in range(6):
        for k, s in enumerate(SVC):
            if f == 0:
                for j, lens in enumerate(LENS):
                    out.append(("fam0_jobs", {"svc": s, "lens": lens}, every(lambda x, k=k, j=j: (k + j) % 5 + (x // 300) % (2 + k))))
            elif f % 2:
                out.append((f"fam{f}_requests_total", {"svc": s}, every(lambda x, k=k, f=f: (1 + k) * f * x // 10)))
            else:
                out.append((f"fam{f}_items", {"svc": s}, every(lambda x, k=k: (x // (120 * (k + 1))) % 7)))
    return out


@pytest.fixture
def store(tmp_path):
    made = []

    def make(data, **kw):
        f = FakePrometheus(data)
        made.append(f)
        specs = load({"sources": [{"name": "lab", "url": f.url, "match": ['{__name__=~"fam.*"}'], "max_series": 2000,
                                   "max_per_family": 40, **kw}]}, tmp_path)
        assert not specs.refused, specs.refused
        src = PrometheusSource(specs.sources[0])
        src._sleep = lambda s: None
        return f, src, specs.sources[0]
    yield make
    for f in made:
        f.close()


def test_the_stores_common_grouping_ranks_above_one_familys_oddity(store, tmp_path):
    _, src, spec = store(common_store())
    inf = infer(src, spec, [], tmp_path, T0, NOW)
    svc, lens = inf.labels["svc"], inf.labels["lens"]
    assert svc["why"] == "groups 6 of 6 families, 5 stable values" and svc["rank"] == 1.0
    assert lens["groups"] == 1 and lens["values"] == 40 and lens["rank"] < 0.05
    every_def = inf.kept + inf.left_out
    for fam in {d.family for d in every_def}:
        by = lambda label, fam=fam: [d for d in every_def if d.family == fam and d.view not in ("distinct",)
                                     and [c for c in d.group_by if d.labels_info.get(c, {}).get("role") == "grouping"] == [label]]
        assert by("svc"), fam
        assert all("common 1.00 [svc: groups 6 of 6 families" in d.why for d in by("svc") if d.why.startswith("moves"))
        if fam == "fam0_jobs":
            assert by("lens")
            assert min(d.score for d in by("svc")) > max(d.score for d in by("lens")), [(d.name, d.score, d.why) for d in by("svc") + by("lens")]

