"""A confidence score for a found model, from NO-TRUTH evidence only, trained on ladder cells whose truth
is known (evidence.py's reports).

**Label** (truth side, `label`): a model is *right* when all three hold
- structure: its structure equals the truth's (score.py: every true part found, no spurious part), or the
  scorer calls it equivalent and the likelihood check cannot reject it (noise-free data, where there is no
  likelihood: the bound says the measured stocks' linear system is within the bound);
- pushes: the push test has no mismatch (pushes.py's verdict is "agrees" or "agrees within the data's
  limits": every impulse, step and sine comparison agrees, tolerances widened by the truth's own refits);
- numbers: within the joint bound (consistency.bound_check ok: every z within 3 and the joint chi-square
  p >= 0.01), or the likelihood ratio does not reject it, or (noise-free) the linear system is within the bound.
Reported beside them, not in the label: footprint (the push test finds no missing, spurious or wrong-signed
response; its numbers aside). A component that could not be computed is unknown (None), and then the label is unknown too (even when another
component is False: otherwise cells the consistency check does not cover would add only their wrong models).
Unknown labels are left out of training and counted.

**Features** (NO-TRUTH side, `features`), FEATURES in order:
- residuals, invariance, heldout, agreement: each check's verdict as a number (supports 1, weak 0.5,
  uninformative 0.5, contradicts 0; error 0.5);
- residuals_logp, invariance_logp: -log10 of the smallest Holm-corrected p over the check's tests, capped at 10,
  divided by 10 (0: no sign of a misfit);
- heldout_skill: the worst held-out skill at the main horizon, clipped to [-1, 1] (0 when none);
- agree_share: the share of the other distinct models that agree (0.5 when there are none);
- agree_best: agrees with the best other model (1/0; 0.5 when none).
Nothing else (no status, no score, no case or strategy name, no complexity) goes in.

**Model**: logistic regression (L2, C = 1, standardised inputs), one row per distinct model on a cell
(identical found flows on a cell count once). Cross-validated by case family (GroupKFold over `family`: a
case's cells, and every draw of a parametric case, 045#1..#8, are never in the fold that trains for them). Reports: the label's base rate, out-of-fold AUC, a
reliability table (predicted vs observed, by bins of predicted confidence), Brier score against the base rate's,
the coefficients of the model fitted on everything, each label component on its own (rate, how it splits by
the scorer's pass, and its own out-of-fold AUC from the same features), and the scorer's pass against the label.
"""

from __future__ import annotations

import math

import numpy as np

FEATURES = ("residuals", "invariance", "heldout", "agreement", "residuals_logp", "invariance_logp", "heldout_skill", "agree_share",
            "agree_best")
VERDICT = {"supports": 1.0, "weak": 0.5, "uninformative": 0.5, "contradicts": 0.0, "error": 0.5}
COMPONENTS = ("structure", "pushes", "numbers", "footprint")     # footprint: reported beside the label, not part of it
BINS = (0.0, 0.2, 0.4, 0.6, 0.8, 1.0)
FOLDS = 5
GOOD = ("pass", "equivalent")


# ---- the label (truth side) ----

def _and(xs: list[bool | None]) -> bool | None:
    """True when all are True; None when any is unknown (so a cell no check covers never adds only its wrong
    models to the training set); else False."""
    if any(x is None for x in xs):
        return None
    return all(xs)


def label(rep: dict) -> dict:
    """{right, structure, pushes, numbers, footprint} (True, False or None: unknown) of one evidence report.
    footprint (the push test finds no missing, spurious or wrong-signed response) is reported only."""
    t = rep.get("truth") or {}
    if rep.get("pending") or rep.get("error") or t.get("error"):
        return {"right": None, "structure": None, "pushes": None, "numbers": None, "footprint": None}
    s = rep.get("scores") or {}
    b, lk, p = t.get("bound") or {}, t.get("likelihood") or {}, t.get("pushes") or {}
    lik_ok = None if not lk.get("covered") or "rejected" not in lk else not lk["rejected"]
    entries_ok = b.get("entries_ok") if b.get("noise_free") else None
    # structure
    if s.get("recall") is None:
        st = None
    elif s.get("recall") == 1 and not s.get("spurious"):
        st = True
    elif rep["existing"]["status"] == "equivalent":
        st = lik_ok if lik_ok is not None else entries_ok
    else:
        st = False
    # pushes
    pu = None if p.get("verdict") is None else p["verdict"] != "differs"
    # numbers
    nums = [b.get("ok") if "ok" in b else None, lik_ok, entries_ok]
    nu = True if any(x is True for x in nums) else (False if any(x is False for x in nums) else None)
    return {"right": _and([st, pu, nu]), "structure": st, "pushes": pu, "numbers": nu, "footprint": p.get("footprint_ok")}


# ---- the features (NO-TRUTH side) ----

def _logp(p) -> float:
    if p is None:
        return 0.0
    return min(10.0, -math.log10(max(float(p), 1e-300))) / 10.0


