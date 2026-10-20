"""evidence.py and evidence_confidence.py: the label, the NO-TRUTH features, the confidence model's
cross-validation and calibration, the per-cell computation, and the CLI command."""

from __future__ import annotations

import inspect
import json

import numpy as np
import pytest

from sdlab.ladder import evidence as E
from sdlab.ladder import evidence_confidence as C


def _rep(status="pass", recall=1.0, spurious=(), verdict="agrees", footprint=True, bound_ok=True, lik=None, noise_free=False,
         entries_ok=None, nt=None, case="c1", model="m", id=1):
    t = {"pushes": {"verdict": verdict, "footprint_ok": footprint},
         "bound": {"ok": bound_ok, "noise_free": noise_free, "entries_ok": entries_ok},
         "likelihood": None if lik is None else {"covered": True, "rejected": lik == "rejected"}}
    nt = nt or {"residuals": {"verdict": "supports", "min_p": 0.5}, "invariance": {"verdict": "supports", "min_p": 0.5},
                "heldout": {"verdict": "supports", "min_skill": 0.8},
                "agreement": {"verdict": "supports", "n_distinct_others": 4, "n_agree": 2, "agree_with_best": True}}
    return {"id": id, "case": case, "variant": "v", "strategy": "s", "model": model, "existing": {"status": status},
            "scores": {"recall": recall, "spurious": list(spurious)}, "truth": t, "notruth": nt}


def test_label_right_needs_all_three():
    assert C.label(_rep())["right"] is True
    assert C.label(_rep(verdict="agrees within the data's limits"))["right"] is True
    assert C.label(_rep(verdict="differs")) == {"right": False, "structure": True, "pushes": False, "numbers": True, "footprint": True}
    assert C.label(_rep(recall=0.5))["structure"] is False
    assert C.label(_rep(spurious=[{"key": "x"}]))["right"] is False


def test_label_numbers_bound_or_likelihood():
    assert C.label(_rep(bound_ok=False, lik="cannot tell"))["numbers"] is True       # outside the bound, likelihood does not reject
    assert C.label(_rep(bound_ok=False, lik="rejected"))["numbers"] is False
    assert C.label(_rep(bound_ok=False))["numbers"] is False
    assert C.label(_rep(bound_ok=False, noise_free=True, entries_ok=True))["numbers"] is True


def test_label_equivalent_needs_the_likelihood():
    assert C.label(_rep(status="equivalent", recall=0.5, bound_ok=False, lik="cannot tell"))["structure"] is True
    assert C.label(_rep(status="equivalent", recall=0.5, bound_ok=False, lik="rejected"))["structure"] is False
    r = _rep(status="equivalent", recall=0.5)
    r["truth"]["likelihood"] = None                                                       # not covered: unknown
    assert C.label(r)["structure"] is None and C.label(r)["right"] is None
    assert C.label({**_rep(), "truth": {"error": "no truth"}})["right"] is None
    r = _rep(verdict="differs", bound_ok=None)
    r["truth"]["bound"] = {"covered": False}                                              # numbers unknown: the label is unknown
    assert C.label(r)["pushes"] is False and C.label(r)["numbers"] is None and C.label(r)["right"] is None


def test_features_read_only_the_notruth_part():
    a = _rep()
    b = _rep(status="fail", recall=0.0, verdict="differs", bound_ok=False, lik="rejected", case="other", model="z", id=9)
    assert C.features(a) == C.features(b)
    assert len(C.features(a)) == len(C.FEATURES)
    nt = {"residuals": {"verdict": "contradicts", "min_p": 1e-20}, "agreement": {"verdict": "uninformative", "n_distinct_others": 0}}
    f = dict(zip(C.FEATURES, C.features(_rep(nt=nt))))
    assert f["residuals"] == 0.0 and f["residuals_logp"] == 1.0 and f["agree_share"] == 0.5 and f["agree_best"] == 0.5
    assert C.features({**a, "notruth": None}) is None
    src = inspect.getsource(C.features)
    for word in ("\"truth\"", "scores", "existing", "status", "case"):
        assert word not in src


def test_auc_and_reliability():
    assert C.auc([1, 1, 0, 0], [0.9, 0.8, 0.2, 0.1]) == 1.0
    assert C.auc([1, 0], [0.5, 0.5]) == 0.5
    assert C.auc([1, 1], [0.1, 0.2]) is None
    rel = C.reliability(np.array([1.0, 0, 1, 1]), np.array([0.1, 0.1, 0.9, 0.95]))
    assert sum(b["n"] for b in rel) == 4 and rel[0]["observed"] == 0.5 and rel[-1]["observed"] == 1.0


