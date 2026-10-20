"""The push test (sdlab/ladder/pushes.py): the truth pushed against itself agrees everywhere; a reversed
flow shows as a spurious response, a missing flow as a missing one; a wrong coefficient on an input that a
wrong drain balances (the same steady-state gain) is caught at a fast sine period and by the impulse; the
engine runs a truth (and a found model) with a MIN; the sine fit recovers a known gain and phase."""

from __future__ import annotations

import copy
import math

import numpy as np
import pytest

from sdlab.ladder import cases, data, pushes
from sdlab.skill import truth_by_time


def _bench(cid: str, variant: str = "none-short"):
    c = cases.load(cid)
    tm = cases.truth_model(c, variant)
    d = data.load(c, variant)
    return tm, d, pushes.Bench(tm, d.get("clean") or d)


def _truth_as_found(tm, d):
    return truth_by_time(tm, d["t"])[0]


@pytest.mark.parametrize("cid", ["300-k8s-requests-in-flight", "301-k8s-request-queue", "303-k8s-daily-traffic"])
def test_truth_agrees_with_itself(cid):
    tm, d, b = _bench(cid)
    out = pushes.compare(b, _truth_as_found(tm, d))
    assert out["agree"] == 1.0 and out["verdict"] == "agrees"
    assert not any(out["footprint"].values())
    assert out["diagnosis"] == ["every push answered as the truth answers"]
    # the battery: an impulse per measured stock, and impulse, step and sines per input and per outside inflow
    kinds = {(p["on"], p["kind"]) for p in out["pushes"]}
    assert {("stock", "impulse"), ("input", "impulse"), ("input", "step"), ("input", "sine"), ("inflow", "step")} <= kinds
    assert out["n"] == len(out["pushes"]) * len(d["levels"])


def test_bench_leaves_the_truth_model_alone():
    c = cases.load("303-k8s-daily-traffic")
    tm = cases.truth_model(c, "none-short")
    before = copy.deepcopy(tm)
    pushes.Bench(tm, data.load(c, "none-short"))
    assert tm == before


def test_reversed_flow_is_a_spurious_response():
    """queue -> inflight reversed (inflight -> queue): an impulse into inflight moves the queue, which the
    truth's queue never does."""
    tm, d, b = _bench("301-k8s-request-queue")
    flows = _truth_as_found(tm, d)
    for f in flows:
        if f.get("from") == "queue" and f.get("to") == "inflight":
            f["from"], f["to"] = "inflight", "queue"
            f["byTime"] = [{**g, "rate": {**g["rate"], "stock": "inflight"}} for g in f["byTime"]]
    out = pushes.compare(b, flows)
    assert ["an impulse into inflight", "queue"] in out["footprint"]["spurious"]
    assert any("queue" in m and "a path the truth does not have" in m for m in out["diagnosis"])


def test_missing_flow_is_a_missing_response():
    tm, d, b = _bench("301-k8s-request-queue")
    flows = [f for f in _truth_as_found(tm, d) if not (f.get("from") == "queue" and f.get("to") == "inflight")]
    flows.append({"from": "queue", "to": None, "rate": {"form": "proportional", "stock": "queue", "k": 0.6}})
    out = pushes.compare(b, flows)
    assert ["an impulse into queue", "inflight"] in out["footprint"]["missing"]
    assert any("does not respond" in m and "a missing path" in m for m in out["diagnosis"])


def test_balanced_wrong_numbers_are_caught_where_the_steady_gain_hides_them():
    """Case 300's stored failure: traffic x 1.2748 in, 0.6373 x inflight out; the same steady-state gain
    from traffic (2.0) as the truth's 1 / 0.5, so a step in traffic agrees, but the impulse into the stock,
    the traffic impulse and the fast sine do not."""
    tm, d, b = _bench("300-k8s-requests-in-flight")
    found = [{"from": "inflight", "to": None, "rate": {"form": "proportional", "stock": "inflight", "k": 0.6373}},
             {"from": None, "to": "inflight", "rate": {"form": "linear", "c": 0, "terms": [{"stock": "traffic", "k": 1.274802}]}}]
    out = pushes.compare(b, found)
    by = {p["push"]: p["stocks"]["inflight"] for p in out["pushes"]}
    assert by["a step in traffic"]["agree"]
    assert not by["an impulse into inflight"]["agree"]
    assert not by["a one-step impulse in traffic"]["agree"]
    fast = min((p for p in out["pushes"] if p["kind"] == "sine" and p["on"] == "input"), key=lambda p: p["period"])
    assert not fast["stocks"]["inflight"]["agree"]
    assert any("the path from traffic to inflight is too strong" in m for m in out["diagnosis"])
    assert any("its own drain is too fast" in m for m in out["diagnosis"])
    assert out["tau_found"] < out["tau_true"]