def features(rep: dict) -> list[float] | None:
    """FEATURES of one report, from its NO-TRUTH part only; None when that part, or its agreement, is missing."""
    n = rep.get("notruth")
    if not n:
        return None
    if "agreement" in n and n["agreement"] is None:
        return None        # evidence.reports found no agreement for the cell's current results (changed since the fill): missing, not neutral
    v = [VERDICT.get((n.get(k) or {}).get("verdict"), 0.5) for k in ("residuals", "invariance", "heldout", "agreement")]
    sk = (n.get("heldout") or {}).get("min_skill")
    a = n.get("agreement") or {}
    nd = a.get("n_distinct_others") or 0
    share = (a.get("n_agree") or 0) / nd if nd else 0.5
    best = a.get("agree_with_best")
    return v + [_logp((n.get("residuals") or {}).get("min_p")), _logp((n.get("invariance") or {}).get("min_p")),
                0.0 if sk is None else float(np.clip(sk, -1, 1)), share, 0.5 if best is None else float(best)]


# ---- the model ----

def auc(y: np.ndarray, s: np.ndarray) -> float | None:
    """Area under the ROC curve (ties count half); None with one class only."""
    y, s = np.asarray(y, bool), np.asarray(s, float)
    pos, neg = s[y], s[~y]
    if not len(pos) or not len(neg):
        return None
    from scipy.stats import rankdata
    r = rankdata(np.concatenate([pos, neg]))
    return float((r[:len(pos)].sum() - len(pos) * (len(pos) + 1) / 2) / (len(pos) * len(neg)))


def reliability(y: np.ndarray, p: np.ndarray, bins=BINS) -> list[dict]:
    out = []
    for lo, hi in zip(bins[:-1], bins[1:]):
        m = (p >= lo) & ((p < hi) if hi < bins[-1] else (p <= hi))
        out.append({"bin": f"{lo:.1f}-{hi:.1f}", "n": int(m.sum()), "predicted": float(p[m].mean()) if m.any() else None,
                    "observed": float(y[m].mean()) if m.any() else None})
    return out


def _fit(X: np.ndarray, y: np.ndarray):
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    return make_pipeline(StandardScaler(), LogisticRegression(C=1.0, max_iter=1000)).fit(X, y)


def oof(X: np.ndarray, y: np.ndarray, groups: np.ndarray, folds: int = FOLDS) -> np.ndarray | None:
    """Out-of-fold predicted P(right), grouped by case; a fold whose training part has one class predicts
    that part's base rate. None when there are fewer than 2 groups."""
    from sklearn.model_selection import GroupKFold
    k = min(folds, len(set(groups.tolist())))
    if k < 2:
        return None
    p = np.full(len(y), np.nan)
    for tr, te in GroupKFold(n_splits=k).split(X, y, groups):
        if len(set(y[tr].tolist())) < 2:
            p[te] = float(y[tr].mean())
        else:
            p[te] = _fit(X[tr], y[tr]).predict_proba(X[te])[:, 1]
    return p


def family(case_id: str) -> str:
    """The cross-validation group of a case: a parametric case's draws (NNN-slug#i) share their case file's
    structure and noise, so they are one group; any other case is its own."""
    return str(case_id).split("#", 1)[0]


def dataset(reps: list[dict]) -> dict:
    """Distinct models (one per (case, variant, model key)) with features: {X, groups (case family), cases,
    labels, status, ids}."""
    seen, rows = set(), []
    for r in reps:
        f = features(r)
        if f is None:
            continue
        key = (r["case"], r["variant"], r.get("model") or r["id"])
        if key in seen:
            continue
        seen.add(key)
        rows.append((r, f, label(r)))
    return {"X": np.array([f for _, f, _ in rows], float).reshape(-1, len(FEATURES)),
            "groups": np.array([family(r["case"]) for r, _, _ in rows]), "cases": np.array([r["case"] for r, _, _ in rows]),
            "labels": [lab for _, _, lab in rows], "status": [r["existing"]["status"] for r, _, _ in rows],
            "ids": [r["id"] for r, _, _ in rows]}


def _target(ds: dict, comp: str) -> tuple[np.ndarray, np.ndarray]:
    m = np.array([lab[comp] is not None for lab in ds["labels"]], bool)
    y = np.array([bool(lab[comp]) for lab in ds["labels"]], bool)
    return m, y


