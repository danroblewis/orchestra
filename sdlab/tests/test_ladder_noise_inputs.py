"""The noise oracle (noise_kf.py, noise_oracle.py, noise_analysis.py) on a case with a measured input:
the input is a known column of the Kalman model (its value during the step, as the linear oracle reads
it), so a meas variant gets measured standard errors and the analysis runs instead of crashing."""

from __future__ import annotations

import math

import numpy as np

from sdlab.ladder import data, noise_analysis, noise_kf
from sdlab.ladder import cases as casemod
from sdlab.ladder.noise_oracle import KalmanOracle, clean_view, make_oracle
from sdlab.ladder.parts import windows
from sdlab.skill import truth_by_time

CASE = "300-k8s-requests-in-flight"          # outside -> inflight = 1 x traffic (a measured input); inflight -> outside = 0.5 x inflight


def _load(variant: str):
    c = casemod.load(CASE)
    tm = casemod.truth_model(c, variant)
    d = data.load(c, variant)
    return tm, d, windows(tm, d["t"])


def test_meas_variant_with_an_input_gets_measured_standard_errors():
    tm, d, wins = _load("meas-short")
    assert d.get("inputs")
    o = make_oracle(truth_by_time(tm, d["t"])[0], d, wins)
    assert isinstance(o, KalmanOracle) and o.ok
    for col in ("inflight", "traffic"):
        se, clean = o.se("inflight", col, 0), o.linear.se("inflight", col, 0)
        assert se is not None and math.isfinite(se) and se > 0
        assert se >= clean * 0.999                  # the reported data never know more than the clean run


def test_the_input_drives_the_state_space_model():
    """On the clean run observed exactly, the truth's innovations are only the counting noise: centred,
    and of the size the model's own covariance says (they would carry the whole inflow if the input
    were left out of the means, and the inflow's noise would be missing from Q)."""
    tm, d, wins = _load("meas-long")
    m = noise_kf.model(clean_view(d), wins)
    assert m is not None and m.inputs == ["traffic"]
    e, S = m.innovations(m.theta0, want_S=True)
    z = e[5:, 0] / np.sqrt(S[5:, 0, 0])
    assert abs(float(np.mean(z))) < 0.1
    assert 0.8 < float(np.std(z)) < 1.2


def test_the_kalman_bound_on_an_input_case_and_its_analysis():
    tm, d, wins = _load("meas-long")
    m = noise_kf.model(d, wins)
    C, null = m.bound()
    assert null.size == 0
    se = dict(zip(m.labels, np.sqrt(np.diag(C)) / m.theta0))
    assert all(0.005 < v < 0.05 for v in se.values()), se          # a few percent on 2000 steps at 5% error
    a = noise_analysis.analyse(CASE, "meas-long")                  # crashed: the model had no input column
    assert a["label"] != "not analysed" and a["parts"]
    assert {r["column"] for row in a["design"] for r in row["terms"]} >= {"traffic", "inflight"}
