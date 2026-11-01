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


def test_each_series_its_views_name_carries_the_title_its_part_gets(tmp_path):
    from orchestra.collect.views import parse

    m = FileMetrics(tmp_path / "m.jsonl")
    lab = {"instrument": "workflows.piles", "project": "p", "workflow": "delivery_sail"}
    pile = lambda st, pl: {**lab, "pile": f"{st}.{pl}", "step": st, "place": pl}
    m.write([Point("workflow_pile_items", 1, T0, pile("write", "held")), Point("workflow_pile_items", 0, T0, pile("ci", "waiting")),
             Point("workflow_pile_oldest_seconds", 4, T0, pile("write", "held")),
             Point("workflow_pile_moves_total", 3, T0, {**lab, "from": "write.held", "to": "ci.waiting"})])
    views = parse({"workflow_pile_items": {"view": "count", "place": "pile"}, "workflow_pile_oldest_seconds": {"view": "age"},
                   "workflow_pile_moves_total": {"view": "moves", "starts": "to", "stops": "from"}})
    got = instrument_series(m, "workflows.piles", T0 + 1, views=views)
    assert sorted(r.get("title") for r in got["series"]) == [
        "age of write (held) · delivery_sail", "ci (waiting) · delivery_sail", "write (held) · delivery_sail",
        "write (held) → ci (waiting) · delivery_sail"]
    assert all("title" not in r for r in instrument_series(m, "workflows.piles", T0 + 1)["series"])
