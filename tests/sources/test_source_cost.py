"""What reading a big tenant costs it, against the fake (review r3, cost): a store too big to list
whole is refused before a series is listed, the cap holds while listing, an HA pair's name too big
across its replicas is read at one and a rule over the pair is read at one replica (never summed
across it), discovery reads only the new steps of its window, a read refused for its size is not
asked again every round, and the health and metadata checks touch no series."""

from __future__ import annotations

import math
import time

import pytest
from fake_prometheus import FakePrometheus
from helpers import project

from orchestra.sources.cache import attempt
from orchestra.sources.catalogue import Catalogue
from orchestra.sources.listing import TooManyNames, listing
from orchestra.sources.prometheus import PROBE_NAME, PrometheusSource
from orchestra.sources.spec import load

NOW = math.floor(time.time() / 60) * 60
T0 = NOW - 3600


def every(seconds, fn, start=T0 - 1800, end=NOW + 600):
    out, t = [], start
    while t <= end:
        out.append((t, float(fn(t - start))))
        t += seconds
    return out


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


def toml(url: str, extra: str = "") -> str:
    return f"""
[discovery]
window = "60m"
step = "60s"

[[sources]]
name = "lab"
url = "{url}"
{extra}
"""


def quick(fake, tmp_path, **kw) -> PrometheusSource:
    src = PrometheusSource(load({"sources": [{"name": "lab", "url": fake.url, **kw}]}, tmp_path).sources[0])
    src._sleep = lambda s: None
    return src


def test_a_store_with_more_names_than_a_listing_is_made_of_is_refused_before_a_series_is_listed(made, tmp_path, monkeypatch):
    f = made([(f"metric_{i:03d}", {}, every(60, lambda s: s)) for i in range(30)])
    p = project(tmp_path, monkeypatch, toml(f.url, "max_names = 10"))
    with pytest.raises(TooManyNames) as e:
        Catalogue(p, None).inference("lab", T0, NOW)
    said = str(e.value)
    assert "at least 11 metric names" in said and "match" in said and "raise" not in said and "budget" not in said
    assert f.requests == 1 and f.name_asks == [[]]           # one cheap request, and no match-everything filter in it
    assert attempt(p.state_dir, "lab")["stopped"]            # it would fail the same way every hour: not tried again
    with pytest.raises(Exception, match="none runs until"):
        Catalogue(p, None).inference("lab", T0, NOW)
    assert f.requests == 1


def test_the_cap_holds_while_listing_not_after(made, tmp_path):
    f = made([(f"m_{i:03d}", {"pod": f"p{j}"}, every(60, lambda s: s)) for i in range(100) for j in range(5)])
    src = quick(f, tmp_path, concurrency=1)
    out = listing(src, ['{__name__=~".+"}'], T0, NOW, concurrency=1, limit=200)
    asked = f.requests
    assert out.cut and sum(len(v) for v in out.names.values()) < 300 and "stopped at 200 series" in " ".join(out.notes)
    assert asked < 1 + 100 / 24                              # not every batch of names was asked for


def _pair(dump):
    """Every series of ``dump`` as two replicas of a Prometheus HA pair would write it."""
    return [(n, {**lab, "prometheus_replica": r}, pts) for n, lab, pts in dump for r in ("a", "b")]


