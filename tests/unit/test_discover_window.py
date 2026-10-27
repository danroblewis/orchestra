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
