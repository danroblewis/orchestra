"""The noises laid on recorded levels (sdlab/ladder/noise.py) and what the scorer and analysis make of
them (noise_kf.py, noise_oracle.py, noise_analysis.py): opt-in only, deterministic, with the right
statistics, and the truth's own structure passes its own scoring wherever the data allow it."""

from __future__ import annotations

import numpy as np
import pytest

from sdlab.ladder import analysis, data, noise, noise_kf, score
from sdlab.ladder import cases as casemod
from sdlab.ladder.noise_oracle import KalmanHidden, KalmanOracle, make_hidden_oracle, make_oracle
from sdlab.ladder.oracle import Oracle
from sdlab.ladder.parts import windows
from sdlab.skill import truth_by_time

NOISY = ["080-noisy-chain-2", "081-noisy-link", "082-noisy-link-loop", "083-noisy-goal-gap", "084-noisy-two-chains",
         "085-noisy-hidden-stock", "086-noisy-stepping-inflow", "087-noisy-injection"]
KINDS = ["meas", "gaps", "weekly", "lag", "outliers", "bias"]


def _get(cid, variant, fresh=False):
    c = casemod.load(cid)
    return c, data.load(c, variant, fresh=fresh)


# ---- opt-in: existing cases are untouched ----

def test_existing_cases_keep_their_four_variants():
    for cid in casemod.case_ids():
        c = casemod.load(cid)
        if "noisy" in c["tags"] or casemod.is_realistic(cid):
            continue
        assert not any(v.get("observe") for v in c["variants"]), cid
        assert {v["noise"] for v in c["variants"]} <= {"none", "counts"}, cid


def test_existing_hashes_do_not_depend_on_the_noise_code(monkeypatch):
    plain, noisy = casemod.load("003-chain-2"), casemod.load("080-noisy-chain-2")
    before = (casemod.case_hash(plain), casemod.case_hash(noisy))
    monkeypatch.setattr(noise, "code_hash", lambda: "something else")
    assert casemod.case_hash(plain) == before[0], "a case that does not opt in is hashed without noise.py"
    assert casemod.case_hash(noisy) != before[1], "a case that opts in is hashed with it"


def test_counts_data_is_the_engines():
    """The noisy case's counts variant is the same run as its original's, and a noisy variant's clean
    run is that counts run, untouched."""
    _, a = _get("003-chain-2", "counts-short")
    _, b = _get("080-noisy-chain-2", "counts-short")
    _, m = _get("080-noisy-chain-2", "meas-short")
    assert a["levels"] == b["levels"] and "observation" not in a and "clean" not in a
    assert m["clean"]["levels"] == a["levels"] and m["clean"]["t"] == a["t"]


def test_noise_entries():
    assert noise.entries(["none", "counts"]) == [("none", None), ("counts", None)]
    (_, o), = noise.entries([{"meas": {"rel": 0.1}}])
    assert o == {"kind": "meas", "rel": 0.1, "abs": 1.0}
    for bad in (["sparkles"], ["meas", "meas"], [{"meas": {"size": 1}}], [{"gaps": {"missing": 1.5}}], [{"counts": {"x": 1}}]):
        with pytest.raises(noise.NoiseError):
            noise.entries(bad)
    with pytest.raises(casemod.CaseError):
        casemod._build("999-x", {"model": {"stocks": [{"id": "A", "initial": 0}], "flows": []}, "variants": {"noise": ["sparkles"]}})


# ---- determinism and statistics ----

@pytest.mark.parametrize("kind", KINDS)
def test_deterministic_from_the_seed(kind):
    _, a = _get("084-noisy-two-chains", f"{kind}-long")
    _, b = _get("084-noisy-two-chains", f"{kind}-long")
    _, f = _get("084-noisy-two-chains", f"{kind}-long", fresh=True)
    assert a == b
    assert f["clean"]["levels"] != a["clean"]["levels"], "the fresh run is the next seed"