def test_a_name_too_big_across_an_ha_pair_is_listed_and_read_at_one_replica(made, tmp_path, monkeypatch):
    orders = [("checkout_orders_total", {"pod": f"p{i}"}, every(15, lambda s, i=i: (i + 1) * s / 15)) for i in range(4)]
    depth = [("queue_depth", {"queue": q}, every(15, lambda s, q=q: 10 + (s // 60) % 7 + len(q))) for q in ("email", "orders")]
    f = made(_pair(orders + depth))
    f.max_series = 6                                          # 8 across the pair; 4 at one replica
    p = project(tmp_path, monkeypatch, toml(f.url))
    inf = Catalogue(p, None).inference("lab", T0, NOW, refresh=True)
    fam = next(x for x in inf.families if x["name"] == "checkout_orders_total")
    assert fam["where"] == {"prometheus_replica": "a"} and any("read at prometheus_replica=a" in n for n in fam["notes"])
    reads = [d for d in inf.kept if d.family == "checkout_orders_total" and d.view == "increments"]
    assert reads and all('prometheus_replica="a"' in d.query for d in reads)
    assert inf.remembered["pinned"] == {"checkout_orders_total": {"pin": {"prometheus_replica": "a"},
                                                                  "at": inf.remembered["pinned"]["checkout_orders_total"]["at"]}}
    before = f.requests
    again = Catalogue(p, None).inference("lab", T0, NOW, refresh=True)    # the next round lists it at its replica at once
    assert any(x["name"] == "checkout_orders_total" and x["where"] for x in again.families)
    assert f.requests - before <= inf.requests


def test_a_rule_over_an_ha_pair_is_read_at_one_replica_not_summed_across_it(made, tmp_path, monkeypatch):
    rule = [("job:checkout_orders:rate5m", {"job": "checkout"}, every(60, lambda s: 19.0 + (s // 600) % 3))]
    f = made(_pair(rule) + [("queue_depth", {"queue": "email"}, every(15, lambda s: 10 + (s // 60) % 7))])
    p = project(tmp_path, monkeypatch, toml(f.url))
    inf = Catalogue(p, None).inference("lab", T0, NOW, refresh=True)
    fam = next(x for x in inf.families if x["name"] == "job:checkout_orders:rate5m")
    assert fam["where"] == {"prometheus_replica": "a"}
    kept = [d for d in inf.kept if d.family == "job:checkout_orders:rate5m"]
    assert kept and all('job:checkout_orders:rate5m{prometheus_replica="a"}' in d.query for d in kept)
    assert not any("prometheus_replica" in d.group_by for d in kept)
    r = Catalogue(p, None).read(T0, NOW, 60.0)
    total = next(pts for n, lab, pts in r.dump if n.startswith("lab:") and "rate5m" in n and not lab.get("job_value"))
    assert total[-1][1] - total[0][1] < 22 * 3600              # a rate, integrated: one replica's 19–21 a second, never the pair's 38–42


def test_a_rule_without_the_replica_label_gives_way_to_its_base_read_at_one_replica(made, tmp_path, monkeypatch):
    base = [("queue_messages", {"queue": q}, every(15, lambda s, q=q: 10 + (s // 60) % 7 + len(q))) for q in ("email", "orders")]
    f = made(_pair(base) + [("queue_messages:sum", {}, every(60, lambda s: 2 * (32 + (s // 60) % 7 * 2)))])   # summed over the pair
    p = project(tmp_path, monkeypatch, toml(f.url))
    inf = Catalogue(p, None).inference("lab", T0, NOW, refresh=True)
    fam = next(x for x in inf.families if x["name"] == "queue_messages")
    assert fam["where"] == {"prometheus_replica": "a"}
    left = [d for d in inf.left_out if "queue_messages:sum" in d.query]
    assert left and all("summed across prometheus_replica" in d.why for d in left)
    sums = [d for d in inf.kept if d.family == "queue_messages" and d.view == "sum_by"]
    assert sums and all('prometheus_replica="a"' in d.query for d in sums)


def test_discovery_reads_only_the_new_steps_and_gets_what_a_whole_read_gets(made, tmp_path, monkeypatch):
    dump = [("jobs_done_total", {"queue": q}, every(15, lambda s, q=q: (2 + len(q)) * s / 15)) for q in ("email", "orders")]
    dump += [("queue_depth", {"queue": q}, every(15, lambda s, q=q: 10 + (s // 60) % 7 + len(q))) for q in ("email", "orders")]
    f = made(dump)
    p = project(tmp_path, monkeypatch, toml(f.url))
    Catalogue(p, None).inference("lab", T0 - 300, NOW - 300)
    first = Catalogue(p, None).read(T0 - 300, NOW - 300, 60.0)
    assert first.status["lab"]["ok"]
    f.ranges.clear()
    slid = Catalogue(p, None).read(T0, NOW, 60.0)                          # five minutes later
    tail = [b - a for a, b in f.ranges]
    whole = Catalogue(p, None, incremental=False).read(T0, NOW, 60.0)
    assert slid.status["lab"]["ok"] and slid.status["lab"]["requests"] <= first.status["lab"]["requests"]
    assert sorted(slid.dump, key=str) == sorted(whole.dump, key=str)       # the same series, the same points
    assert tail and max(tail) < 900                                      # the new five minutes and a little before, not the hour


def test_a_read_refused_for_its_size_is_not_asked_again_every_round(made, tmp_path, monkeypatch):
    wide = [("http_requests_total", {"pod": f"p{i}"}, every(15, lambda s, i=i: (i + 1) * s / 15)) for i in range(6)]
    f = made(wide + [("queue_depth", {"queue": "email"}, every(15, lambda s: 10 + (s // 60) % 7))])
    p = project(tmp_path, monkeypatch, toml(f.url, 'series_per_query = 1\n[[series]]\nsource = "lab"\nname = "everything"\n'
                                                   'query = "sum by (pod) (rate(http_requests_total[2m]))"\nkind = "rate"'))
    Catalogue(p, None).inference("lab", T0, NOW)
    f.max_series = 4                                         # the declared read touches six: over the limit
    one = Catalogue(p, None).read(T0, NOW, 60.0)
    refusals = f.refusals
    two = Catalogue(p, None).read(T0 + 60, NOW + 60, 60.0)
    assert any("everything" in x for x in one.status["lab"]["failed"])
    assert any("not asked again" in x for x in two.status["lab"]["failed"])
    assert f.refusals == refusals                            # the second round did not pay for it again


def test_health_and_metadata_touch_no_series(made, tmp_path):
    f = made([("up", {"instance": f"i{i}"}, every(15, lambda s: 1)) for i in range(20)])
    f.meta = {"up": [{"type": "gauge", "help": "", "unit": ""}], "queue_depth": [{"type": "gauge", "help": "", "unit": ""}]}
    src = quick(f, tmp_path)
    h = src.health()
    assert h.ok and not any(q == "up" for q in f.queries) and all(q == PROBE_NAME for q in f.queries)
    assert src.metadata(["queue_depth"]) == {"queue_depth": {"type": "gauge", "help": "", "unit": ""}}
    assert {"metric": "queue_depth", "limit_per_metric": "1"} in f.meta_asks
    many = src.metadata([f"m{i}" for i in range(50)] + ["up"])
    assert set(many) == {"up"} and {"limit_per_metric": "1"} in f.meta_asks


def test_a_family_too_big_to_compare_its_replicas_is_read_at_one_never_summed_across_them(made, tmp_path, monkeypatch):
    from orchestra.sources import survey
    monkeypatch.setattr(survey, "DUPLICATE_SERIES", 4)       # as a 6,490-series family is to the default 5,000
    reqs = [("http_requests_total", {"pod": f"p{i}"}, every(15, lambda s, i=i: (i + 1) * s / 15)) for i in range(4)]
    f = made(_pair(reqs))
    p = project(tmp_path, monkeypatch, toml(f.url))
    inf = Catalogue(p, None).inference("lab", T0, NOW, refresh=True)
    fam = next(x for x in inf.families if x["name"] == "http_requests_total")
    assert fam["where"] == {"prometheus_replica": "a"} and any("names a replica of an HA pair" in n for n in fam["notes"])
    reads = [d for d in inf.kept if d.family == "http_requests_total" and d.view == "increments"]
    assert reads and all('prometheus_replica="a"' in d.query and "prometheus_replica" not in d.group_by for d in reads)
