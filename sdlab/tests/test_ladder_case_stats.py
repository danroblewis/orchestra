"""case_stats.py: each case's verdict per strategy and the counts the Cases list colours by."""

from sdlab.ladder import case_stats


def test_verdict():
    assert case_stats.verdict([None, None]) is None
    assert case_stats.verdict(["pass", None, "pass"]) == "pass"
    assert case_stats.verdict(["pass", "equivalent"]) == "equivalent"
    assert case_stats.verdict(["pass", "fail", "error"]) == "fail"
    assert case_stats.verdict(["pass", "timeout"]) == "error"


def _cell(case, strategy, variant, status):
    return {"case": case, "strategy": strategy, "variant": variant, "status": status}


def test_rows_counts_and_reuse():
    cells = [_cell("a", "s1", "v1", "pass"), _cell("a", "s1", "v2", "pass"),
             _cell("a", "s2", "v1", "pass"), _cell("a", "s2", "v2", "fail"),
             _cell("a", "s3", "v1", None), _cell("a", "s3", "v2", None),
             _cell("a", "gone", "v1", "pass")]
    sm = {"strategies": [{"name": "s1"}, {"name": "s2"}, {"name": "s3"}],
          "cases": [{"id": "a", "level": 1, "tags": ["kubernetes"]}], "cells": cells}
    (r,) = case_stats.rows(sm)
    assert r == ["a", "kubernetes", True, 1, 2, 1, 0, 1, 0, 4, 3, 6]   # ran 2, 1 pass, 1 fail; cells 3 of 4 run pass, 6 cells
    made = case_stats._memo["a"][1]
    case_stats.rows(sm)
    assert case_stats._memo["a"][1] is made                               # unchanged cells: the row is reused
    sm["cells"] = [*cells[:-2], _cell("a", "s3", "v2", "pass"), cells[-1]]
    assert case_stats.rows(sm)[0][4:6] == [3, 2]                          # a changed cell: added up again