def test_meas_statistics():
    c, d = _get("084-noisy-two-chains", "meas-long")
    o = d["observation"]
    z = np.concatenate([(np.asarray(d["levels"][s]) - np.asarray(d["clean"]["levels"][s])) / np.sqrt(o["abs"] ** 2 + (o["rel"] * np.asarray(d["clean"]["levels"][s])) ** 2)
                        for s in d["levels"]])
    assert abs(z.mean()) < 4 / np.sqrt(len(z)) and abs(z.std() - 1) < 0.03, (z.mean(), z.std())
    assert d["t"] == d["clean"]["t"]


def test_gaps_statistics():
    _, d = _get("084-noisy-two-chains", "gaps-long")
    t, ct = d["t"], d["clean"]["t"]
    kept = (len(t) - 2) / (len(ct) - 2)
    assert abs(kept - 0.7) < 0.035 and t[0] == ct[0] and t[-1] == ct[-1] and all(b > a for a, b in zip(t, t[1:]))
    assert max(np.diff(t)) > 1
    for s, v in d["levels"].items():
        assert v == [d["clean"]["levels"][s][ct.index(x)] for x in t]


def test_weekly_statistics():
    _, d = _get("080-noisy-chain-2", "weekly-short")
    assert d["t"] == list(range(7, 301, 7))
    for s, v in d["levels"].items():
        x = np.asarray(d["clean"]["levels"][s], dtype=float)
        assert np.allclose(v, [x[i - 6: i + 1].mean() for i in range(6, 300, 7)], atol=1e-4)
    assert d["all_levels"]["A"] == [d["clean"]["all_levels"]["A"][i] for i in range(6, 300, 7)]


def test_lag_statistics():
    _, d = _get("087-noisy-injection", "lag-short")
    assert d["t"] == d["clean"]["t"][3:]
    for s, v in d["levels"].items():
        assert v == d["clean"]["levels"][s][:-3]
    assert d["injections"] == d["clean"]["injections"], "announced events keep their times"


def test_outliers_statistics():
    _, d = _get("084-noisy-two-chains", "outliers-long")
    out = {(i, s) for i, s in d["observation"]["outliers"]}
    n = len(d["t"]) * len(d["levels"])
    assert abs(len(out) / n - 0.01) < 0.004
    for s, v in d["levels"].items():
        x = d["clean"]["levels"][s]
        m = float(np.mean(np.abs(x)))
        for i, (a, b) in enumerate(zip(v, x)):
            if (i, s) in out:
                assert abs(a - b) >= min(0.5 * max(m, 10) - 1e-6, b), (s, i)        # gross (or clipped at 0)
            else:
                assert a == b


def test_bias_statistics():
    _, d = _get("084-noisy-two-chains", "bias-long")
    assert d["observation"]["bias"] == {"B2": 1.2}
    for s, v in d["levels"].items():
        x = np.asarray(d["clean"]["levels"][s], dtype=float)
        assert np.allclose(v, x * (1.2 if s == "B2" else 1.0), atol=1e-4)


# ---- the scorer: oracle routing, the truth passes ----

def test_scorer_uses_the_kalman_oracle_and_hashes_it():
    assert score.make_oracle is make_oracle and analysis.make_oracle is make_oracle
    import inspect
    assert "noise_oracle.py" in inspect.getsource(score.score_hash) and "noise_kf.py" in inspect.getsource(score.score_hash)


def test_noisy_data_get_the_kalman_oracle():
    c, d = _get("080-noisy-chain-2", "meas-short")
    tm = casemod.truth_model(c, "meas-short")
    flows, _ = truth_by_time(tm, d["t"])
    assert isinstance(make_oracle(flows, d, windows(tm, d["t"])), KalmanOracle)
    _, plain = _get("003-chain-2", "counts-short")
    assert type(make_oracle(flows, plain, windows(tm, plain["t"]))) is Oracle
    c, d = _get("085-noisy-hidden-stock", "gaps-short")
    tm = casemod.truth_model(c, "gaps-short")
    assert isinstance(make_hidden_oracle(truth_by_time(tm, d["t"])[0], d, windows(tm, d["t"]), "gaps"), KalmanHidden)


