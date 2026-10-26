"""The Dynamics page's history samples levels at the discovery step when that is finer than its
own, so the chart shows the levels discovery saw."""

from orchestra.metrics import Point
from orchestra.metrics.file import FileMetrics
from orchestra.sd.model import Model, SeriesRef, Stock
from orchestra.web.background import STOCK_STEP_S, history, stock_step

T0 = 1_800_000_000.0


def test_a_level_held_four_seconds_shows_on_a_five_second_grid_not_a_fifteen(tmp_path):
    store = FileMetrics(tmp_path / "m.jsonl")
    lab = {"project": "p", "machine": "m"}
    end = T0 + 3600
    at = end - 60 - (end - 60) % 15 + 5                     # up at 5 s past a 15 s tick, down 4 s later
    store.write([Point("level", 0.0, T0, lab), Point("level", 1.0, at, lab), Point("level", 0.0, at + 4, lab)])
    model = Model("x", "x", stocks=[Stock("s", "s", series=SeriesRef("level", lab))], flows=[])
    coarse = history(model, store, end, stock_step(30.0))["stocks"]["s"]
    fine = history(model, store, end, stock_step(5.0))["stocks"]["s"]
    assert stock_step(30.0) == STOCK_STEP_S and stock_step(5.0) == 5.0
    assert max(v for _, v in coarse) == 0.0 and max(v for _, v in fine) == 1.0
