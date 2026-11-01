"""The Instruments page lists an instrument's series with their latest values (web/instrument_series.py):
read from the metrics store by the ``instrument`` label, never by running the instrument; the owner
(2026-11-01) looked for the piles there."""

from orchestra.metrics import Point
from orchestra.metrics.file import FileMetrics
from orchestra.web.instrument_series import instrument_series

T0 = 1_800_000_000.0


def test_an_instruments_series_are_listed_with_their_latest_values(tmp_path):
    m = FileMetrics(tmp_path / "m.jsonl")
    pile = {"instrument": "workflows.piles", "project": "p", "workflow": "w", "pile": "write.held", "step": "write",
            "place": "held", "describes": "held by role worker"}
    m.write([Point("workflow_pile_items", 2, T0, pile), Point("workflow_pile_items", 3, T0 + 10, pile),
             Point("workflow_pile_moves_total", 7, T0 + 10, {"instrument": "workflows.piles", "project": "p", "workflow": "w",
                                                             "from": "write.held", "to": "<end>"}),
             Point("floor_offers", 1, T0 + 10, {"instrument": "workflows.floor", "project": "p"}),
             Point("workflow_pile_items", 9, T0 - 7200, {**pile, "pile": "gone.held", "step": "gone"})])
    got = instrument_series(m, "workflows.piles", T0 + 20)
    assert got["ok"] and got["more"] == 0
    assert [(r["name"], r["value"], r["at"]) for r in got["series"]] == [
        ("workflow_pile_items", 3, T0 + 10), ("workflow_pile_moves_total", 7, T0 + 10)]
    assert got["series"][0]["labels"] == {k: v for k, v in pile.items() if k not in ("instrument", "project")}


def test_no_store_says_so():
    assert instrument_series(None, "x", T0) == {"ok": False, "error": "the metrics store could not be opened"}