def test_lag_and_outliers_cost_nothing_and_meas_costs_more_with_its_size():
    """The SE on the reported data over the SE on the clean run: a lag and a few outliers (left out)
    cost nothing; measurement error costs more the larger it is; at 0 it is the counts variant."""
    for v in ("lag-long", "outliers-long"):
        a = analysis.get("080-noisy-chain-2", v)
        assert all(abs(x - 1) < 0.03 for x in a["cost"].values()), (v, a["cost"])
    costs = [max(analysis.get(f"088-sweep-measurement-error#{i}", "meas-long")["cost"].values()) for i in range(1, 8)]
    assert abs(costs[0] - 1) < 1e-3 and all(b > a for a, b in zip(costs, costs[1:])), costs


def test_scorer_tolerance_follows_the_cost():
    """The scorer's allowance on noisy data is the counts oracle's times the measured cost."""
    c, d = _get("080-noisy-chain-2", "weekly-short")
    _, base = _get("080-noisy-chain-2", "counts-short")
    tm = casemod.truth_model(c, "weekly-short")
    eq = score.equations(c, "weekly", tm, truth_by_time(tm, d["t"])[0], d)
    eq0 = score.equations(c, "counts", tm, truth_by_time(tm, base["t"])[0], base)
    a = analysis.get("080-noisy-chain-2", "weekly-short")
    for p, p0 in zip(eq["parts"], eq0["parts"]):
        assert p["se"] == pytest.approx(p0["se"] * a["cost"][p["key"]], rel=0.02), p["key"]


def test_bias_labels():
    assert analysis.get("081-noisy-link", "bias-short")["label"] == "unidentifiable"         # the link's k times the bias
    assert analysis.get("086-noisy-stepping-inflow", "bias-short")["label"] == "unidentifiable"   # the inflow times the bias
    assert analysis.get("080-noisy-chain-2", "bias-long")["label"] == "achievable"           # the move's conservation pins the bias


@pytest.mark.parametrize("cid", NOISY)
def test_truth_passes_its_own_scoring(cid):
    c = casemod.load(cid)
    for v in c["variants"]:
        if not v.get("observe"):
            continue
        tm = casemod.truth_model(c, v["name"])
        d = data.load(c, v["name"])
        eq = score.equations(c, v["noise"], tm, truth_by_time(tm, d["t"])[0], d)
        assert eq["status"] == "pass", (cid, v["name"], [p for p in eq["parts"] if not p["ok"]])


@pytest.mark.parametrize("cid", ["080-noisy-chain-2", "081-noisy-link", "083-noisy-goal-gap", "085-noisy-hidden-stock", "086-noisy-stepping-inflow"])
def test_truth_refitted_passes_where_achievable(cid):
    """The truth's own structure fitted to the noisy data (the Kalman likelihood) passes in the cells
    the analysis calls achievable (it may fail where it says data-limited or unidentifiable)."""
    c = casemod.load(cid)
    fails = []
    for v in c["variants"]:
        if not v.get("observe") or v["length"] != "short":
            continue
        tm = casemod.truth_model(c, v["name"])
        d = data.load(c, v["name"])
        m = noise_kf.model(d, windows(tm, d["t"]))
        eq = score.equations(c, v["noise"], tm, m.flows_at(m.refit()), d)
        if eq["status"] != "pass" and analysis.get(cid, v["name"])["label"] == "achievable":
            fails.append((v["name"], [(p["key"], p["error"]) for p in eq["parts"] if not p["ok"]], [s["key"] for s in eq["spurious"]]))
    assert len(fails) <= 1, fails                        # p of an achievable cell is >= 0.5, most are near 1