def report(reps: list[dict]) -> dict:
    ds = dataset(reps)
    n_all = len(ds["labels"])
    out: dict = {"features": list(FEATURES), "distinct_models": n_all, "cases": len(set(ds["cases"].tolist())),
                 "families": len(set(ds["groups"].tolist()))}
    m, y = _target(ds, "right")
    out["labelled"], out["unknown"] = int(m.sum()), int(n_all - m.sum())
    out["base_rate"] = float(y[m].mean()) if m.any() else None
    X, g, yy = ds["X"][m], ds["groups"][m], y[m]
    st = np.array(ds["status"])[m]
    good = np.isin(st, GOOD)
    out["scorer_vs_label"] = {"pass_right": int((good & yy).sum()), "pass_wrong": int((good & ~yy).sum()),
                              "fail_right": int((~good & yy).sum()), "fail_wrong": int((~good & ~yy).sum())}
    comps = {}
    for comp in COMPONENTS:
        cm, cy = _target(ds, comp)
        cst = np.isin(np.array(ds["status"])[cm], GOOD)
        c = {"known": int(cm.sum()), "rate": float(cy[cm].mean()) if cm.any() else None,
             "rate_scorer_pass": float(cy[cm][cst].mean()) if cst.any() else None,
             "rate_scorer_fail": float(cy[cm][~cst].mean()) if (~cst).any() else None}
        if cm.sum() >= 10 and 0 < cy[cm].sum() < cm.sum():
            p = oof(ds["X"][cm], cy[cm], ds["groups"][cm])
            c["auc"] = None if p is None else auc(cy[cm], p)
        comps[comp] = c
    out["components"] = comps
    if len(yy) < 10 or yy.all() or not yy.any():
        out["note"] = "too few labelled models, or one class only: no model fitted"
        return out
    p = oof(X, yy, g)
    if p is None:
        out["note"] = "one case family only: no grouped cross-validation"
        return out
    out["auc"] = auc(yy, p)
    out["brier"] = float(np.mean((p - yy) ** 2))
    out["brier_base"] = float(np.mean((yy.mean() - yy) ** 2))
    out["reliability"] = reliability(yy.astype(float), p)
    out["auc_scorer_pass"] = auc(yy, good.astype(float))          # for reference: the truth-based pass as a 0/1 score
    out["auc_per_feature"] = {f: auc(yy, X[:, j]) for j, f in enumerate(FEATURES)}
    full = _fit(X, yy)
    lr = full[-1]
    out["coefficients"] = {"intercept": float(lr.intercept_[0]), **{f: float(c) for f, c in zip(FEATURES, lr.coef_[0])}}
    out["scaler"] = {"mean": full[0].mean_.tolist(), "scale": full[0].scale_.tolist()}
    out["oof"] = {int(i): float(q) for i, q in zip(np.array(ds["ids"])[m], p)}
    return out


def predict(model: dict, rep: dict) -> float | None:
    """P(right) of one report from a report()'s fitted coefficients (the model fitted on every labelled model)."""
    f = features(rep)
    if f is None or "coefficients" not in model:
        return None
    x = (np.array(f) - np.array(model["scaler"]["mean"])) / np.array(model["scaler"]["scale"])
    z = model["coefficients"]["intercept"] + float(np.dot([model["coefficients"][k] for k in FEATURES], x))
    return 1.0 / (1.0 + math.exp(-z))


def text(r: dict) -> str:
    def f(x, fmt="{:.2f}"):
        return "-" if x is None else fmt.format(x)
    lines = [f"confidence model: {r['distinct_models']} distinct models on {r['cases']} cases; labelled {r['labelled']}, unknown {r['unknown']};"
             f" base rate of 'right' {f(r['base_rate'], '{:.1%}')}",
             "features (NO-TRUTH only): " + ", ".join(r["features"])]
    sv = r["scorer_vs_label"]
    lines.append(f"scorer pass/equivalent vs label: pass&right {sv['pass_right']}, pass&wrong {sv['pass_wrong']}, fail&right {sv['fail_right']},"
                 f" fail&wrong {sv['fail_wrong']}")
    for c, v in r["components"].items():
        lines.append(f"  component {c:9}: known {v['known']:4}, rate {f(v['rate'], '{:.1%}')}, among scorer passes {f(v['rate_scorer_pass'], '{:.1%}')},"
                     f" among fails {f(v['rate_scorer_fail'], '{:.1%}')}, out-of-fold AUC {f(v.get('auc'))}")
    if r.get("note"):
        lines.append(r["note"])
        return "\n".join(lines)
    lines.append(f"out-of-fold AUC (grouped by case family: {r.get('families')} groups, {FOLDS} folds) {f(r['auc'])}; Brier {f(r['brier'], '{:.3f}')} vs base rate's {f(r['brier_base'], '{:.3f}')};"
                 f" the scorer's pass as a score: AUC {f(r['auc_scorer_pass'])}")
    lines.append("reliability (predicted -> observed):")
    for b in r["reliability"]:
        lines.append(f"  {b['bin']}: n {b['n']:4}  predicted {f(b['predicted'])}  observed {f(b['observed'])}")
    lines.append("single-feature AUC: " + ", ".join(f"{k} {f(v)}" for k, v in r["auc_per_feature"].items()))
    lines.append("coefficients (standardised inputs): " + ", ".join(f"{k} {v:+.2f}" for k, v in r["coefficients"].items()))
    return "\n".join(lines)
