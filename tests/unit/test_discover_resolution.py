"""Each series is read at its own resolution, its last value held (a measurement is never drawn as a
ramp between the points where it changed: review r1 F9); a slow level is balanced between its
writes, never between its changes; a slow series drives no fast flow; and discovery is fast enough
for hours of a few hundred series at a fine step."""

import random

from orchestra.sd.discover import discover
from orchestra.sd.resolution import HOLD, measure, observed_every
from orchestra.sd.series import Series, sample

T0 = 1_800_000_000.0


def test_a_series_change_per_step_is_worked_out_once():
    s = Series("x", {}, [], [0.0, 1.0, 3.0], False)
    assert s.deltas is s.deltas
    assert s.deltas == [1.0, 2.0]


def test_counts_are_held_and_measurements_resolved_by_their_changes():
    # a count written every 30 s that changes every 2 min: held, its resolution its changes'
    count = [(T0 + 30 * i, float(i // 4)) for i in range(100)]
    assert measure(count, False) == measure(count, False).__class__(120.0, HOLD)
    # one that changes at every write: the write interval
    assert measure([(T0 + 30 * i, float(i % 7)) for i in range(100)], False).seconds == 30.0
    # a counter written only when it moves: as fine as its events
    assert measure([(T0 + 7 * i * i, float(i)) for i in range(20)], True, on_events=True).seconds is None
    # a temperature polled every minute that its feed changes every half hour: held, 30 min
    feed = [(T0 + 60 * i, 10.0 + 0.37 * (i // 30)) for i in range(240)]
    r = measure(feed, False)
    assert r.read == HOLD and abs(r.seconds - 1800) < 1e-6
    # ... but it is observed every minute: its balance is judged between its writes, not its changes
    assert observed_every(feed, r) == 60.0
    # a resolution its source declared is a floor
    assert measure(count, False, declared=60.0).seconds == 120.0
    assert measure(count, False, declared=600.0).seconds == 600.0


def test_a_whole_valued_feed_polled_every_minute_is_as_slow_as_its_changes():
    # a power demand in whole MW that its feed updates every half hour, polled every minute: held
    # (whole values), but its resolution is half an hour, not the minute it is polled at
    rng = random.Random(11)
    demand, pts = 25000, []
    for i in range(6 * 60):
        if i % 30 == 0:
            demand += rng.choice([-1, 1]) * rng.randint(50, 400)
        pts.append((T0 + 60 * i + rng.uniform(0, 2), float(demand)))
    r = measure(pts, False)
    assert r.read == HOLD and abs(r.seconds - 1800) < 10, r


def test_an_hourly_measurement_in_a_few_hours_is_resolved_by_its_changes():
    # six hourly readings of an air quality index: too few to show a schedule, but it changed
    # five times an hour apart
    pts = [(T0 + 3600 * i + 40 * (i % 2), float(v)) for i, v in enumerate([42, 45, 51, 48, 39, 44])]
    r = measure(pts, False)
    assert r.read == HOLD and abs(r.seconds - 3600) < 60, r
    # one reading of a smooth measurement as well
    assert abs(measure([(T0 + 3600 * i, 10.0 + 0.1 * i * i) for i in range(6)], False).seconds - 3600) < 1e-6
    # but a few writes of a state, in bursts and silences, are things happening
    burst = [(T0 + t, float(i % 2)) for i, t in enumerate([0, 20, 45, 3000, 3030, 9000, 9010, 9040])]
    assert measure(burst, False).seconds is None


def test_a_count_written_only_when_it_moves_is_as_fine_as_its_events():
    # a queue's length written at every arrival and departure, in bursts and silences
    rng = random.Random(12)
    t, n, pts = T0, 5, []
    for _ in range(300):
        t += rng.expovariate(1 / 20) if rng.random() < 0.3 else rng.uniform(0.01, 0.5)
        n = max(0, n + rng.choice([-1, 1]))
        pts.append((t, float(n)))
    assert measure(pts, False).seconds is None


def test_a_measurement_is_held_between_its_points_never_drawn_as_a_ramp():
    pts = [(T0 + 60 * i, 1.5 if i < 30 else 4.5) for i in range(61)]     # one change, at 30 min
    [s] = sample([("temp", {}, pts)], T0, 600.0, 6)
    assert s.resolution.read == HOLD
    # written every minute and 1.5 every time until 30 min: it was 1.5, not on its way to 4.5
    assert s.values[:4] == [1.5, 1.5, 1.5, 4.5]


def test_a_gauge_polled_often_that_changed_twice_is_balanced_on_every_step():
    # written every 30 s, changed twice in the hour (a pod's resource requests): 120 observations,
    # not two stretches between changes on which any two counters balance it exactly
    pts = [(T0 + 30 * i, 2.5e8 if i < 40 else (5.1e8 if i < 90 else 3.3e8)) for i in range(121)]
    [s] = sample([("requests_bytes", {}, pts)], T0, 30.0, 120)
    assert s.blocks is None
    assert sum(1 for d in s.deltas if d) == 2


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
    # a press busy for forty minutes of two hours; a feed that changes every half hour (polled
    # every minute) happened to be high then. Its intervals holding the press's jobs are too
    # few to tell a driver from a coincidence: the press's rate is a constant
    rng = random.Random(5)
    lab = {"machine": "press"}
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
    dump = [("jobs_started_total", lab, st_pts), ("jobs_finished_total", lab, fi_pts), ("working", lab, b_pts),
            ("space_weather_index", {"machine": "feed"}, feed)]
    m = discover(dump, start=T0, end=T0 + 7200, step=5.0)
    assert started >= 20
    [f] = [f for f in m.flows if f.id.startswith("jobs_started")]
    assert f.current().inputs == [] or f.current().inputs == ["working"], f.current()
    assert not any(x.startswith("input:space_weather") for fl in m.flows for x in fl.current().inputs)
