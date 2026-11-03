"""A faux Kubernetes namespace (kube-state-metrics' one-hot pod phases, a queue and its counters,
scraped every 15 s), against the fake answering as Prometheus does (``increase`` extrapolated):
the pods in each phase are summed, never counted as reporters; a counter read from its raw samples
balances the level it feeds at every step (UC-K, report findings 1 and 4)."""

from __future__ import annotations

import math
import time
from itertools import pairwise

import pytest
from fake_prometheus import FakePrometheus
from helpers import project
from kube_world import kube

from orchestra.metrics import for_project
from orchestra.sd.rediscover import rediscover
from orchestra.sources import fetch
from orchestra.sources.infer import infer
from orchestra.sources.prometheus import PrometheusSource
from orchestra.sources.spec import load

END = math.floor(time.time() / 60) * 60
MINUTES = 150
LABELS = {"service": ["service", "deployment"]}


@pytest.fixture(scope="module")
def shop():
    dump, truth = kube(END, MINUTES)
    fake = FakePrometheus(dump)
    fake.extrapolate = True
    yield fake, truth
    fake.close()


def spec_for(url: str, tmp_path):
    specs = load({"sources": [{"name": "kube", "url": url, "prefix": "kube", "machine": "service", "labels": LABELS,
                               "match": ['{namespace="shop"}']}]}, tmp_path)
    assert not specs.refused, specs.refused
    return specs.sources[0]


def test_a_one_hot_phase_gauge_is_summed_per_phase_never_counted_as_reporters(shop, tmp_path):
    fake, truth = shop
    spec = spec_for(fake.url, tmp_path)
    inf = infer(PrometheusSource(spec), spec, [], tmp_path, END - 7200, END)
    fam = next(f for f in inf.families if f["name"] == "kube_pod_status_phase")
    assert fam["indicator"] and fam["states"] == ["phase"]
    assert any("every sample 0 or 1" in n for n in fam["notes"])
    phase = [d for d in inf.kept + inf.left_out if d.family == "kube_pod_status_phase"]
    by_phase = [d for d in phase if "phase" in d.group_by]
    # no count of reporters split by phase (every pod reports every phase), nor by anything else
    assert not [d for d in phase if d.view == "count" and d.agg == "count"]
    held = [d for d in by_phase if d.view == "count"]
    assert held and all(d.agg == "sum" and d.query.startswith("sum by (") for d in held)
    assert all("every sample 0 or 1" in d.origin[0] for d in held)
    assert {d.view for d in by_phase if d.agg == "held"} == {"starts", "stops"}
    # its other views say nothing new: the pods per service are a sum too
    assert all(d.view not in ("count", "starts", "stops") or "phase" in d.group_by for d in phase)
    # read: the pods in each phase, as the truth has them at every step, balanced by those that entered and left it
    one = lambda view: next(d for d in by_phase if d.view == view and d.group_by == ["phase"])
    start, end = END - 7200, END - 60
    got, errors = fetch.read_many(PrometheusSource(spec), [one("count"), one("starts"), one("stops")], "kube", None, start, end, 30.0)
    assert not errors, errors
    rows = {view: {r[1]["phase"]: dict(r[2]) for r in got[one(view).id]} for view in ("count", "starts", "stops")}
    scrapes = sorted(truth)
    for ph in ("Pending", "Running", "Succeeded", "Failed"):
        level, came, went = rows["count"][ph], rows["starts"][ph], rows["stops"][ph]
        at = lambda pts, t: max((v for u, v in pts.items() if u <= t), default=0.0)
        for t in sorted(level):
            if t >= start:
                near = [truth[s][ph] for s in scrapes if t - 46 < s <= t]   # a pod gone still reads for one lookback (46 s)
                assert min(near) <= level[t] <= max(near), (ph, t)
                assert level[t] - level[min(level)] == at(came, t) - at(went, t), (ph, t)
    assert max(rows["count"]["Running"].values()) < 12 and max(rows["count"]["Pending"].values()) >= 1
    # a gauge whose values are not an indicator is still counted by its reporters
    inflight = [d for d in inf.kept + inf.left_out if d.family == "http_requests_in_flight" and d.view == "count"]
    assert inflight and all(d.agg == "count" for d in inflight)


def test_the_pods_in_each_phase_are_stocks_their_entries_and_exits_balance(shop, tmp_path, monkeypatch):
    fake, truth = shop
    p = project(tmp_path, monkeypatch, f"""
[discovery]
window = "120m"
step = "30s"

[[sources]]
name = "kube"
url = "{fake.url}"
prefix = "kube"
machine = "service"
match = ['{{namespace="shop"}}']

[sources.labels]
service = ["service", "deployment"]
""")
    m = rediscover(p, for_project(p), now=END).model
    phases = {s.series.labels["phase"]: s for s in m.stocks if s.series and s.series.name == "kube:kube_pod_status_phase"
              and set(s.series.labels) == {"phase"}}
    assert {"Pending", "Running"} <= set(phases)
    for s in phases.values():
        assert s.series.query.startswith("sum by (") and s.evidence.get("by_construction")
    # Unknown, which no pod was ever in, is no stock; and no count of the pods reporting a phase is one
    assert "Unknown" not in phases and not any(t["Unknown"] for t in truth.values())
    assert not [s for s in m.stocks if s.series and "phase" in s.series.labels and "count by" in (s.series.query or "")]
    assert all(f.counter.name.endswith(("_entered_total", "_left_total")) for f in m.flows
               if f.counter and "phase" in f.counter.labels and {f.src, f.dst} & {s.id for s in phases.values()})


def test_a_counter_read_from_raw_samples_balances_its_level_at_every_step(shop, tmp_path, monkeypatch):
    fake, _ = shop
    spec = spec_for(fake.url, tmp_path)
    inf = infer(PrometheusSource(spec), spec, [], tmp_path, END - 7200, END)
    pick = lambda fam, view: next(d for d in inf.kept if d.family == fam and d.view == view and not d.group_by)
    defs = [pick("queue_depth", "sum_by"), pick("queue_enqueued_total", "increments"), pick("queue_dequeued_total", "increments")]
    start, end, step = END - 7200, END - 60, 30.0

    def gaps() -> list[float]:
        got, errors = fetch.read_many(PrometheusSource(spec), defs, "kube", None, start, end, step)
        assert not errors, errors
        (_, _, depth, _), (_, _, enq, _), (_, _, deq, _) = (got[d.id][0] for d in defs)
        lv, e, q = dict(depth), dict(enq), dict(deq)
        ts = sorted(set(lv) & set(e) & set(q))
        assert len(ts) > 200
        return [(lv[b] - lv[a]) - ((e[b] - e[a]) - (q[b] - q[a])) for a, b in pairwise(ts)]
    assert all(abs(g) < 1e-6 for g in gaps())               # exact, step by step, across the exporter's restart
    monkeypatch.setattr(fetch, "RAW_SAMPLES", 0)             # a store that cannot give raw samples: increase(), extrapolated
    assert sum(abs(g) > 1e-6 for g in gaps()) > 50
