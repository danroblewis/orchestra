"""Model complexity (sdlab/ladder/complexity.py): flows + numbers, counted the same way for the true
and the found model, per result as extra and ratio, and the Occam score."""

import copy

import pytest

from sdlab.ladder import complexity, store
from sdlab.ladder import cases as casemod
from sdlab.skill import truth_by_time


@pytest.fixture(autouse=True)
def cache(tmp_path, monkeypatch):
    monkeypatch.setenv("SDLAB_LADDER_CACHE", str(tmp_path / "ladder"))
    return tmp_path / "ladder"


def truth_total(case_id, variant="counts-short"):
    return complexity.of_truth(casemod.load(case_id), variant)["total"]


@pytest.mark.parametrize("case_id, variant, total", [
    ("001-inflow-only", "counts-short", 2),          # 1 flow + 1 constant
    ("003-chain-2", "counts-short", 6),              # 3 flows + 3 numbers
    ("011-goal-gap", "counts-short", 7),             # a gap is 2 numbers (goal, time)
    ("015-hidden-stock", "counts-short", 9),         # 4 flows + 4 numbers + 1 hidden stock
    ("016-coflow", "counts-short", 11),              # ... + 1 co-flow use
    ("017-linear-effect", "counts-short", 15),       # 5 flows + 5 numbers + a linear effect (normal, min, max)
    ("020-unannounced-step", "counts-short", 8),     # 3 flows + 3 numbers + 2 more pieces of the inflow in 300 steps
    ("020-unannounced-step", "counts-long", 25),     # ... 19 more pieces in 2000 steps
])
def test_true_models_count_as_documented(case_id, variant, total):
    assert truth_total(case_id, variant) == total


def test_the_parts_add_up():
    c = complexity.count(casemod.load("017-linear-effect")["model"]["flows"], complexity.measured(casemod.load("017-linear-effect")))
    assert c == {"flows": 5, "terms": 5, "pieces": 0, "other": 3, "total": 13}   # no schedule: no pieces


def test_the_truth_written_as_a_found_model_counts_the_same():
    for cid, variant in (("003-chain-2", "counts-short"), ("020-unannounced-step", "counts-long"), ("015-hidden-stock", "none-short")):
        c = casemod.load(cid)
        model = casemod.truth_model(c, variant)
        steps = casemod.variant(c, variant)["steps"]
        found = truth_by_time(model, list(range(2, steps + 1)))[0]
        cx = complexity.of_result({"case": cid, "variant": variant, "status": "pass", "found": found})
        assert cx["extra"] == 0 and cx["ratio"] == 1


def test_a_found_inflow_in_pieces_counts_every_piece():
    c = casemod.load("003-chain-2")
    found = copy.deepcopy(c["model"]["flows"])
    found[0]["inflow"] = [{"from": 2 + 30 * i, "to": 31 + 30 * i, "value": 20 + (i % 2) * 0.1} for i in range(9)]
    cx = complexity.of_result({"case": "003-chain-2", "variant": "counts-short", "status": "fail", "found": found})
    assert cx["true"] == 6 and cx["found"] == 14 and cx["extra"] == 8
    assert cx["by"] == {"flows": 0, "terms": 0, "pieces": 8, "other": 0}
    found[0]["inflow"] = [{"from": 2, "to": 100, "value": 20}, {"from": 101, "to": 300, "value": 20}]   # equal pieces are one
    assert complexity.of_result({"case": "003-chain-2", "variant": "counts-short", "status": "pass", "found": found})["extra"] == 0


def test_extra_flows_terms_and_hidden_stocks_count():
    c = casemod.load("003-chain-2")
    found = copy.deepcopy(c["model"]["flows"]) + [
        {"from": None, "to": "B", "rate": {"form": "linear", "c": 1.5, "terms": [{"stock": "A", "k": 0.01}, {"stock": "B", "k": 0}]}},
        {"from": "A", "to": "B", "via": {"delay": 4}, "rate": {"form": "proportional", "stock": "A", "k": 0.1}},
        {"from": "A", "to": "B", "rate": {"form": "proportional", "stock": "A", "k": 0.1},
         "effects": [{"stock": "B", "shape": "table", "points": [[0, 1], [100, 1]]}], "ratio": 2},
    ]
    cx = complexity.of_result({"case": "003-chain-2", "variant": "counts-short", "status": "fail", "found": found})
    # flows 1 + 2 + 1; terms 2 (zero term not written) + 2 (k, delay) + 1; other: hidden 1 + table 4 + ratio 1
    assert cx["by"] == {"flows": 4, "terms": 5, "pieces": 0, "other": 6}
    assert cx["extra"] == 15 and cx["found"] == 21


def test_occam_score():
    cx = {"true": 10, "found": 15, "extra": 5}
    assert complexity.occam("pass", 4, 4, cx) == pytest.approx(0.5)
    assert complexity.occam("equivalent", 2, 4, {**cx, "extra": -2}) == 1.0     # simpler than the truth: no penalty
    assert complexity.occam("fail", 3, 4, cx) == pytest.approx(0.25)
    assert complexity.occam("fail", 1, 4, {**cx, "extra": 30}) == 0.0
    assert complexity.occam("error", None, None, None) == 0.0
    assert complexity.occam(None, None, None, None) is None


def test_stored_results_are_counted_once():
    c = casemod.load("003-chain-2")
    rid = store.record({"case": "003-chain-2", "variant": "counts-short", "strategy": "x", "case_hash": c["hash"], "strategy_hash": "s",
                        "score_hash": "h", "status": "pass", "scores": {"right": 3, "of": 3}, "found": c["model"]["flows"]})
    eid = store.record({"case": "003-chain-2", "variant": "none-short", "strategy": "x", "case_hash": c["hash"], "strategy_hash": "s",
                        "score_hash": "h", "status": "error", "error": "boom"})
    rows = store.latest()
    got = complexity.for_results(rows)
    assert got[rid]["extra"] == 0 and got[eid] is None
    cell = complexity.cell(next(r for r in rows if r["id"] == rid), got[rid])
    assert cell["occam"] == 1.0 and cell["cx_true"] == 6 and cell["cx_by"] == [0, 0, 0, 0]
    assert complexity.for_results(rows) == got
