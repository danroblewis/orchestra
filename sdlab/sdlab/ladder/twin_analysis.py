"""What a real case's twin can deliver: analysis.py's labels (achievable, data-limited,
unidentifiable, not analysed) for the twin as discovery sees it (2026-10-19). The scorer's side;
discovery never sees it.

The twin (real/data.py) is the published model run by the engine **without counting noise**, cut to
the case's training samples (discovery sees the first `train`), with Gaussian **measurement error**
laid on each measured stock (sd = rel x max(level, floor), the case's `real.twin`), and a stock the
data give as a total minus another (`complement`: adoption's N = 100 - A) computed from the other's
noisy level. analysis.py's step-by-step Gaussian (fisher.py: counting noise, every level exact)
describes none of this, so the twin is analysed as an output-error problem:

- **the bound**: the published model's numbers and every stock's starting level (hidden ones too;
  no method sees them) are the unknowns; each training sample of each observed stock is the
  deterministic run's level plus its measurement error. The Fisher information is
  sum_i J_i' R_i^-1 J_i (J_i: the sample's derivative by central differences of the whole run,
  R_i: its error variance). A complement stock's error is the other's, so it adds only that the two
  sum to the total on every sample (an exact observation of the sum). The bound of the numbers is mapped to the scorer's parts (and a flow
  with effects to its amount over the training samples) and compared with the scorer's allowance
  (analysis._allowances on the twin's training data, as real/score.py scores it, noise "counts"),
  joint p by Monte Carlo as in analysis.py;
- **the structure**: a true term is detected with P(|z| > sqrt(log n)), n the observations; a
  same-size alternative (analysis.alternatives) whose run is the truth's is not separable (no
  counting noise to tell a move from a link), and a reader that is an exact linear function of
  other measured stocks on every sample (N = 100 - A) cannot be told from them: either makes the
  cell `unidentifiable`.
"""

from __future__ import annotations

import math

import numpy as np
from scipy.stats import norm

from . import analysis as an
from . import cases as casemod
from .fisher import TruthParams, _effect, _rate, bound
from .parts import ONE, label, parts

ROUND_SD = 1e-4 / math.sqrt(12)        # a level is recorded to 4 decimals


def _simulate(flows: list[dict], ids: list[str], x0: np.ndarray, t: list, injections: list[dict], inputs: dict) -> np.ndarray:
    """The engine without noise (dt 1): stocks x samples, sample 0 the start."""
    idx = {s: i for i, s in enumerate(ids)}
    names = [k for k in inputs if k not in idx]
    for k in names:
        idx[k] = len(idx)
    K = len(t)
    X = np.zeros((len(ids), K))
    X[:, 0] = x0
    inj = {}
    for j in injections or []:
        if j.get("stock") in idx:
            inj.setdefault(j["t"], []).append((idx[j["stock"]], float(j["amount"])))
    x = np.maximum(np.asarray(x0, dtype=float).copy(), 0.0)
    take = {s: [(fi, float(f.get("ratio") or 1)) for fi, f in enumerate(flows) if f.get("from") == s] for s in ids}
    for fi, f in enumerate(flows):
        for u in f.get("uses") or []:
            if u.get("stock") in take and float(u.get("per") or 0) > 0:
                take[u["stock"]].append((fi, float(u["per"])))
    for k in range(1, K):
        for si, a in inj.get(t[k], []):
            x[si] = max(0.0, x[si] + a)
        view = np.concatenate([x, [float(inputs[n][k]) if k < len(inputs[n]) else 0.0 for n in names]])[:, None]
        q = np.zeros(len(flows))
        for fi, f in enumerate(flows):
            segs = f.get("byTime")
            rate = next((g["rate"] for g in segs if g["from"] <= t[k] <= g["to"]), segs[-1]["rate"]) if segs else f.get("rate")
            r = _rate(rate, view, idx, f)[0]
            for e in f.get("effects") or []:
                r *= _effect(e, view, idx)[0]
            q[fi] = r
        for s, tk in take.items():
            want = sum(q[fi] * w for fi, w in tk)
            if want > x[idx[s]] > -1 and want > 0:
                kk = max(0.0, x[idx[s]]) / want
                for fi, _ in tk:
                    q[fi] *= kk
        for fi, f in enumerate(flows):
            if f.get("from") in idx:
                x[idx[f["from"]]] -= q[fi] * float(f.get("ratio") or 1)
            if f.get("to") in idx:
                x[idx[f["to"]]] += q[fi]
            for u in f.get("uses") or []:
                if u.get("stock") in idx and float(u.get("per") or 0) > 0:
                    x[idx[u["stock"]]] -= q[fi] * float(u["per"])
        X[:, k] = x
    return X


