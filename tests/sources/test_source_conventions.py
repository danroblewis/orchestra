"""Most metrics need no ``kinds``: names and the store's metadata say what they are
(``conventions.py``); ``kinds`` keys may be globs, an exact name over a pattern and a longer
pattern over a shorter (``kinds.py``); and an edited ``kinds`` re-runs inference at the next round,
which says why (``cache.py``). Against the fake."""

from __future__ import annotations

import math
import time
from pathlib import Path

import pytest
from fake_prometheus import FakePrometheus

from orchestra.sources.cache import definitions
from orchestra.sources.catalogue import provenance
from orchestra.sources.conventions import convention
from orchestra.sources.kinds import entry
from orchestra.sources.prometheus import PrometheusSource
from orchestra.sources.schema import read
from orchestra.sources.spec import load
from orchestra.sources.views import views

NOW = math.floor(time.time() / 60) * 60
T0 = NOW - 3600
SUB = {"subscription_id": "orders"}
P = "gcp_pubsub_subscription_"


def every(fn, step=60):
    return [(float(t), float(fn(t - T0))) for t in range(int(T0), int(NOW) + 1, step)]


def wave(x: float) -> float:
    return 100 + 40 * ((x // 60) % 3) - 25 * ((x // 60) % 2)


def pubsub() -> list:
    """Pub/Sub as Google Cloud Monitoring exports it: DELTA counts per minute, pushed as gauges, and GAUGE levels."""
    return [(P + "ack_message_count", SUB, every(wave)),
            (P + "pull_request_count", SUB, every(lambda x: wave(x) / 10)),
            (P + "num_undelivered_messages", SUB, every(lambda x: 500 + 3 * ((x // 60) % 7))),
            (P + "oldest_unacked_message_age", SUB, every(lambda x: 30 + x)),       # stuck: rises by one a second, no clock
            (P + "backlog_bytes", SUB, every(lambda x: 9000 + 50 * ((x // 60) % 5)))]


def _spec(url: str, tmp_path: Path, **kw):
    specs = load({"sources": [{"name": "work", "url": url, "match": ['{__name__=~"[a-zA-Z_:].*"}'], **kw}]}, tmp_path)
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


def _read(fake, spec):
    sch = read(PrometheusSource(spec), spec, T0, NOW)
    return {f.name: f for f in sch.families}, [d for f in sch.families for d in views(f, spec)]


def test_pubsub_names_are_classified_with_no_kinds(store, tmp_path):
    fake = store(pubsub())
    fams, defs = _read(fake, _spec(fake.url, tmp_path))
    for n in ("ack_message_count", "pull_request_count"):
        f = fams[P + n]
        assert (f.kind, f.counter_form) == ("counter", "delta") and "by convention" in f.retyped
        assert {d.view for d in defs if d.family == P + n and d.view != "distinct"} == {"increments"}
    for n in ("num_undelivered_messages", "oldest_unacked_message_age", "backlog_bytes"):
        f = fams[P + n]
        assert f.kind == "gauge", (n, f.kind, f.retyped)          # the age is no clock: a level
        assert any(d.view == "sum_by" and d.kind == "level" for d in defs if d.family == P + n)


def test_a_gauge_whose_help_says_per_interval_is_a_flow(store, tmp_path):
    fake = store([("checkout_widgets", {"shop": "a"}, every(wave))])
    fake.meta = {"checkout_widgets": [{"type": "gauge", "help": "Number of widgets sold in the sampling period.", "unit": ""}]}
    fams, defs = _read(fake, _spec(fake.url, tmp_path))
    f = fams["checkout_widgets"]
    assert (f.kind, f.counter_form) == ("counter", "delta") and "help says per interval" in f.retyped
    assert all(d.kind == "counter" for d in defs if d.family == "checkout_widgets" and d.view != "distinct")


def test_the_conventions_table():
    rising = [[(float(t), float(t)) for t in range(0, 1200, 60)]]
    falls = [[(float(t), float(wave(t))) for t in range(0, 1200, 60)]]
    assert convention("x_count", None, None, falls)[:2] == ("counter", "delta")
    assert convention("x_total", "gauge", None, rising)[:2] == ("counter", "")          # cumulative: never fell
    assert convention("x_count", "counter", None, falls) is None                        # the store's own type settles it
    assert convention("kube_pod_count", "gauge", None, falls) is None                   # things held, not events
    assert convention("queue_pending_total", None, None, falls) is None
    assert convention("x_gauge", "gauge", "delta of x", falls)[:2] == ("counter", "delta")
    assert convention("foo_num_ready", "gauge", None, falls)[0] == "gauge"
    assert convention("cpu_temperature", "gauge", None, falls) is None                  # silent: behaviour decides


def test_patterns_and_precedence():
    table = {"gcp_pubsub_*": "level", "gcp_pubsub_*_count": "flow", "*:count": "flow", "gcp_pubsub_x_count": "ignore"}
    assert entry(["gcp_pubsub_x_count"], table) == "gcp_pubsub_x_count"                  # exact over any pattern
    assert entry(["gcp_pubsub_y_count"], table) == "gcp_pubsub_*_count"                  # longer over shorter
    assert entry(["gcp_pubsub_y_bytes"], table) == "gcp_pubsub_*"
    assert entry(["grpc_client_callMillis:count"], table) == "*:count"
    assert entry(["other"], table) is None


def test_kinds_patterns_decide_and_say_which_entry(store, tmp_path):
    fake = store(pubsub())
    spec = _spec(fake.url, tmp_path, kinds={"gcp_pubsub_*": "level", "gcp_pubsub_*_count": "flow", P + "backlog_bytes": "ignore"})
    fams, defs = _read(fake, spec)
    assert (fams[P + "ack_message_count"].declared_kind, fams[P + "ack_message_count"].declared_by) == ("flow", "gcp_pubsub_*_count")
    assert fams[P + "num_undelivered_messages"].declared_by == "gcp_pubsub_*"
    assert fams[P + "backlog_bytes"].kind == "ignored" and fams[P + "backlog_bytes"].declared_by == P + "backlog_bytes"
    d = next(d for d in defs if d.family == P + "ack_message_count" and d.view == "increments")
    assert provenance(spec, d)["declared_by"] == "gcp_pubsub_*_count"


def test_an_edited_kinds_is_read_at_the_next_round_and_the_round_says_why(store, tmp_path):
    fake = store([("rpc_inflight", {"m": "Get"}, every(lambda x: 3 + (x // 60) % 4))])
    kinds_of = lambda inf: {(d.view, d.kind) for d in inf.kept if d.family == "rpc_inflight" and d.view != "distinct"}
    first = _spec(fake.url, tmp_path)
    a = definitions(PrometheusSource(first), first, [], tmp_path, tmp_path / "state", T0, NOW)
    assert kinds_of(a) == {("sum_by", "level")} and not a.reason
    edited = _spec(fake.url, tmp_path, kinds={"rpc_*": "flow"})
    b = definitions(PrometheusSource(edited), edited, [], tmp_path, tmp_path / "state", T0, NOW)   # no refresh, no wipe
    assert kinds_of(b) == {("increments", "counter")}
    assert b.reason == "re-inferred: the source's kinds changed" and b.notes[0] == b.reason and b.round["reason"] == b.reason
    again = definitions(PrometheusSource(edited), edited, [], tmp_path, tmp_path / "state", T0, NOW)
    assert again.at == b.at                                                              # cached again under the new settings
