"""A definition's motion is judged over the window the inference serves (the kube demo, 2026-11-03:
a cached inference judged over one quiet hour left out every pod series, and a week's discovery saw
no pods). Against the conformance fake: a family flat in the last hour but moved earlier in the
held history is kept; one flat throughout is left out saying so; a cached judgement of an hour is
never reused for a week; and the survey stays within the round's request cap."""

from __future__ import annotations

import math
import time

import pytest
from fake_prometheus import FakePrometheus

from orchestra.sources.cache import cached, definitions
from orchestra.sources.prometheus import PrometheusSource
from orchestra.sources.spec import load

NOW = math.floor(time.time() / 60) * 60
DAYS = 2
T0 = NOW - DAYS * 86400
HOUR = NOW - 3600


def every(seconds, fn):
    return [(float(t), float(fn(t))) for t in range(int(T0), int(NOW) + 1, seconds)]


def dump():
    # replicas that scaled up and back down a day ago, then held still through the last hour
    replicas = [("deploy_replicas", {"deployment": d}, every(60, lambda t, n=n: n + (2 if NOW - 30 * 3600 < t < NOW - 20 * 3600 else 0)))
                for n, d in enumerate(("api", "worker"), 1)]
    flat = [("node_capacity", {"node": n}, every(60, lambda t: 8.0)) for n in ("n1", "n2")]
    queue = [("queue_depth", {"queue": q}, every(60, lambda t, k=k: (k * t / 60) % 40)) for k, q in enumerate("ab", 1)]
    return replicas + flat + queue


@pytest.fixture
def fake():
    f = FakePrometheus(dump())
    yield f
    f.close()


def spec_for(fake, tmp_path, **kw):
    specs = load({"sources": [{"name": "lab", "url": fake.url, "infer_every": "1h", **kw}]}, tmp_path)
    assert not specs.refused, specs.refused
    return specs.sources[0]


def families(defs):
    return {d.family for d in defs}


def test_a_family_still_in_the_hour_that_moved_earlier_in_the_history_is_kept(fake, tmp_path):
    spec = spec_for(fake, tmp_path)
    hour = definitions(PrometheusSource(spec), spec, [], tmp_path, tmp_path / "a", HOUR, NOW)
    assert "deploy_replicas" not in families(hour.kept)                          # judged over the hour alone: still
    inf = definitions(PrometheusSource(spec), spec, [], tmp_path, tmp_path / "b", HOUR, NOW, judge_from=T0)
    assert "deploy_replicas" in families(inf.kept) and "queue_depth" in families(inf.kept)
    assert inf.judged == [T0, NOW] and inf.window == [HOUR, NOW]


def test_a_family_flat_over_the_whole_history_is_left_out_saying_so(fake, tmp_path):
    spec = spec_for(fake, tmp_path)
    inf = definitions(PrometheusSource(spec), spec, [], tmp_path, tmp_path / "s", HOUR, NOW, judge_from=T0)
    flat = [d for d in inf.left_out if d.family == "node_capacity"]
    assert flat and "node_capacity" not in families(inf.kept)
    assert all(f"did not move in the {DAYS}-day history" in d.why for d in flat if "move" in d.why)
    assert any("move" in d.why for d in flat)


def test_a_cached_judgement_of_an_hour_is_not_reused_for_a_wider_window(fake, tmp_path):
    spec = spec_for(fake, tmp_path)
    src = PrometheusSource(spec)
    hour = definitions(src, spec, [], tmp_path, tmp_path / "s", HOUR, NOW)
    n = fake.requests
    assert definitions(src, spec, [], tmp_path, tmp_path / "s", HOUR, NOW).at == hour.at and fake.requests == n   # the same window: reused
    wide = definitions(src, spec, [], tmp_path, tmp_path / "s", HOUR, NOW, judge_from=T0)
    assert fake.requests > n and wide.at > hour.at and "deploy_replicas" in families(wide.kept)
    assert cached(tmp_path / "s", "lab").judged == [T0, NOW]
    n = fake.requests
    again = definitions(src, spec, [], tmp_path, tmp_path / "s", HOUR, NOW)     # an hour within the judged history: reused
    assert fake.requests == n and again.at == wide.at


def test_the_survey_of_the_history_stays_within_the_caps(fake, tmp_path):
    spec = spec_for(fake, tmp_path, infer_requests=60)
    n = fake.requests
    hour = definitions(PrometheusSource(spec), spec, [], tmp_path, tmp_path / "a", HOUR, NOW)
    alone = fake.requests - n
    n = fake.requests
    wide = definitions(PrometheusSource(spec), spec, [], tmp_path, tmp_path / "b", HOUR, NOW, judge_from=T0)
    surveyed = fake.requests - n
    assert surveyed == wide.requests <= spec.infer_requests and hour.requests == alone
    assert surveyed - alone <= 3                       # at most one read a family the hour left still
    assert not wide.partial
