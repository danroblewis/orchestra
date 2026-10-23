"""kalman_lna's 308/309 regressions since febd195 (docs/research/fixes/regress-kalman_lna.md): the tracker takes a hidden
stage feeding the controlled stock with the inflow side it replaces, reads a constant written as "value", and the rows
rebuild stocks a co-flow touches."""

from __future__ import annotations

from sdlab.discovery.strategies.kalman_lna import rows, tracker
from tests.test_kalman_lna_rows import _case
from tests.test_kalman_lna_tracker import _controlled, _run


def test_tracker_replaces_a_hidden_stage_with_the_inflow_side():
    x, s = _controlled()
    stocks, run = _run(x, s)
    T = len(s) - 1
    flows = [{"from": None, "to": "s_hidden", "ratio": 1, "rate": {"form": "constant", "value": 0.5}},
             {"from": "s_hidden", "to": "s", "ratio": 1, "rate": {"form": "proportional", "stock": "s_hidden", "k": 1.0}},
             {"from": "s", "to": None, "ratio": 1, "rate": {"form": "proportional", "stock": "s", "k": 0.01}}]
    r = tracker.revise({"flows": flows, "inferred_levels": {"s_hidden": [0.5] * (T + 1)}}, stocks, run, {})
    assert "tracker" in r
    into = [f for f in r["flows"] if f.get("to") in ("s", "s_hidden")]
    assert [f.get("id") for f in into] == ["tracker_in_s"]   # one inflow: the stage left with the side it fed
    assert "s_hidden" not in (r.get("inferred_levels") or {})


def test_tracker_reads_a_constant_written_as_value():
    assert tracker._rate_value({"form": "constant", "value": 0.25}, {}) == 0.25
    assert tracker._rate_value({"form": "constant", "c": 0.5}, {}) == 0.5


def test_rows_rebuild_the_stocks_a_coflow_touches():
    stocks, run = _case()
    proxy = [{"from": None, "to": "pending", "ratio": 1, "rate": {"form": "constant", "value": 0.3}},
             {"from": "pending", "to": "ready", "ratio": 1, "rate": {"form": "proportional", "stock": "pending", "k": 0.2},
              "uses": [{"stock": "desired", "per": 2.0}]},
             {"from": "pending", "to": "ready", "ratio": 1, "rate": {"form": "proportional", "stock": "pending", "k": 0.3}},
             {"from": "ready", "to": None, "ratio": 1, "rate": {"form": "constant", "value": 0.1}}]
    r = rows.revise({"flows": proxy}, stocks, run, {})
    assert {"pending", "ready"} <= set(r["rows"]["rebuilt"])     # before: the co-flow left both unread
    assert not any(f.get("uses") for f in r["flows"])
    got = {(f["from"], f["to"]): f["rate"] for f in r["flows"]}
    assert abs(got[("pending", "ready")]["k"] - 0.4) < 1e-6


def test_coflow_group():
    assert rows._co_group({"from": "a", "to": "b"}) == set()
    assert rows._co_group({"from": "a", "to": None, "uses": [{"stock": "c", "per": 1}]}) == {"a", "c"}
    assert rows._co_group({"from": None, "to": "b", "uses": [{"stock": "b"}]}) == {"b"}
