"""The scorer's oracles on a truth with a piecewise-linear whole flow (kubernetes 306: dispatch =
min(0.6 x queue, 40 x ready)): the MIN's form in every step is known from the truth at the step's
state (parts.piecewise), so the linear oracle (oracle.py) and the Kalman model (noise_kf.py,
noise_oracle.py) fit each regime's numbers as columns of their own and give the truth's linear flows
measured standard errors, instead of none."""

from __future__ import annotations

import copy
import math

import numpy as np

from sdlab.ladder import cases as casemod
from sdlab.ladder import data, sim
from sdlab.ladder.noise_oracle import KalmanOracle, make_oracle
from sdlab.ladder.oracle import Oracle
from sdlab.ladder.parts import parts, piecewise, windows
from sdlab.skill import truth_by_time

CASE = "306-k8s-ready-replicas-cap"


def _expr(expr: str) -> dict:
    return {"id": "x", "from": "q", "to": "i", "rate": {"form": "expr", "expr": expr}, "whole": {"auxiliaries": {}}}


def test_a_min_is_two_regimes_with_their_own_linear_forms():
    q = np.array([10.0, 100.0, 500.0, 700.0, 20.0, 900.0] * 10)
    r = np.array([9.0, 9.0, 13.0, 9.0, 13.0, 13.0] * 10)
    X = np.vstack([q, r])
    regime, forms = piecewise(_expr("min(0.6 * q, 40 * r)"), {"t": list(range(len(q) + 1))}, ["q", "r"], X)
    demand = 0.6 * q <= 40 * r
    assert len(forms) == 2
    for k, (c, ks) in enumerate(forms):
        on = regime == k
        assert c == 0.0
        if demand[on].all():
            assert ks.keys() == {"q"} and math.isclose(ks["q"], 0.6, rel_tol=1e-6)
        else:
            assert not demand[on].any() and ks.keys() == {"r"} and math.isclose(ks["r"], 40.0, rel_tol=1e-6)


def test_a_smooth_curve_is_not_piecewise_linear():
    rng = np.random.default_rng(0)
    X = rng.uniform(1, 100, size=(2, 200))
    assert piecewise(_expr("0.01 * q * r"), {"t": list(range(201))}, ["q", "r"], X) is None
    assert piecewise(_expr("0.6 * zz"), {"t": list(range(201))}, ["q", "r"], X) is None     # reads what the data lack


def _load(variant: str):
    c = casemod.load(CASE)
    tm = casemod.truth_model(c, variant)
    d = data.load(c, variant)
    wins = windows(tm, d["t"])
    return tm, d, wins, sim.mark(truth_by_time(tm, d["t"])[0], tm)


def _keys(flows, d, wins):
    tp, _ = parts(flows, set(d["levels"]), wins[0], set(d.get("inputs") or {}))
    return [k for k in tp if k[0] == "flow"], list(tp)


def test_a_linear_expression_scores_as_the_same_linear_flow():
    """A whole flow whose expression is linear on the run (one regime) gives exactly the SEs of the
    same flow written as a linear rate."""
    tm, d, wins, flows = _load("counts-short")
    as_expr, as_linear = copy.deepcopy(flows), copy.deepcopy(flows)
    for f in as_expr:
        if f.get("whole"):
            f["rate"] = {"form": "expr", "expr": "0.6 * queue"}
            f.pop("byTime", None)
    for f in as_linear:
        if f.get("whole"):
            f.pop("whole")
            f["rate"] = {"form": "proportional", "stock": "queue", "k": 0.6}
            f.pop("byTime", None)
    a, b = Oracle(as_expr, d, wins), Oracle(as_linear, d, wins)
    assert a.ok and b.ok
    keys, true_keys = _keys(as_linear, d, wins)
    for k in keys:
        if k[1:3] != ("queue", "inflight"):
            assert math.isclose(a.part_se(k, true_keys, 0), b.part_se(k, true_keys, 0), rel_tol=1e-9), k


def test_the_min_truth_gets_measured_standard_errors_on_counts():
    tm, d, wins, flows = _load("counts-short")
    o = make_oracle(flows, d, wins)
    assert isinstance(o, Oracle) and o.ok
    keys, true_keys = _keys(flows, d, wins)
    assert ("flow", "retries", None, "retries") in keys
    for k in keys:
        se = o.part_se(k, true_keys, 0)
        assert se is not None and math.isfinite(se) and se > 0, k
    # the retries split: about what the same loop's split had on 305 (se 0.189), not the bare 10% of 0.4
    assert 0.1 < o.part_se(("flow", "retries", None, "retries"), true_keys, 0) < 0.3


def test_the_min_truth_gets_measured_standard_errors_on_meas():
    tm, d, wins, flows = _load("meas-short")
    o = make_oracle(flows, d, wins)
    assert isinstance(o, KalmanOracle) and o.ok
    keys, true_keys = _keys(flows, d, wins)
    for k in keys:
        se, clean = o.part_se(k, true_keys, 0), o.linear.part_se(k, true_keys, 0)
        assert se is not None and math.isfinite(se) and se > 0, k
        assert clean is not None and se >= 0.999 * clean, k             # the reported data never know more than the clean run
