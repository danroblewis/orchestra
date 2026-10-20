"""What a noisy variant's data (noise.py) can deliver: analysis.py's labels (achievable,
data-limited, unidentifiable, not analysed) for meas, gaps, weekly, lag, outliers and bias, with the
Kalman model of the truth (noise_kf.py) in place of the step-by-step Gaussian of fisher.py, which
assumes every step is seen, exactly and on time. The scorer's side; discovery never sees it.

- **design**: is each true term distinguishable from the alternatives? Every measured stock's row
  (a constant, one per window where the truth's changes, and every measured level) is a free number
  in one joint Kalman model; a term's z = |true| / SE there, detected with P(|z_hat| > sqrt(log n))
  (n: the points reported). Not for a truth with a hidden stock (as in analysis.py).
- **alternatives**: the same-size structures with the same means (analysis.alternatives), told
  apart only by the counting noise's covariance, now seen through the reporting: P(the likelihood
  prefers the truth) = Phi(sqrt(D / 2)) with D the KL divergence of the reported data, from the
  Kalman filters of both (noise_kf.SSM.kl).
- **the bound**: the Kalman model's SE of every scored part (the information in the means; the
  counting noise's variance is held at the truth, so this is at or above the full Cramer-Rao
  bound), against the scorer's allowance (whose oracle SE is the counts oracle's times the noise's
  measured cost, noise_oracle.py). A part along a direction the data say nothing about (a bias
  times the number it multiplies) makes the cell unidentifiable. `cost` gives each part's SE on the
  reported data over its SE on the clean run (1: the noise costs nothing).

analyse(case_id, variant) -> the same fields as analysis.analyse.
"""

from __future__ import annotations

import hashlib
import math
from pathlib import Path

import numpy as np
from scipy.stats import norm

from . import analysis as an
from . import cases as casemod
from . import data as datamod
from . import noise_kf
from .noise_oracle import clean_view
from .parts import ONE, label, windows
from ..skill import truth_by_time

HERE = Path(__file__).resolve().parent


def code_hash() -> str:
    h = hashlib.sha256()
    for name in ("noise_analysis.py", "noise_kf.py", "noise_oracle.py", "noise.py"):
        h.update((HERE / name).read_bytes())
    return h.hexdigest()[:8]


def design(m: noise_kf.SSM, n_points: int) -> list[dict]:
    """Each measured row free in one joint model: SE, z and the chance to detect each true term."""
    if m.hidden:
        return []
    truth = m.entry_values(m.theta0)
    W = len(m.wins)
    rows = []
    extras, where = [], []
    for r in m.measured:
        us = [truth.get((w, r, ONE), 0.0) for w in range(W)]
        if any(abs(x - us[0]) > 1e-12 for x in us):
            for w, (a, b) in enumerate(m.wins):
                extras.append(({r: 1.0}, ONE, w))
                where.append((r, f"1 [{a}-{b}]", us[w]))
        else:
            extras.append(({r: 1.0}, ONE, None))
            where.append((r, "1", us[0]))
        for c in m.measured + m.inputs:                  # measured inputs: columns as the levels are
            extras.append(({r: 1.0}, c, None))
            where.append((r, c, float(np.mean([truth.get((w, r, c), 0.0) for w in range(W)]))))
    fi = m.fisher(extras, leaves=[])                 # the rows as reported (a bias is part of its row's numbers here)
    k = 0
    C, null = noise_kf.bound(fi)
    crit = math.sqrt(math.log(max(n_points, 3)))
    for r in m.measured:
        sel = [i for i, (rr, _, _) in enumerate(where) if rr == r]
        cols = [where[i][1] for i in sel]
        G = fi[np.ix_([k + i for i in sel], [k + i for i in sel])]
        d = np.sqrt(np.maximum(np.diag(G), 1e-300))
        Gs = G / np.outer(d, d)
        ev, V = np.linalg.eigh((Gs + Gs.T) / 2)
        cond = float(min(1e16, math.sqrt(ev.max() / max(ev.min(), 1e-300)))) if len(ev) else 1.0
        collinear = []
        for e, vec in zip(ev, V.T):
            rel = math.sqrt(max(e, 0.0) / ev.max())
            if rel < 1e-3:
                part = [(cols[j], round(float(vec[j]), 3)) for j in np.argsort(-np.abs(vec)) if abs(vec[j]) > 0.15]
                collinear.append({"columns": [p[0] for p in part], "weights": [p[1] for p in part], "relative_size": rel, "exact": rel < 1e-7})
        terms = []
        for i in sel:
            _, c, true = where[i]
            if abs(true) < 1e-12:
                continue
            j = k + i
            blind = null.size and np.abs(null[j]).max() > 1e-3
            se = math.inf if blind else math.sqrt(max(C[j, j], 0.0))
            z = abs(true) / se if se > 0 else math.inf
            p = 1.0 if math.isinf(z) else float(norm.cdf(z - crit) + norm.cdf(-z - crit))
            terms.append({"column": c, "true": float(true), "se_full": an._fin(se), "z": an._fin(z), "p_detect": p})
        rows.append({"stock": r, "columns": cols, "rank": int((ev > ev.max() * 1e-14).sum()), "of": len(cols), "cond": cond,
                     "collinear": collinear, "terms": terms, "threshold": crit, "steps": n_points})
    return rows