def test_oof_never_trains_on_the_case_it_predicts(monkeypatch):
    seen = []
    real = C._fit

    def spy(X, y):
        seen.append({tuple(x) for x in X})
        return real(X, y)
    monkeypatch.setattr(C, "_fit", spy)
    rng = np.random.default_rng(0)
    groups = np.repeat([f"c{i}" for i in range(6)], 10)
    X = np.column_stack([np.repeat(np.arange(6), 10) + 0.01 * rng.normal(size=60), rng.normal(size=60)])   # column 0 names the case
    y = rng.random(60) < 0.5
    p = C.oof(X, y, groups)
    assert not np.isnan(p).any()
    for train in seen:
        cases = {int(round(x[0])) for x in train}
        assert len(cases) < 6                                   # every fit left at least one case out
    assert C.oof(X, y, np.array(["one"] * 60)) is None


def test_cross_validation_groups_draws_of_a_parametric_case_together(monkeypatch):
    """045#1..#8 share their case file's structure: no fold may train on one draw and predict another."""
    assert C.family("045-random-link#3") == C.family("045-random-link#7") == "045-random-link"
    assert C.family("011-link") == "011-link"
    seen = []
    real = C.oof

    def spy(X, y, groups, folds=C.FOLDS):
        seen.append(groups)
        return real(X, y, groups, folds)
    monkeypatch.setattr(C, "oof", spy)
    rng = np.random.default_rng(2)
    reps = [_rep(verdict="agrees" if i % 2 else "differs", case=f"0{40 + i % 6}-fam#{1 + i % 4}", model=f"m{i}", id=i,
                 nt={"residuals": {"verdict": "supports" if i % 2 else "contradicts", "min_p": float(rng.random())}})
            for i in range(96)]
    r = C.report(reps)
    assert r["cases"] == 12 and r["families"] == 6
    assert seen and all(set(g.tolist()) <= {f"0{40 + k}-fam" for k in range(6)} for g in seen)


def test_missing_agreement_is_missing_not_neutral():
    """evidence.reports sets agreement None when the cell changed since the fill: no features, not 0.5s."""
    nt = {"residuals": {"verdict": "supports", "min_p": 0.5}, "agreement": None}
    assert C.features(_rep(nt=nt)) is None
    assert C.dataset([_rep(nt=nt)])["X"].shape == (0, len(C.FEATURES))


def test_report_learns_an_informative_feature():
    rng = np.random.default_rng(1)
    reps = []
    for i in range(80):
        right = bool(rng.random() < 0.5)
        v = "supports" if (right if rng.random() < 0.9 else not right) else "contradicts"
        nt = {"residuals": {"verdict": v, "min_p": 0.5}}
        reps.append(_rep(verdict="agrees" if right else "differs", nt=nt, case=f"c{i % 8}", model=f"m{i}", id=i))
    reps.append({**reps[0], "id": 999})                         # the same model on the same cell counts once
    r = C.report(reps)
    assert r["distinct_models"] == 80 and r["labelled"] == 80 and r["cases"] == 8
    assert 0.3 < r["base_rate"] < 0.7
    assert r["auc"] > 0.8 and r["brier"] < r["brier_base"]
    assert sum(b["n"] for b in r["reliability"]) == 80
    assert r["components"]["pushes"]["rate"] == r["base_rate"]
    assert 0 <= C.predict(r, reps[0]) <= 1
    assert "AUC" in C.text(r)


def test_best_others_skip_self_and_duplicates():
    own = {"a": {"notruth_score3": 1.0}, "b": {"notruth_score3": 0.5}, "c": {"notruth_score3": 1.0}}
    key_of = {"s1": "a", "s2": "a", "s3": "b", "s4": "c", "s5": "c"}
    assert E.best_others(own, key_of, "s1") == ["s4", "s3"]
    assert E.best_others(own, key_of, "s3") == ["s1", "s4"]


def test_not_in_the_score_hash():
    from sdlab.ladder import score
    assert "evidence" not in inspect.getsource(score.score_hash)


def test_compute_cell_on_the_truth():
    """The truth handed in as a found model: the push test agrees, the bound holds, the NO-TRUTH checks run."""
    from sdlab.ladder import cases as casemod
    from sdlab.ladder import data
    from sdlab.skill import truth_by_time
    cid, var = "002-inflow-outflow", "counts-short"
    c = casemod.load(cid)
    d = data.load(c, var)
    flows = truth_by_time(casemod.truth_model(c, var), d["t"])[0]
    raw = json.dumps(flows)
    out = E.compute_cell(cid, var, [(1, "x", raw), (2, "y", raw)], {}, {1, 2}, {1}, "ctx", reference=1)
    own = {i: v for i, p, _, v in out if p == "own"}
    assert set(own) == {1, 2} and own[1]["model"] == own[2]["model"]
    t = own[1]["truth"]
    assert t["pushes"]["verdict"] in ("agrees", "agrees within the data's limits") and t["pushes"]["footprint_ok"]
    assert t["bound"]["ok"]
    assert set(own[1]["notruth"]) == set(E.OWN_CHECKS)
    agr = [v for i, p, _, v in out if p == "agreement"]
    assert len(agr) == 1 and agr[0]["best_other"] is None       # the only other model is the same model


def test_cli_registers_evidence():
    from sdlab.ladder import cli
    with pytest.raises(SystemExit) as e:
        cli.main(["evidence", "--help"])
    assert e.value.code == 0