def test_engine_runs_a_min_truth_and_a_min_found_model():
    tm, d, b = _bench("222-distilled-drain-at-min-of-capacity-and-level", "counts-short")
    assert b.engine
    out = pushes.compare(b, [dict(f) for f in tm["flows"]])
    assert out["agree"] == 1.0
    assert out["notes"] == ["found model run on the engine (a flow with an expression)"]
    # the same truth with the MIN replaced by its capacity (a drain that ignores the backlog): X keeps all it gets
    flows = [dict(f) for f in tm["flows"]]
    for f in flows:
        if (f.get("rate") or {}).get("form") == "expr":
            f["rate"] = {"form": "proportional", "stock": "Y", "k": 0.2}
    out = pushes.compare(b, flows)
    assert out["verdict"] == "differs"


def test_sine_fit_recovers_gain_and_phase():
    P = 20
    h = np.arange(400)
    r = 3.0 + 0.01 * h + 0.7 * np.sin(2 * math.pi * h / P - math.radians(40))
    g, ph = pushes._sine(r, P)
    assert g == pytest.approx(0.7, rel=1e-9)
    assert ph == pytest.approx(-40.0, abs=1e-6)


def test_freeze_takes_the_piece_that_holds():
    f = {"from": None, "to": "A", "byTime": [{"from": 1, "to": 50, "rate": {"form": "constant", "value": 1}},
                                             {"from": 51, "to": 100, "rate": {"form": "constant", "value": 2}}]}
    assert pushes._freeze(f, 100)["rate"]["value"] == 2 and "byTime" not in pushes._freeze(f, 100)
    g = {"from": None, "to": "A", "rate": {"form": "constant", "value": 0}, "inflow": [{"from": 1, "to": 10, "value": 5.0}]}
    assert pushes._freeze(g, 10)["rate"] == {"form": "constant", "value": 5.0}


def test_a_response_below_the_footprint_on_both_sides_agrees():
    """Neither model responds (both below FOOT x the push's largest true response): the footprints match, so the
    comparison agrees, whatever the two small curves' relative difference (it was a 'wrong-signed path' of 0)."""
    tm, d, b = _bench("003-chain-2")
    leak = {"id": "leak", "from": "B", "to": "A", "rate": {"form": "proportional", "stock": "B", "k": 0.004}}
    out = pushes.compare(b, _truth_as_found(tm, d) + [leak])
    row = next(p for p in out["pushes"] if p["on"] == "stock" and p["target"] == "B")["stocks"]["A"]
    assert row["responds"] == [False, False] and row["err"] > pushes.TOL_SHAPE and row["agree"]
    assert out["agree"] == 1.0 and not any(out["footprint"].values())
    leak["rate"]["k"] = 0.02                                           # above the footprint: a path the truth does not have
    out = pushes.compare(b, _truth_as_found(tm, d) + [leak])
    assert any(s == "A" and push.endswith("B") for push, s in out["footprint"]["spurious"])


def test_a_stock_at_the_top_of_its_range_is_pushed_down_and_extrapolations_are_marked():
    """018's C settles at the top of what the run recorded (70): the impulse takes material out of C, so it stays
    where the data are (a found table effect ends at the last level seen); a push that takes the truth beyond the
    recorded range is marked, and agree_in_range leaves it out."""
    tm, d, b = _bench("018-table-effect", "none-long")
    names = [p["name"] for p in b.pushes if p["on"] == "stock"]
    assert "an impulse out of C" in names
    imp = next(p for p in b.pushes if p["name"] == "an impulse out of C")
    assert imp["size"] < 0
    out = pushes.compare(b, _truth_as_found(tm, d))
    assert out["agree"] == 1.0 and out["agree_in_range"] == 1.0
    step = next(p for p in out["pushes"] if p["kind"] == "step" and p["target"] == "C")
    assert "C" in step["outside_data"]
    assert 0 < out["n_in_range"] < out["n"]
    assert not next(p for p in out["pushes"] if p["push"] == "an impulse out of C").get("outside_data")