def analyse(case_id: str, variant: str) -> dict:
    case = casemod.load(case_id)
    v = casemod.variant(case, variant)
    noise = v["noise"]
    tm = casemod.truth_model(case, variant)
    d = datamod.load(case, variant)
    out = {"case": case_id, "variant": variant, "noise": noise, "observe": v["observe"], "steps": v["steps"], "points": len(d["t"]),
           "hash": case["hash"], "code": an.code_hash() + an._tolerance_hash() + code_hash()}
    wins = windows(tm, d["t"])
    m = noise_kf.model(d, wins)
    notes, why, unident = [], [], []
    equivalences = an._equivalences(case, tm)
    if m is None:
        out.update(label="not analysed", p=None, design=[], parts=[], why=[], equivalences=equivalences,
                   notes=["not analysed: a truth the Kalman model does not cover (effects, co-flows or a form that is not linear)"])
        return an._jsonable(out)
    mc = noise_kf.model(clean_view(d), wins)
    al = an._allowances(case, noise, tm, d)
    out["design"] = design(m, len(d["t"]))
    structure_p, structure_bad = 1.0, []
    for row in out["design"]:
        for term in row["terms"]:
            if term["column"].startswith("1 ["):
                continue
            structure_p *= term["p_detect"]
            if term["z"] is None or term["z"] < row["threshold"]:
                structure_bad.append(f"{row['stock']} <- {term['column']} (z {term['z'] or 0:.2g} < {row['threshold']:.2g})")
        for g in row["collinear"]:
            text = f"{' ~ '.join(sorted(g['columns']))} are {'exactly ' if g['exact'] else 'nearly '}collinear on this run (each row may read any of them)"
            if text not in equivalences:
                equivalences.append(text)
    for text, alt in an.alternatives(tm, set(d["levels"])):
        D = m.kl(truth_by_time(alt, d["clean"]["t"])[0])
        if D is None:
            continue
        p_alt = float(norm.cdf(math.sqrt(max(D, 0.0) / 2)))
        structure_p *= p_alt
        if p_alt < 0.75:
            structure_bad.append(f"{text} (told apart by the noise with p {p_alt:.2f})")
        equivalences.append(f"{text}: the same mean change of every stock; told apart only by the noise (P(the likelihood prefers the truth) {p_alt:.2f})")
    C, null = m.bound()
    out["parameters"] = [{"name": n, "true": float(th), "se_kalman": float(math.sqrt(max(C[i, i], 0.0))),
                          "unidentified": bool(null.size and np.abs(null[i]).max() > 1e-3)} for i, (n, th) in enumerate(zip(m.labels, m.theta0))]
    keys, vals, D = m.jacobian(m.part_values)
    Cp = D @ C @ D.T
    scale = np.maximum(np.abs(vals), 1e-9)
    p_null = (np.abs(D @ null).max(axis=1) / scale if null.size else np.zeros(len(keys))) > 1e-6
    cost = {}
    if mc is not None:
        Cc, _ = mc.bound()
        kc, _, Dc = mc.jacobian(mc.part_values)
        ic = {k: i for i, k in enumerate(kc)}
    part_rows = []
    for i, (w, k, sub) in enumerate(keys):
        allowed = al["allowed"].get((w, k) if sub is None else (w, k, sub))
        if allowed is None:
            continue
        se = math.inf if p_null[i] else math.sqrt(max(Cp[i, i], 0.0))
        name = label(k) + (f" {sub}" if sub else "")
        r = {"part": name, "window": w, "true": float(vals[i]), "crb_se": an._fin(se), "allowed": allowed,
             "oracle_se": al["oracle_se"].get((w, k) if sub is None else (w, k, sub)), "p": an._p_within(allowed, se), "source": "Kalman (reported data)"}
        if mc is not None and (w, k, sub) in ic and not p_null[i]:
            g = Dc[ic[(w, k, sub)]]
            sc = math.sqrt(max(float(g @ Cc @ g), 0.0))
            if sc > 0:
                r["cost"] = se / sc
                cost.setdefault(name, round(se / sc, 3))
        if p_null[i]:
            r["unidentified"] = True
            unident.append(f"{name}: only a combination with other numbers shows in the data"
                           + (" (the bias multiplies it)" if v["observe"]["kind"] == "bias" else ""))
        part_rows.append((r, D[i]))
    p_numbers, _ = an._joint(part_rows, [], C)
    out["parts"] = [r for r, _ in part_rows]
    out["cost"] = cost
    out["effects"] = []
    kind = v["observe"]["kind"]
    if kind == "outliers":
        notes.append("the outliers are left out of the bound (a robust method can find a few gross errors)")
    if kind == "lag":
        notes.append("the bound knows the lag; announced eras and injections are stamped at their true time, the levels later")
    notes.append("the bound is the Kalman filter's on the reported data, from the means (the counting noise's variance held at the truth)")
    mirror = an._mirror(case)
    if mirror:
        equivalences.append(mirror)
        notes.append("the hidden stock's mirror is told apart only through the counting noise")
    out["structure_p"] = structure_p
    out["numbers_p"] = p_numbers
    out["p"] = p_numbers * structure_p
    if unident:
        lab = "unidentifiable"
        out["p"] = 0.0
    elif out["p"] < an.ACHIEVABLE:
        lab = "data-limited"
        why.append(an._limit_reason(out, structure_bad))
    else:
        lab = "achievable"
    out.update(label=lab, why=unident + [w for w in why if w], equivalences=equivalences, notes=sorted(set(notes)))
    return an._jsonable(out)
