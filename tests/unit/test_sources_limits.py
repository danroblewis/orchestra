"""How hard a remote store is leaned on (sources/limits.py), and one read at the finest grouping
serving every coarser one exactly (sources/regroup.py): pure, with a fake clock."""

from __future__ import annotations

import time

import pytest

from orchestra.sources import PastDeadline
from orchestra.sources.limits import Budget, OverBudget, RateLimit
from orchestra.sources.regroup import derive, distinct, regroup


class Clock:
    def __init__(self):
        self.t = 1000.0
        self.slept: list[float] = []

    def __call__(self) -> float:
        return self.t

    def sleep(self, s: float) -> None:
        self.slept.append(s)
        self.t += s


def test_the_bucket_lets_a_burst_through_then_paces_at_its_rate():
    c = Clock()
    rl = RateLimit(5, 10, sleep=c.sleep, clock=c)
    for _ in range(10):
        rl.take()
    assert c.slept == []
    for _ in range(5):
        rl.take()
    assert sum(c.slept) == pytest.approx(1.0)          # five more at 5 a second


def test_a_429s_wait_holds_every_reader_of_the_source():
    c = Clock()
    rl = RateLimit(100, 100, sleep=c.sleep, clock=c)
    rl.hold(7.0)
    rl.take()
    assert sum(c.slept) == pytest.approx(7.0)


def test_a_wait_past_the_deadline_raises_at_once():
    c = Clock()
    rl = RateLimit(1, 1, sleep=c.sleep, clock=c)
    rl.take()
    with pytest.raises(PastDeadline, match="request rate"):
        rl.take(until=time.monotonic() + 0.1)
    assert c.slept == []


def test_two_processes_share_one_bucket_through_its_file(tmp_path):
    c = Clock()
    a = RateLimit(1, 2, tmp_path / "s.rate", sleep=c.sleep, clock=c)
    b = RateLimit(1, 2, tmp_path / "s.rate", sleep=c.sleep, clock=c)
    a.take()
    b.take()                                            # the burst of two is shared: the third waits
    a.take()
    assert sum(c.slept) == pytest.approx(1.0)
    b.hold(5.0)
    a.take()
    assert sum(c.slept) == pytest.approx(6.0)


def test_a_round_stops_at_its_budget():
    b = Budget(requests=3, what="the inference round")
    for _ in range(3):
        b.spend("x")
    with pytest.raises(OverBudget, match="made its 3 requests"):
        b.spend("x")
    with pytest.raises(OverBudget, match="past the deadline"):
        Budget(until=time.monotonic() - 1).spend("x")
    assert issubclass(OverBudget, PastDeadline)


FINE_SUM = [({"svc": "a", "region": "eu"}, [(0, 1.0), (60, 2.0)]), ({"svc": "a", "region": "us"}, [(0, 3.0), (60, 5.0)]),
            ({"svc": "b", "region": "eu"}, [(0, 10.0), (60, 20.0)])]
FINE_COUNT = [({"svc": "a", "region": "eu"}, [(0, 1.0), (60, 2.0)]), ({"svc": "a", "region": "us"}, [(0, 1.0), (60, 1.0)]),
              ({"svc": "b", "region": "eu"}, [(0, 2.0), (60, 0.0)])]


def _by(rows):
    return {tuple(sorted(lab.items())): pts for lab, pts in rows}


def test_coarser_groupings_are_exact_from_the_finest():
    assert _by(regroup(FINE_SUM, ["svc"], "sum")) == {(("svc", "a"),): [(0, 4.0), (60, 7.0)], (("svc", "b"),): [(0, 10.0), (60, 20.0)]}
    assert _by(regroup(FINE_SUM, [], "sum")) == {(): [(0, 14.0), (60, 27.0)]}
    assert _by(regroup(FINE_SUM, ["region"], "max")) == {(("region", "eu"),): [(0, 10.0), (60, 20.0)], (("region", "us"),): [(0, 3.0), (60, 5.0)]}
    assert _by(derive({"count": FINE_COUNT}, "count", ["svc"]))[(("svc", "a"),)] == [(0, 2.0), (60, 3.0)]
    # an average is the sum of sums over the sum of counts, never an average of averages
    avg = _by(derive({"sum": FINE_SUM, "count": FINE_COUNT}, "avg", []))[()]
    assert avg == [(0, 14.0 / 4), (60, 27.0 / 3)]


def test_how_many_values_report_is_exact_from_the_finest_counts():
    got = _by(distinct(FINE_COUNT, [], ["region"]))
    assert got == {(): [(0, 2.0), (60, 2.0)]}          # at 60, b/eu has no reporter, a/eu still has
    assert _by(distinct(FINE_COUNT, ["svc"], ["region"]))[(("svc", "b"),)] == [(0, 1.0)]
