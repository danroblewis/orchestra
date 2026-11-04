"""``split`` on a source: a family is split only by the labels the owner named and summed over every
other, by the store (``sum by (…)`` in the query); without it, inference chooses as before. And a
label named like an object (``container_name``) is an identity only when its values behave like one."""

from __future__ import annotations

import math
import time

import pytest
from fake_prometheus import FakePrometheus

from orchestra.sources.fetch import read_many
from orchestra.sources.infer import infer
from orchestra.sources.prometheus import PrometheusSource
from orchestra.sources.schema import read
from orchestra.sources.spec import load

NOW = math.floor(time.time() / 60) * 60
T0 = NOW - 3600
SERVICES, METHODS, STATUSES = ["checkout", "search"], ["GET", "POST", "PUT"], ["200", "500"]
LENS = [f"caller-{i}" for i in range(9)]          # the owner's edge_service: many values nobody wanted a series of


def every(fn, step=30):
    return [(float(t), float(fn(t - T0))) for t in range(int(T0), int(NOW) + 1, step)]


def dump():
    out = []
    for i, (s, m, st, lens) in enumerate((s, m, st, lens) for s in SERVICES for m in METHODS for st in STATUSES for lens in LENS):
        lab = {"service_name": s, "method": m, "status": st, "edge_service": lens}
        out.append(("rpc_inflight", lab, every(lambda x, i=i: (i % 7) + (x // 300) % 4)))
        out.append(("rpc_requests_total", lab, every(lambda x, i=i: (1 + i % 3) * x // 10)))
    return out


@pytest.fixture
def store(tmp_path):
    made = []

    def make(data, **kw):
        f = FakePrometheus(data)
        made.append(f)
        specs = load({"sources": [{"name": "lab", "url": f.url, "match": ['{__name__=~"rpc_.*"}'], "max_series": 400,
                                   "max_per_family": 40, **kw}]}, tmp_path)
        assert not specs.refused, specs.refused
        src = PrometheusSource(specs.sources[0])
        src._sleep = lambda s: None
        return f, src, specs.sources[0]
    yield make
    for f in made:
        f.close()


SPLIT = ["service_name", "method", "status"]


def test_a_split_source_reads_one_series_per_named_value_summed_by_the_store(store, tmp_path):
    fake, src, spec = store(dump(), split=SPLIT)
    inf = infer(src, spec, [], tmp_path, T0, NOW)
    by_family = {}
    for d in inf.kept:
        by_family.setdefault(d.family, []).append(d)
    assert set(by_family) == {"rpc_inflight", "rpc_requests_total"}
    for fam, defs in by_family.items():
        for d in defs:
            assert "edge_service" not in d.by_real and "edge_service" not in d.group_by, (fam, d.name, d.by_real)
            if d.view != "distinct":
                assert set(SPLIT) <= set(d.by_real) and d.summed == ["edge_service"], (d.name, d.by_real, d.summed)
    sums = [d for d in inf.kept if d.view in ("sum_by", "increments")]
    assert {d.family for d in sums} == {"rpc_inflight", "rpc_requests_total"}
    fake.queries.clear()
    got, errors = read_many(src, sums, spec.prefix, None, NOW - 1800, NOW, 60.0)
    assert not errors
    n = len(SERVICES) * len(METHODS) * len(STATUSES)
    assert all(len(got[d.id]) == n for d in sums), {d.name: len(got[d.id]) for d in sums}
    sent = " ".join(fake.queries)
    assert "sum by (service_name, method, status) (last_over_time(rpc_inflight" in sent
    assert "sum by (service_name, method, status) (increase(rpc_requests_total" in sent      # the store sums, never its raw samples


def test_without_split_inference_chooses_as_before(store, tmp_path):
    _, src, spec = store(dump())
    inf = infer(src, spec, [], tmp_path, T0, NOW)
    assert spec.split is None and all(not d.summed for d in inf.kept + inf.left_out)
    groupings = {tuple(sorted(d.group_by)) for d in inf.kept + inf.left_out if d.family == "rpc_inflight" and d.view == "sum_by"}
    assert () in groupings and any(len(g) == 1 for g in groupings)        # the total and single labels, as inference chooses


def test_split_is_refused_unless_a_list_of_label_names(tmp_path):
    for bad in ("service", ["service", "a-b"], [1]):
        specs = load({"sources": [{"name": "lab", "url": "http://x", "match": ['{a="b"}'], "split": bad}]}, tmp_path)
        assert "lab" in specs.refused and "split" in specs.refused["lab"]


def _container(values_at):
    """``container_name`` holding the values ``values_at(minute)`` gives, each reporting while named."""
    out = {}
    for t in range(int(T0), int(NOW) + 1, 30):
        for v in values_at((t - T0) // 60):
            out.setdefault(v, []).append((float(t), 1.0 + (t // 300) % 3))
    return [("rpc_inflight", {"container_name": v, "service_name": "x"}, pts) for v, pts in out.items()]


def test_a_container_name_holding_a_few_stable_services_is_a_grouping(store):
    _, src, spec = store(_container(lambda m: ["checkout", "search", "authz", "cart", "email"]))
    fam = next(f for f in read(src, spec, T0, NOW).families if f.name == "rpc_inflight")
    assert fam.labels["container_name"].role == "grouping", fam.labels["container_name"]


def test_a_churning_container_name_stays_an_identity(store):
    # a pod-like name: replaced every half hour, two reporting at a time, three in the hour: few values, but churning
    _, src, spec = store(_container(lambda m: [f"web-{min(m, 59) // 30}", f"web-{min(m, 59) // 30 + 1}"]))
    fam = next(f for f in read(src, spec, T0, NOW).families if f.name == "rpc_inflight")
    info = fam.labels["container_name"]
    assert info.role == "identity" and info.cardinality <= 3 and info.churn > 0.1, info
