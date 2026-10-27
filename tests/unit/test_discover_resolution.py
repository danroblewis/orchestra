"""Each series is read at its own resolution: counts and states held, smooth measurements linear
between their real points; a slow level is balanced between its writes; a slow series drives no
fast flow; and discovery is fast enough for hours of a few hundred series at a fine step."""

import random

from orchestra.sd.discover import discover
from orchestra.sd.resolution import HOLD, LINEAR, measure
from orchestra.sd.series import Series, sample

T0 = 1_800_000_000.0


def test_a_series_change_per_step_is_worked_out_once():
    s = Series("x", {}, [], [0.0, 1.0, 3.0], False)
    assert s.deltas is s.deltas
    assert s.deltas == [1.0, 2.0]


def test_counts_are_held_and_measurements_resolved_by_their_changes():
    # a count written every 30 s: held, its resolution the write interval
    count = [(T0 + 30 * i, float(i // 4)) for i in range(100)]
    assert measure(count, False) == measure(count, False).__class__(30.0, HOLD)
    # a counter written only when it moves: as fine as its events
    assert measure([(T0 + 7 * i * i, float(i)) for i in range(20)], True, on_events=True).seconds is None
    # a temperature polled every minute that its feed changes every half hour: linear, 30 min
    feed = [(T0 + 60 * i, 10.0 + 0.37 * (i // 30)) for i in range(240)]
    r = measure(feed, False)
    assert r.read == LINEAR and abs(r.seconds - 1800) < 1e-6
    # a resolution its source declared is a floor
    assert measure(count, False, declared=60.0).seconds == 60.0


def test_a_measurement_is_read_linearly_between_its_real_points():
    pts = [(T0 + 60 * i, 1.5 if i < 30 else 4.5) for i in range(61)]     # one change, at 30 min
    [s] = sample([("temp", {}, pts)], T0, 600.0, 6)
    assert s.resolution.read == LINEAR
    # from its first point to the point where it changed, a ramp: 1.5 at 0, 4.5 at 30 min
    assert s.values[:4] == [1.5, 2.5, 3.5, 4.5]


def _queue(rng: random.Random, minutes: int, write_every: float):
    """A queue whose arrivals and departures are counted as they happen, and whose length is
    written every ``write_every`` seconds."""
    lab = {"machine": "queue"}
    length = arrived = served = 0
    a_pts, s_pts, l_pts = [(T0, 0.0)], [(T0, 0.0)], []
    for i in range(minutes * 60):
        t = T0 + i
        if rng.random() < 0.08:
            arrived, length = arrived + 1, length + 1
            a_pts.append((t + 0.5, float(arrived)))
        if length and rng.random() < 0.07:
            served, length = served + 1, length - 1
            s_pts.append((t + 0.5, float(served)))
        if i % write_every == 0:
            l_pts.append((t + 0.9, float(length)))
    return [("arrived_total", lab, a_pts), ("served_total", lab, s_pts), ("queue_length", lab, l_pts)]


def test_a_level_written_every_minute_is_balanced_between_its_writes():
    # on 5 s steps the length's change shows only in the step it is written in, a minute after the
    # counters counted it: no balance on single steps. Between its writes, it balances exactly
    dump = _queue(random.Random(3), 120, 60)
    m = discover(dump, start=T0, end=T0 + 7200, step=5.0)
    assert [s.id for s in m.stocks] == ["queue_length"], m.discovery["left_out"]
    ev = m.stocks[0].evidence
    assert ev["balance_r2"] > 0.99
    assert {b["series"] for b in ev["balance"]} == {'arrived_total{machine="queue"}', 'served_total{machine="queue"}'}


def test_a_slow_series_does_not_drive_a_fast_flow():
    # a worker busy for forty minutes of two hours; a feed that changes every half hour (polled
    # every minute) happened to be high then. Its intervals holding the worker's events are too
    # few to tell a driver from a coincidence: the worker's rate is a constant
    rng = random.Random(5)
    lab = {"machine": "worker"}
    started = finished = busy = 0
    st_pts, fi_pts, b_pts = [(T0, 0.0)], [(T0, 0.0)], [(T0, 0.0)]
    for i in range(7200):
        t = T0 + i
        rate = 1 / 60 if 2400 <= i < 4800 else 1 / 3000
        if not busy and rng.random() < rate:
            started, busy = started + 1, 1
            st_pts.append((t, float(started)))
            b_pts.append((t, 1.0))
        elif busy and rng.random() < 1 / 20:
            finished, busy = finished + 1, 0
            fi_pts.append((t, float(finished)))
            b_pts.append((t, 0.0))
    feed = [(T0 + 60 * i, (7.3 if 40 <= i < 80 else 1.1) + 0.01 * ((i // 30) % 2)) for i in range(121)]
    dump = [("turns_started_total", lab, st_pts), ("turns_finished_total", lab, fi_pts), ("working", lab, b_pts),
            ("space_weather_index", {"machine": "feed"}, feed)]
    m = discover(dump, start=T0, end=T0 + 7200, step=5.0)
    assert started >= 20
    [f] = [f for f in m.flows if f.id.startswith("turns_started")]
    assert f.current().inputs == [] or f.current().inputs == ["working"], f.current()
    assert not any(x.startswith("input:space_weather") for fl in m.flows for x in fl.current().inputs)
