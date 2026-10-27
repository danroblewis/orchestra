"""The window a model is fitted on is the window's data, whatever a single series does: a collector
started near the end is an input, not a stock that cuts every flow's window to its few minutes."""

import random

from test_discover import simulate  # pytest puts this folder on the path

from orchestra.metrics import Point
from orchestra.metrics.file import FileMetrics
from orchestra.sd.discover import discover


def _late_queue(start: float, end: float, from_min: float) -> list[Point]:
    """A queue a new collector started measuring ``from_min`` minutes in, with its own counters
    of what came and went, written every 5 s: a real stock, with a short history."""
    rng, lab = random.Random(4), {"project": "p", "machine": "collector"}
    waiting = came = went = 0
    pts, t = [], start + from_min * 60
    while t <= end:
        if rng.random() < 0.4:
            came, waiting = came + 1, waiting + 1
        if waiting and rng.random() < 0.35:
            went, waiting = went + 1, waiting - 1
        pts += [Point("jobs_waiting", waiting, t, lab), Point("jobs_came_total", came, t, lab), Point("jobs_went_total", went, t, lab)]
        t += 5
    return pts


def test_a_series_that_starts_near_the_end_keeps_the_model_and_its_fit_span(tmp_path):
    store = FileMetrics(tmp_path / "m.jsonl")
    start, end = simulate(store, minutes=60)
    store.write(_late_queue(start, end, from_min=52))
    m = discover(store.dump("", {"project": "p"}), start=start, end=end, step=30)
    assert {"bakery_shelf_loaves", "bakery_oven_orders_pending"} <= {s.id for s in m.stocks}
    assert "jobs_waiting" not in {s.id for s in m.stocks}
    assert m.discovery["left_out"]['jobs_waiting{machine="collector"}'].startswith("written for only 8 min of the 60 min")
    # the fit span is the window's, not the new collector's eight minutes
    assert m.discovery["fit_start"] < start + 60, m.discovery["fit_start"] - start
    assert m.discovery["live_minutes"] > 55, m.discovery["live_minutes"]
    sold = m.flow("bakery_loaves_sold_total").current()
    assert sold.window[0] < start + 60 and sold.quality["live_minutes"] > 55, (sold.window, sold.quality)


def test_a_stock_whose_machine_started_later_cuts_only_its_own_flows(tmp_path):
    # a queue measured from 20 minutes in covers two thirds of the hour: a stock, fitted on its
    # own forty minutes, while the bakery's flows keep the whole hour
    store = FileMetrics(tmp_path / "m.jsonl")
    start, end = simulate(store, minutes=60)
    store.write(_late_queue(start, end, from_min=20))
    m = discover(store.dump("", {"project": "p"}), start=start, end=end, step=30)
    assert {"bakery_shelf_loaves", "bakery_oven_orders_pending", "jobs_waiting"} <= {s.id for s in m.stocks}
    came = m.flow("jobs_came_total").current()
    assert came.window[0] >= start + 20 * 60 - 30 and came.quality["live_minutes"] < 41, (came.window[0] - start, came.quality)
    sold = m.flow("bakery_loaves_sold_total").current()
    assert sold.window[0] < start + 60 and sold.quality["live_minutes"] > 55, (sold.window[0] - start, sold.quality)
    assert "jobs_waiting" not in sold.inputs
    assert m.stock("jobs_waiting").evidence["live_from"] >= start + 20 * 60


def _heartbeat(start: float, end: float) -> list[Point]:
    """Another machine writing every 5 s to the end: the system was being watched throughout."""
    return [Point("clock_seconds", float(i % 7), start + 5 * i, {"project": "p", "machine": "clock"}) for i in range(int((end - start) // 5) + 1)]


def test_a_machine_restarting_at_the_end_of_the_window_keeps_its_stocks(tmp_path):
    # the bakery's machines are being restarted: silent for the last two and a half minutes,
    # past their one-minute live limit, while another machine writes on. A discovery now must not
    # drop their stocks as gone (the live demo's ticket stocks went at 01:23, 140 s into the
    # scheduler's restart, and came back 15 s later)
    store = FileMetrics(tmp_path / "m.jsonl")
    start, end = simulate(store, minutes=60, outage=(57.5 * 60, 60 * 60))
    store.write(_heartbeat(start, end))
    m = discover(store.dump("", {"project": "p"}), start=start, end=end, step=30)
    assert {"bakery_shelf_loaves", "bakery_oven_orders_pending"} <= {s.id for s in m.stocks}, m.discovery["left_out"]
    assert m.flow("bakery_loaves_sold_total").current().quality["live_minutes"] > 55


def test_a_machine_not_yet_written_after_the_computer_woke_keeps_its_stocks(tmp_path):
    # the computer slept from minute 30: nothing at all was written. It woke half a minute before
    # the end, the host wrote at once, and the bakery's machines have not written yet. Their
    # silence of half an hour is the watcher's absence, not theirs
    store = FileMetrics(tmp_path / "m.jsonl")
    start, end = simulate(store, minutes=60, outage=(30 * 60, 60 * 60))
    store.write([Point("orchestra_host_up", 1.0, t, {"project": "p"}) for t in range(int(start), int(end) + 1, 5)
                 if t < start + 30 * 60 or t >= end - 30])
    m = discover(store.dump("", {"project": "p"}), start=start, end=end, step=30)
    assert {"bakery_shelf_loaves", "bakery_oven_orders_pending"} <= {s.id for s in m.stocks}, m.discovery["left_out"]


def test_a_machine_silent_longer_than_a_restart_is_gone(tmp_path):
    store = FileMetrics(tmp_path / "m.jsonl")
    start, end = simulate(store, minutes=60, outage=(50 * 60, 60 * 60))
    store.write(_heartbeat(start, end))
    m = discover(store.dump("", {"project": "p"}), start=start, end=end, step=30)
    assert not m.stocks
    assert m.discovery["left_out"]['bakery_shelf_loaves{machine="shop"}'].startswith("no longer written: its machine shop has been silent 10 min")
