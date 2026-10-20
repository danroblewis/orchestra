"""The NO-TRUTH evidence checks (sdlab/ladder/notruth.py) on synthetic data made here with numpy: the
leakage guard, and that each check supports a right model and flags a wrong one with a diagnosis."""

from __future__ import annotations

import ast
from pathlib import Path

import numpy as np
import pytest

from sdlab.ladder import notruth
from sdlab.ladder.notruth_core import build_grid, leaves, set_leaves

LADDER = Path(__file__).resolve().parents[1] / "sdlab" / "ladder"


def _data(n=600, k=0.2, k2=None, seed=1, meas=0.0, injections=()):
    """One stock x fed by a measured input u (gain 1) and drained at k (k2 from the middle on), counting noise."""
    rng = np.random.default_rng(seed)
    t = list(range(1, n + 1))
    u = 50 + 30 * np.sin(2 * np.pi * np.arange(n) / 60) + 20 * (np.arange(n) % 150 < 40)
    x = np.zeros(n)
    x[0] = 250.0
    inj = {j["t"]: j["amount"] for j in injections}
    for i in range(1, n):
        kk = k2 if (k2 is not None and i >= n // 2) else k
        prev = x[i - 1] + inj.get(t[i], 0.0)
        x[i] = prev + rng.poisson(u[i]) - rng.binomial(int(prev), kk)
    y = x + (rng.normal(0, meas, n) if meas else 0)
    view = {"stocks": [{"id": "x", "unit": "things"}], "t": t, "levels": {"x": y.tolist()}, "inputs": {"u": u.tolist()}}
    if injections:
        view["injections"] = [dict(j, stock="x") for j in injections]
    return view


def _flows(k=0.2, gain=1.0):
    return [{"from": None, "to": "x", "rate": {"form": "linear", "c": 0, "terms": [{"stock": "u", "k": gain}]}},
            {"from": "x", "to": None, "rate": {"form": "proportional", "stock": "x", "k": k}}]


# ---- the guard ----

@pytest.mark.parametrize("key", ["all_levels", "counters", "clean", "observation", "truth", "case", "seed"])
def test_guard_refuses_what_discovery_never_sees(key):
    v = _data(200)
    v[key] = {}
    for fn in (notruth.residuals, notruth.invariance, notruth.heldout):
        with pytest.raises(AssertionError):
            fn(v, _flows())


def test_guard_refuses_hidden_levels():
    v = _data(200)
    v["levels"]["hidden"] = [0.0] * 200
    with pytest.raises(AssertionError):
        notruth.residuals(v, _flows())


def test_notruth_modules_import_nothing_that_reads_the_truth():
    banned = {"cases", "data", "store", "sdtruth", "score", "oracle", "noise", "noise_kf", "noise_oracle", "runner", "realistic",
              "physics", "particles", "skill", "hidden_oracle", "real", "strict", "longrun", "objective_test", "analysis"}
    for name in ("notruth.py", "notruth_core.py", "notruth_kf.py"):
        tree = ast.parse((LADDER / name).read_text())
        for node in ast.walk(tree):
            mods = []
            if isinstance(node, ast.ImportFrom):
                mods = [node.module or ""] + [a.name for a in node.names]
            elif isinstance(node, ast.Import):
                mods = [a.name for a in node.names]
            for m in mods:
                assert not ({p for p in m.split(".")} & banned), f"{name} imports {m}"


# ---- the checks ----

def test_residuals_support_the_right_model_and_diagnose_a_wrong_one():
    v = _data()
    right = notruth.residuals(v, _flows())
    assert right["verdict"] in ("supports", "weak")
    wrong = notruth.residuals(v, _flows(k=0.1, gain=0.6))
    assert wrong["verdict"] == "contradicts"
    assert any(f["verdict"] == "contradicts" and ("input u" in f["test"] or "level x" in f["test"] or "mean" in f["test"])
               for f in wrong["findings"])
    assert all(f.get("diagnosis") for f in wrong["findings"])


def test_residuals_whiten_report_noise():
    v = _data(meas=8.0, seed=3)
    r = notruth.residuals(v, _flows())
    assert r["how"].startswith("kalman")
    assert r["verdict"] != "contradicts", r["findings"]
    assert r["stocks"][0]["R"] > 20                      # it found the report noise (variance 64)


def test_invariance_flags_a_number_that_changes_halfway():
    v = _data(k=0.2, k2=0.4, seed=2)
    r = notruth.invariance(v, _flows(k=0.3))
    assert r["verdict"] == "contradicts"
    assert any("x -> outside" in f["number"] for f in r["findings"])
    ok = notruth.invariance(_data(seed=2), _flows())
    assert ok["verdict"] in ("supports", "weak")


def test_heldout_right_model_beats_persistence():
    r = notruth.heldout(_data(seed=4), _flows())
    assert r["verdict"] == "supports"
    assert r["horizons"]["20"]["held_out"][0]["skill"] > 0.3


def test_agreement_tells_duplicates_neighbours_and_strangers_apart():
    v = _data(seed=5)
    r = notruth.agreement(v, _flows(), {"same": _flows(), "close": _flows(k=0.201), "far": _flows(k=0.05, gain=0.3),
                                        "near": _flows(k=0.2005)})
    assert r["others"]["same"]["duplicate"]
    assert r["others"]["close"]["agree"] and r["others"]["near"]["agree"]
    assert not r["others"]["far"]["agree"]
    assert r["verdict"] == "supports" and r["n_agree"] == 2
    assert abs(r["push_response"]["x"]["x"]["1"] - 0.8) < 1e-6      # a push into x: 80% left after one step at k 0.2
    assert notruth.agreement(v, _flows(), {})["verdict"] == "uninformative"


def test_injections_enter_the_one_step_prediction():
    inj = [{"t": 100 + 50 * i, "amount": 300.0} for i in range(8)]
    v = _data(seed=6, injections=inj)
    assert notruth.residuals(v, _flows())["verdict"] in ("supports", "weak")


def test_evidence_counts_and_score():
    v = _data(seed=7)
    ev = notruth.evidence(v, _flows(), {"a": _flows(k=0.201), "b": _flows(k=0.199)})
    assert set(ev["checks"]) == {"residuals", "invariance", "heldout", "agreement"}
    assert ev["counts"]["contradicts"] == 0
    assert ev["score"] is not None and ev["score"] >= 0.75


def test_leaves_round_trip():
    fl = _flows()
    lv = leaves(fl)
    assert [x.value for x in lv] == [0, 1.0, 0.2]
    out = set_leaves(fl, lv, [0, 2.0, 0.3])
    assert out[0]["rate"]["terms"][0]["k"] == 2.0 and out[1]["rate"]["k"] == 0.3 and fl[1]["rate"]["k"] == 0.2


def test_grid_handles_gaps():
    v = _data(300)
    keep = [i for i in range(300) if i % 3 != 1 or i in (0, 299)]
    v = {**v, "t": [v["t"][i] for i in keep], "levels": {"x": [v["levels"]["x"][i] for i in keep]},
         "inputs": {"u": [v["inputs"]["u"][i] for i in keep]}}
    g = build_grid(v)
    assert len(g.times) == 300 and np.isnan(g.y[0]).sum() == 300 - len(keep)
    assert notruth.residuals(v, _flows())["verdict"] in ("supports", "weak", "uninformative")
