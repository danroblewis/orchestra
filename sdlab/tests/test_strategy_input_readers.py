"""periodic_inflows and recession on a case with a measured input (300: outside -> inflight = 1 x
traffic, a measured input; inflight -> outside = 0.5 x inflight). A row's numbers may name the input
as well as stocks' levels; both strategies looked every reader up among the stocks only and crashed
(ValueError: 'traffic' is not in list) when a profile (periodic_inflows) or a quiet fit (recession)
reached that row. The input is a known regressor of the row, and its number stays an input flow."""

from __future__ import annotations

import pytest

from sdlab.ladder import cases as casemod
from sdlab.ladder import data
from sdlab.ladder.runner import discover

CASE = "300-k8s-requests-in-flight"


@pytest.mark.parametrize("strategy", ["periodic_inflows", "recession"])
def test_a_row_reading_a_measured_input(strategy):
    c = casemod.load(CASE)
    d = data.load(c, "none-long")
    r = discover(strategy, casemod.truth_model(c, "none-long"), d)
    into = [f for f in r["flows"] if f.get("to") == "inflight" and not f.get("from")]
    assert any(f.get("input") == "traffic" and abs(f["rate"]["terms"][0]["k"] - 1) < 0.05 for f in into), into
    out = [f for f in r["flows"] if f.get("from") == "inflight" and not f.get("to")]
    assert any(abs((f["rate"].get("k") or f["rate"].get("terms", [{}])[0].get("k") or 0) - 0.5) < 0.05 for f in out), out