def _part_values(tp: TruthParams, theta: np.ndarray, measured: set, inputs: set) -> dict:
    """The scorer's parts per window as numbers ((w, key, sub)), with a hidden part's k_in and delay."""
    fl = tp.flows_at(theta)
    out = {}
    for w, win in enumerate(tp.wins):
        here = [{**{k: v for k, v in f.items() if k != "byTime"},
                 "rate": next((g for g in f["byTime"] if g["from"] <= win[0] <= g["to"]), f["byTime"][-1])["rate"]} for f in fl]
        pw, _ = parts(here, measured, win, inputs)
        for k, v in pw.items():
            if k[0] in ("flow", "uses", "via") and isinstance(v, (int, float)):
                out[(w, k, None)] = float(v)
            elif k[0] == "hidden" and isinstance(v, dict):
                for sub in ("k_in", "delay"):
                    if sub in v and math.isfinite(v[sub]):
                        out[(w, k, sub)] = float(v[sub])
    return out


def analyse(case_id: str, variant: str) -> dict:
    from .real import data as real_data
    case = casemod.load(case_id)
    tm = casemod.truth_model(case, variant)
    d = real_data.load(case, variant)                       # the training samples, with the measurement error
    tw = case["real"]["twin"]
    complement = set(tw.get("complement") or {})
    t = list(d["t"])
    measured = list(d["levels"])
    observed = [s for s in measured if s not in complement]
    out = {"case": case_id, "variant": variant, "noise": "twin (measurement error)", "steps": len(t) - 1, "points": len(t),
           "hash": case["hash"], "code": an.code_hash() + an._tolerance_hash()}
    true_run = {"t": t, "levels": d["all_levels"], "all_levels": d["all_levels"], "injections": d.get("injections") or [],
                **({"inputs": d["inputs"]} if d.get("inputs") else {})}
    tp = TruthParams(tm, true_run, "none")
    notes = ["the twin: the published model without counting noise, its training samples with measurement error; the bound"
             " is the output-error one (the run's levels as functions of the numbers and the starting levels)"]
    if not tp.ok or len(t) < 4 or float(tm.get("dt") or 1) < 1:
        out.update(label="not analysed", p=None, design=[], parts=[], why=[], equivalences=[], notes=notes + ["not analysed: a twin this analysis does not cover"])
        return an._jsonable(out)
    ids = tp.ids
    inputs = dict(d.get("inputs") or {})
    x0 = np.array([float(d["all_levels"][s][0]) for s in ids])
    P = tp.P
    theta = np.concatenate([tp.theta0, x0])
    steps = np.concatenate([tp.dsteps, np.maximum(1e-4, 1e-4 * np.abs(x0))])

    def run(z):
        return _simulate(tp.flows_at(z[:P]), ids, z[P:], t, d.get("injections") or [], inputs)

    base = run(theta)
    oi = [ids.index(s) for s in observed]
    rel, floor = tw.get("rel") or {}, tw.get("floor") or {}
    sd = np.array([np.maximum(float(rel.get(s, 0.0)) * np.maximum(np.abs(base[ids.index(s)]), float(floor.get(s, 0.0))), ROUND_SD) for s in observed])
    # a complement (N = total - A) says only that the two add up to the total on every sample: an
    # observation of their sum, exact to the data's rounding
    comp = [(ids.index(c), ids.index(x["of"])) for c, x in (tw.get("complement") or {}).items() if c in ids and x.get("of") in ids]
    sd = np.vstack([sd] + [np.full((1, len(t)), ROUND_SD) for _ in comp]) if comp else sd

    def seen(X):
        return np.vstack([X[oi]] + [X[[c]] + X[[o]] for c, o in comp]) if comp else X[oi]

    J = np.zeros((len(theta), sd.shape[0], len(t)))
    for p in range(len(theta)):
        a, b = theta.copy(), theta.copy()
        a[p] += steps[p]
        b[p] -= steps[p]
        J[p] = (seen(run(a)) - seen(run(b))) / (2 * steps[p])
    W = J / sd[None]
    fi = np.einsum("pik,qik->pq", W, W)
    # a number the run does not depend on at all (an effect's cap that never binds) is left out of the
    # inverse (unidentified, harmless: nothing scored depends on it); the rest by fisher.bound
    # a linear effect's normal, min and max are left out too: k x level / normal has one number in the
    # run, not two (and a flow with effects is scored as a whole), so keeping both makes an exact null
    lin_eff = {i for i, nm in enumerate(tp.labels) if ".effect(" in nm and nm.rsplit(".", 1)[-1] in ("normal", "min", "max")}
    live = np.array([i for i in np.flatnonzero(np.diag(fi) > 0) if i not in lin_eff], dtype=int)
    C = np.zeros_like(fi)
    Cl, nl = bound(fi[np.ix_(live, live)])
    C[np.ix_(live, live)] = Cl
    dead = [i for i in range(len(theta)) if i not in set(live) and i not in lin_eff]
    cols = [np.eye(len(theta))[:, i] for i in dead]
    if nl.size:
        for j in range(nl.shape[1]):
            v = np.zeros(len(theta))
            v[live] = nl[:, j]
            cols.append(v)
    null = np.array(cols).T if cols else np.zeros((len(theta), 0))
    Cr = C[:P, :P]
    null_r = null[:P]
    out["parameters"] = [{"name": nm, "true": float(th), "crb_se": float(math.sqrt(max(C[i, i], 0.0))),
                          "unidentified": bool(null.size and np.abs(null[i]).max() > 1e-3)} for i, (nm, th) in enumerate(zip(tp.labels, tp.theta0))]
    al = an._allowances(case, "counts", tm, d)
    mset, iset = set(measured), set(inputs) - set(d["all_levels"])
    keys_vals = _part_values(tp, tp.theta0, mset, iset)
    keys = list(keys_vals)
    D = np.zeros((len(keys), P))
    for p in range(P):
        a, b = tp.theta0.copy(), tp.theta0.copy()
        a[p] += tp.dsteps[p]
        b[p] -= tp.dsteps[p]
        va, vb = _part_values(tp, a, mset, iset), _part_values(tp, b, mset, iset)
        D[:, p] = [(va.get(k, 0.0) - vb.get(k, 0.0)) / (2 * tp.dsteps[p]) for k in keys]
    vals = np.array([keys_vals[k] for k in keys])
    Cp = D @ Cr @ D.T
    sc = np.maximum(np.abs(vals), 1e-9)
    p_null = (np.abs(D @ null_r).max(axis=1) / sc if null.size else np.zeros(len(keys))) > 1e-6
    effect_ends = set(al["effect_ends"])
    unident, why, part_rows = [], [], []
    crit = math.sqrt(math.log(max(len(oi) * len(t), 3)))
    structure_p, structure_bad = 1.0, []
    for i, (w, k, sub) in enumerate(keys):
        if (k[1], k[2]) in effect_ends and k[0] in ("flow", "uses"):
            continue
        allowed = al["allowed"].get((w, k) if sub is None else (w, k, sub))
        if allowed is None:
            continue
        se = math.inf if p_null[i] else math.sqrt(max(Cp[i, i], 0.0))
        name = label(k) + (f" {sub}" if sub else "")
        r = {"part": name, "window": w, "true": float(vals[i]), "crb_se": an._fin(se), "allowed": allowed,
             "oracle_se": al["oracle_se"].get((w, k) if sub is None else (w, k, sub)), "p": an._p_within(allowed, se), "source": "output error (twin)"}
        if p_null[i]:
            r["unidentified"] = True
            unident.append(f"{name}: only a combination with other numbers shows in the data")
        elif k[0] in ("flow", "via") and abs(vals[i]) > 0:
            z = abs(vals[i]) / se if se > 0 else math.inf
            pd = 1.0 if math.isinf(z) else float(norm.cdf(z - crit) + norm.cdf(-z - crit))
            structure_p *= pd
            if z < crit:
                structure_bad.append(f"{name} (z {z:.2g} < {crit:.2g})")
        part_rows.append((r, D[i]))
    effect_rows = []
    for ends in al["effect_ends"]:
        sel = [fi for fi, f in enumerate(tp.flows) if ((f.get("from") if f.get("from") in mset else None),
                                                       (f.get("to") if f.get("to") in mset else None)) == ends]
        amt = lambda z: tp.rates(z, cap=False)[sel].sum(axis=0)  # noqa: E731
        b0 = amt(tp.theta0)
        G = np.zeros((tp.K, P))
        for p in range(P):
            a, b = tp.theta0.copy(), tp.theta0.copy()
            a[p] += tp.dsteps[p]
            b[p] -= tp.dsteps[p]
            G[:, p] = (amt(a) - amt(b)) / (2 * tp.dsteps[p])
        rms = float(np.sqrt(np.mean(b0 ** 2))) or 1e-9
        e_rms = float(np.sqrt(max(np.einsum("kp,pq,kq->", G, Cr, G) / len(b0), 0.0)) / rms)
        bad = bool(null.size and (np.abs(G @ null_r).max() / rms) > 1e-6)
        effect_rows.append({"ends": [e or "outside" for e in ends], "rel_rms_se": e_rms, "allowed": al["tol"]["rel"], "unidentified": bad, "G": G, "rms": rms})
        if bad:
            unident.append(f"the flow {ends[0] or 'outside'} -> {ends[1] or 'outside'} (with effects): its amount is not pinned down")
    p_numbers, per_effect = an._joint(part_rows, effect_rows, Cr)
    for e, pe in zip(effect_rows, per_effect):
        e["p"] = pe
    # the structure: readers that are exact functions of other measured stocks, and alternatives with the same run
    equivalences = []
    L = np.array([np.asarray(d["levels"][s], dtype=float) for s in measured])
    A = np.vstack([np.ones(len(t)), L]).T
    norms = np.linalg.norm(A, axis=0)
    norms[norms == 0] = 1.0
    sv, V = np.linalg.svd(A / norms, full_matrices=False)[1:]
    read = {k[3] for _, k, _ in keys if k[0] in ("flow", "via")} | {e.get("stock") for f in tm["flows"] for e in f.get("effects") or []}
    for e, vec in zip(sv, V):
        if e < 1e-4 * sv.max():                              # exact to the data's 4 decimals
            cols = [c for c, x in zip([ONE] + measured, vec) if abs(x) > 1e-6]
            text = f"{' ~ '.join(cols)} are exactly collinear on every training sample (e.g. a stock given as a total minus another)"
            equivalences.append(text)
            if len(set(cols) & read) and len(cols) > 1:
                unident.append(f"structure: {text}: a rate may read either")
    for text, alt in an.alternatives(tm, mset):
        try:
            tpa = TruthParams(alt, true_run, "none")
            if not tpa.ok:
                continue
            xa = _simulate(tpa.flows_at(tpa.theta0), tpa.ids, np.array([float(d["all_levels"][s][0]) for s in tpa.ids]), t,
                           d.get("injections") or [], inputs)
        except (ValueError, KeyError, IndexError):
            continue
        same = all(np.allclose(xa[tpa.ids.index(s)], base[ids.index(s)], rtol=1e-9, atol=1e-6) for s in observed)
        if same:
            unident.append(f"structure: {text}: the same run (no counting noise to tell them apart)")
            equivalences.append(f"{text}: the same levels")
    out["design"] = []
    out["parts"] = [r for r, _ in part_rows]
    out["effects"] = [{k: v for k, v in e.items() if k not in ("G", "rms")} for e in effect_rows]
    out["structure_p"] = structure_p
    out["numbers_p"] = p_numbers
    out["p"] = p_numbers * structure_p
    if unident:
        lab, out["p"] = "unidentifiable", 0.0
    elif out["p"] < an.ACHIEVABLE:
        lab = "data-limited"
        why.append(an._limit_reason(out, structure_bad))
    else:
        lab = "achievable"
    out.update(label=lab, why=unident + [w for w in why if w], equivalences=equivalences, notes=sorted(set(notes)))
    return an._jsonable(out)
