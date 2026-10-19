"""What a case's data can and cannot deliver, from the mathematics: the scorer's side of a case and
variant (computed from the TRUE model and the run; discovery never sees it). A failure is then
diagnosed as the method's fault (the data could deliver it) or the data's limit.

    analyse(case_id, variant) -> {label, p, design, parameters, parts, equivalences, notes, ...}

**Identifiability of the structure from levels** (design): each measured stock's change regressed
on everything a method could put in its row (a constant per window where the truth's constant
changes, and every measured level), weighted by the change's true noise variance. Per stock: the
condition number of the (column-normalised) design, its rank, the (near-)collinear columns, and
for each true term its standard error in that full regression and z = |true| / SE. A term with
z below sqrt(log n) (the BIC price of a column) cannot be told from the alternatives; its chance to
be detected is P(|z_hat| > sqrt(log n)).

**The best achievable accuracy** (fisher.py): the Cramér-Rao bound of the true structure's numbers
under the variant's noise (counting noise: each flow Poisson around its rate; none: the data's
rounding to 4 decimals, so "exact if identifiable"), mapped to the scorer's parts per window, and
for a flow with effects to its amount over the run (compared as a whole by the scorer). A part is
"achievable with probability p" = P(an estimator at the bound lands within the scorer's tolerance
for it) = 2 Phi(allowed / SE) - 1; the case's p is the joint chance (Monte Carlo from the bound's
normal) times the chance every true term is detected.

**Labels:**

- `unidentifiable`: only an equivalent model is possible: a scored number lies along a direction
  the data say nothing about (births and deaths), or a true term is collinear with others to the
  data's precision (identical stocks without noise), or a hidden stock's mirror;
- `data-limited`: identifiable, but even at the bound the scorer's tolerance is met with p < 0.5;
- `achievable`: p >= 0.5;
- `not analysed`: a truth the analysis does not cover.

A truth with a hidden stock uses the hidden oracle's ML standard errors (hidden_oracle.py) in
place of the bound. Results are cached per case hash and variant in $SDLAB_LADDER_CACHE/analysis.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path

import numpy as np
from scipy.stats import norm

from . import cases as casemod
from . import data as datamod
from . import score as scoremod
from .fisher import COUNT_VAR, ROUND_VAR, TruthParams, amounts_jacobian, bound, part_map
from .hidden_oracle import HiddenOracle
from .oracle import Oracle
from .parts import ONE, label, linear_system, parts, windows

ACHIEVABLE = 0.5                 # p at or above: achievable
DRAWS = 4000                     # Monte Carlo draws for the joint p
HERE = Path(__file__).resolve().parent
LABELS = ("achievable", "data-limited", "unidentifiable", "not analysed")


def code_hash() -> str:
    h = hashlib.sha256()
    for name in ("analysis.py", "fisher.py", "parts.py", "oracle.py", "hidden_oracle.py"):
        h.update((HERE / name).read_bytes())
    return h.hexdigest()[:12]


def _tolerance_hash() -> str:
    """What the scorer allows (its defaults and tolerance code), so a scorer change refreshes p."""
    import inspect
    src = inspect.getsource(scoremod._tolerances) + inspect.getsource(scoremod._close) + json.dumps(scoremod.DEFAULTS, sort_keys=True)
    return hashlib.sha256(src.encode()).hexdigest()[:8]


# ---- the design: is the true structure distinguishable from the alternatives? ----

def design(truth_model: dict, d: dict, noise: str, tp: TruthParams | None) -> list[dict]:
    ids = list(d["levels"])
    t = d["t"]
    lv = np.array([np.asarray(d["levels"][s], dtype=float) for s in ids])
    inj = np.zeros_like(lv)
    tindex = {v: i for i, v in enumerate(t)}
    for j in d.get("injections") or []:
        if j.get("stock") in ids and j["t"] in tindex:
            inj[ids.index(j["stock"]), tindex[j["t"]]] += float(j["amount"])
    prev, dy = lv[:, :-1] + inj[:, 1:], np.diff(lv, axis=1) - inj[:, 1:]
    n = dy.shape[1]
    steps = np.asarray(t[1:])
    wins = windows(truth_model, t)
    from ..skill import truth_by_time
    flows, _ = truth_by_time(truth_model, t)
    systems = [linear_system(flows, ids, w) for w in wins]
    linear = all(s is not None for s in systems)
    var = None
    if tp is not None and tp.ok:
        _, Sig = tp.mean_var(tp.theta0)
        var = np.array([Sig[:, i, i] for i in range(len(ids))])
    crit = math.sqrt(math.log(max(n, 3)))
    out = []
    for i, s in enumerate(ids):
        # the constant: one column per window where the truth's constant for this stock changes
        cols, X = [], []
        u = [sys_[1][i] for sys_ in systems] if linear else [0.0]
        if linear and any(abs(x - u[0]) > 1e-12 for x in u):
            for w, (a, b) in enumerate(wins):
                m = (steps >= a) & (steps <= b)
                cols.append(f"1 [{a}-{b}]")
                X.append(m.astype(float))
        else:
            cols.append("1")
            X.append(np.ones(n))
        for j in ids:
            cols.append(j)
            X.append(prev[ids.index(j)])
        X = np.array(X).T
        y = dy[i]
        if var is not None:
            wt = 1.0 / np.maximum(var[i], 1e-12)
        elif noise == "none":
            wt = np.full(n, 1.0 / ROUND_VAR)
        else:                                                         # no variance model: the residual's
            beta, *_ = np.linalg.lstsq(X, y, rcond=None)
            wt = np.full(n, 1.0 / max(COUNT_VAR, float(np.var(y - X @ beta))))
        Xw = X * np.sqrt(wt)[:, None]
        norms = np.linalg.norm(Xw, axis=0)
        live = norms > 0
        Xs = Xw[:, live] / norms[live]
        sv = np.linalg.svd(Xs, compute_uv=False)
        G = Xs.T @ Xs
        ev, V = np.linalg.eigh(G)
        cond = float(min(1e16, math.sqrt(ev.max() / max(ev.min(), 1e-300)))) if len(ev) else 1.0
        rank = int((sv > sv.max() * 1e-7).sum()) if len(sv) else 0
        names = [c for c, ok in zip(cols, live) if ok]
        collinear = []
        for e, vec in zip(ev, V.T):
            rel = math.sqrt(max(e, 0.0) / ev.max())
            if rel < 1e-3:
                part = [(names[k], round(float(vec[k]), 3)) for k in np.argsort(-np.abs(vec)) if abs(vec[k]) > 0.15]
                collinear.append({"columns": [p[0] for p in part], "weights": [p[1] for p in part], "relative_size": rel,
                                  "exact": rel < 1e-7})
        # each column's SE in the full regression (infinite along exact collinearity)
        se = np.full(len(cols), math.inf)
        keep = ev > ev.max() * 1e-14
        Ginv = (V[:, keep] / ev[keep]) @ V[:, keep].T
        exact_null = V[:, ev <= ev.max() * 1e-14]
        diag = np.diag(Ginv)
        for k, ci in enumerate(np.flatnonzero(live)):
            if exact_null.size and np.abs(exact_null[k]).max() > 0.05:
                continue
            se[ci] = math.sqrt(max(diag[k], 0.0)) / norms[ci]
        terms = []
        if linear:
            B = [sys_[0][i] for sys_ in systems]
            for ci, c in enumerate(cols):
                if c.startswith("1"):
                    w = next((w for w, (a, b) in enumerate(wins) if c == f"1 [{a}-{b}]"), None)
                    true = u[w] if w is not None else u[0]
                else:
                    vals = [Bw[ids.index(c)] for Bw in B]
                    true = float(np.mean(vals))
                if abs(true) < 1e-12:
                    continue
                z = abs(true) / se[ci] if se[ci] > 0 else math.inf
                p = 1.0 if math.isinf(z) else float(norm.cdf(z - crit) + norm.cdf(-z - crit))
                terms.append({"column": c, "true": float(true), "se_full": _fin(se[ci]), "z": _fin(z), "p_detect": p})
        out.append({"stock": s, "columns": cols, "rank": rank, "of": len(cols), "cond": cond, "collinear": collinear,
                    "terms": terms, "threshold": crit, "steps": n})
    return out


# ---- the best achievable accuracy, against the scorer's tolerance ----

def _allowances(case: dict, noise: str, truth_model: dict, d: dict) -> dict:
    """What the scorer allows each true part in each window: {(w, key): allowed}, and the rel for
    flows with effects. Mirrors score.equations."""
    from ..skill import truth_by_time
    tol = scoremod._tolerances(case, noise)
    measured = set(d["levels"])
    lv = d.get("all_levels") or d["levels"]
    means = {s: float(np.mean(v)) if len(v) else 0.0 for s, v in lv.items()}
    t = d["t"]
    wins = windows(truth_model, t)
    tflows, _ = truth_by_time(truth_model, t)
    true_w = [parts(tflows, measured, w)[0] for w in wins]
    true_keys = list(dict.fromkeys(k for tp in true_w for k in tp))
    weights = np.array([b - a + 1 for a, b in wins], dtype=float)
    weights /= weights.sum()
    sizes = [sum(wt * scoremod._size(k, tp[k], means, tp) for wt, tp in zip(weights, true_w) if k in tp) for k in true_keys]
    finite = [s for s in sizes if math.isfinite(s) and s > 0]
    scale = float(np.median(finite)) if finite else 1.0
    oracle = Oracle(tflows, d, wins)
    hidden = HiddenOracle(tflows, d, wins, noise) if not oracle.ok and any(k[0] == "hidden" for k in true_keys) else None
    allowed, ses = {}, {}
    for w, tp in enumerate(true_w):
        for k, v in tp.items():
            if k[0] == "hidden":
                hse = (hidden.hidden_se(k, w) if hidden else None) or {}
                lvl = max(1e-9, means.get(k[1], 0.0))
                allowed[(w, k, "k_in")] = max(tol["rel"] * abs(v["k_in"]), tol["floor"] * scale / lvl, tol["z"] * (hse.get("k_in") or 0.0))
                allowed[(w, k, "delay")] = max(tol["rel"] * v["delay"], tol["z"] * (hse.get("delay") or 0.0)) if math.isfinite(v["delay"]) else 0.0
                ses[(w, k, "k_in")], ses[(w, k, "delay")] = hse.get("k_in"), hse.get("delay")
                continue
            if k[0] not in ("flow", "uses") or not isinstance(v, (int, float)):
                continue
            se = oracle.part_se(k, true_keys, w) if oracle.ok else hidden.part_se(k, w) if hidden else None
            reader = k[3] if k[0] == "flow" else None
            level = 1.0 if reader in (None, ONE) else max(1e-9, means.get(reader, 0.0))
            allowed[(w, k)] = max(tol["rel"] * abs(v), tol["floor"] * scale / level, tol["z"] * (se or 0.0))
            ses[(w, k)] = se
    effect_ends = sorted({(f.get("from") if f.get("from") in measured else None, f.get("to") if f.get("to") in measured else None)
                          for f in truth_model["flows"] if f.get("effects")}, key=str)
    return {"allowed": allowed, "oracle_se": ses, "tol": tol, "true": true_w, "wins": wins, "effect_ends": effect_ends,
            "hidden": hidden, "scale": scale}


def _p_within(allowed: float, se: float | None) -> float:
    if se is None or not math.isfinite(se):
        return 0.0
    if se <= 0:
        return 1.0
    return float(2 * norm.cdf(allowed / se) - 1)


def analyse(case_id: str, variant: str, mc: bool = True) -> dict:
    case = casemod.load(case_id)
    v = casemod.variant(case, variant)
    noise = v["noise"]
    tm = casemod.truth_model(case, variant)
    d = datamod.load(case, variant)
    out = {"case": case_id, "variant": variant, "noise": noise, "steps": v["steps"], "hash": case["hash"], "code": code_hash() + _tolerance_hash()}
    tp = TruthParams(tm, d, noise)
    al = _allowances(case, noise, tm, d)
    hidden_truth = any(not s.get("measured", True) for s in case["model"]["stocks"])
    out["design"] = design(tm, d, noise, tp if tp.ok else None)
    notes, equivalences = [], _equivalences(case, tm)
    structure_p, structure_bad = 1.0, []
    for row in out["design"]:
        for term in row["terms"]:
            if term["column"].startswith("1 ["):                      # a window's constant: a piece, scored as a number
                continue
            structure_p *= term["p_detect"]
            if term["z"] is not None and term["z"] < row["threshold"]:
                structure_bad.append(f"{row['stock']} <- {term['column']} (z {term['z']:.2g} < {row['threshold']:.2g})")
            if term["z"] is None or (term["se_full"] is None):
                pass
        for g in row["collinear"]:
            text = (f"{' ~ '.join(sorted(g['columns']))} are {'exactly ' if g['exact'] else 'nearly '}collinear on this run"
                    f" (each row may read any of them: the data cannot say which)")
            if text not in equivalences:
                equivalences.append(text)
    unident, why = [], []
    part_rows = []
    if tp.ok:
        measured_ids = set(d["levels"])
        for text, alt in alternatives(tm, measured_ids):
            p_alt = _separation(tp, alt, d, noise)
            if p_alt is None:
                continue
            if noise == "none":
                unident.append(f"structure: {text}: the same levels with as many numbers")
            else:
                structure_p *= p_alt
                if p_alt < 0.75:
                    structure_bad.append(f"{text} (told apart by the noise with p {p_alt:.2f})")
            equivalences.append(f"{text}: the same mean change of every stock; told apart only by the noise"
                                + ("" if noise == "none" else f" (P(the likelihood prefers the truth) {p_alt:.2f})"))
        fi = tp.fisher()
        C, null = bound(fi["full"])
        Cm, null_m = bound(fi["mean"])
        se_full = np.sqrt(np.maximum(np.diag(C), 0))
        se_mean = np.sqrt(np.maximum(np.diag(Cm), 0))
        out["parameters"] = [{"name": n, "true": float(th), "crb_se": float(a), "crb_se_mean_only": float(b),
                              "unidentified": bool(null.size and np.abs(null[i]).max() > 1e-3)}
                             for i, (n, th, a, b) in enumerate(zip(tp.labels, tp.theta0, se_full, se_mean))]
        keys, vals, D = part_map(tp)
        Cp = D @ C @ D.T
        scale_p = np.maximum(np.abs(vals), 1e-9)
        p_null = (np.abs(D @ null).max(axis=1) / scale_p if null.size else np.zeros(len(keys))) > 1e-6
        p_null_m = (np.abs(D @ null_m).max(axis=1) / scale_p if null_m.size else np.zeros(len(keys))) > 1e-6
        effect_ends = set(al["effect_ends"])
        for i, (w, k) in enumerate(keys):
            allowed = al["allowed"].get((w, k))
            if allowed is None or (k[1], k[2]) in effect_ends:        # a flow with effects is compared as a whole
                continue
            se = math.inf if p_null[i] else math.sqrt(max(Cp[i, i], 0.0))
            r = {"part": label(k), "window": w, "true": float(vals[i]), "crb_se": _fin(se), "allowed": allowed,
                 "oracle_se": al["oracle_se"].get((w, k)), "p": _p_within(allowed, se)}
            if p_null[i]:
                r["unidentified"] = True
                unident.append(f"{label(k)}: only a combination with other numbers shows in the data")
            elif p_null_m[i] and noise != "none":
                r["variance_only"] = True
                notes.append(f"{label(k)} is identifiable only through the counting noise's variance (not from the mean)")
            part_rows.append((r, D[i]))
        effect_rows = []
        for ends in al["effect_ends"]:
            base, G = amounts_jacobian(tp, ends)
            rms = float(np.sqrt(np.mean(base ** 2))) or 1e-9
            # the rms relative error of the amount at the bound (expected): sqrt(tr(G C G') / K) / rms
            e_rms = float(np.sqrt(max(np.einsum("kp,pq,kq->", G, C, G) / len(base), 0.0)) / rms)
            bad = bool(null.size and (np.abs(G @ null).max() / rms) > 1e-6)
            effect_rows.append({"ends": [e or "outside" for e in ends], "rel_rms_se": e_rms, "allowed": al["tol"]["rel"],
                                "unidentified": bad, "G": G, "rms": rms})
            if bad:
                unident.append(f"the flow {ends[0] or 'outside'} -> {ends[1] or 'outside'} (with effects): its amount is not pinned down")
        if noise != "none":
            # counts near zero: whole numbers 0, 1, 2 and drains cut short by an empty stock are far from the
            # Gaussian the bound assumes (on 056 the truth's own Gaussian ML refit is biased 25-40% there)
            low = float((tp.prev[[tp.idx[x] for x in tp.measured]] <= 2).any(axis=0).mean())
            out["near_floor"] = low
            if low > 0.05:
                out["approximate"] = True
                notes.append(f"a stock is at 2 or below on {100 * low:.0f}% of steps: the Gaussian bound is approximate there"
                             " (an exact count likelihood could do better; a Gaussian method is biased)")
        p_numbers, per_effect = _joint(part_rows, effect_rows, C)
        for e, pe in zip(effect_rows, per_effect):
            e["p"] = pe
        out["parts"] = [r for r, _ in part_rows]
        out["effects"] = [{k: v for k, v in e.items() if k not in ("G", "rms")} for e in effect_rows]
        if noise == "none" and structure_bad:
            unident += [f"structure: {x} is collinear with other columns to the data's precision" for x in structure_bad]
    elif hidden_truth and al["hidden"] is not None and al["hidden"].ok:
        rows = []
        for (w, k, *sub), allowed in al["allowed"].items():
            se = al["oracle_se"].get((w, k, *sub))
            name = label(k) + (f" {sub[0]}" if sub else "")
            rows.append({"part": name, "window": w, "allowed": allowed, "crb_se": se, "p": _p_within(allowed, se), "source": "hidden oracle (ML)"})
        out["parts"] = rows
        p_numbers = float(np.prod([r["p"] for r in rows])) if rows else 1.0
        notes.append("hidden stock: the SEs are the hidden oracle's (ML on the measured data), not a bound over every method")
    elif hidden_truth and noise == "none":
        out["parts"] = []
        p_numbers = None
        notes.append("hidden stock without noise: exact if identifiable (no oracle)")
    else:
        out["parts"] = []
        p_numbers = None
        notes.append("not analysed: a truth this analysis does not cover")
    mirror = _mirror(case)
    if mirror:
        equivalences.append(mirror)
        if noise == "none":
            unident.append("the hidden stock's mirror (its delay and B's drain swapped, k_in rescaled) gives the same measured levels")
        else:
            notes.append("the hidden stock's mirror is told apart only through the counting noise")
    out["structure_p"] = structure_p
    out["numbers_p"] = p_numbers
    out["p"] = None if p_numbers is None else p_numbers * structure_p
    if unident:
        lab = "unidentifiable"
        out["p"] = 0.0                     # a pass here comes from a prior (parsimony, a tiebreak), not from the data
    elif out["p"] is None:
        lab = "not analysed"
    elif out["p"] < ACHIEVABLE:
        lab = "data-limited"
        why.append(_limit_reason(out, structure_bad))
    else:
        lab = "achievable"
    out.update(label=lab, why=unident + [w for w in why if w], equivalences=equivalences, notes=sorted(set(notes)))
    return _jsonable(out)


def _joint(part_rows: list, effect_rows: list, C: np.ndarray) -> tuple[float, list[float]]:
    """P(every part within its allowance and every effect flow within rel), at the bound's normal."""
    if not part_rows and not effect_rows:
        return 1.0, []
    if any(r.get("unidentified") for r, _ in part_rows) or any(e["unidentified"] for e in effect_rows):
        return 0.0, [0.0 if e["unidentified"] else 1.0 for e in effect_rows]
    w, V = np.linalg.eigh((C + C.T) / 2)
    L = V * np.sqrt(np.maximum(w, 0.0))
    rng = np.random.default_rng(12345)
    Z = rng.standard_normal((C.shape[0], DRAWS))
    delta = L @ Z
    ok = np.ones(DRAWS, dtype=bool)
    if part_rows:
        D = np.array([row for _, row in part_rows])
        allowed = np.array([r["allowed"] for r, _ in part_rows])
        ok &= (np.abs(D @ delta) <= allowed[:, None] + 1e-12).all(axis=0)
    per_effect = []
    for e in effect_rows:
        err = np.sqrt(np.mean((e["G"] @ delta) ** 2, axis=0)) / e["rms"]
        within = err <= e["allowed"]
        per_effect.append(float(within.mean()))
        ok &= within
    return float(ok.mean()), per_effect


def _limit_reason(out: dict, structure_bad: list[str]) -> str:
    worst = sorted((r for r in out.get("parts") or [] if r.get("p") is not None), key=lambda r: r["p"])[:2]
    bits = [f"{r['part']} reached within tolerance with p {r['p']:.2f} (bound SE {r['crb_se']:.3g}, allowed {r['allowed']:.3g})"
            for r in worst if r["p"] < 0.95]
    if structure_bad:
        bits.append("terms hard to tell from the alternatives: " + "; ".join(structure_bad[:3]))
    return "; ".join(bits)


def _equivalences(case: dict, truth_model: dict) -> list[str]:
    """Models that make the same levels with more numbers (parsimony picks the truth)."""
    measured = {s["id"] for s in case["model"]["stocks"] if s.get("measured", True)}
    out = []
    for f in truth_model["flows"]:
        a, b = f.get("from"), f.get("to")
        if a in measured and b in measured and not f.get("effects") and not f.get("uses") and _drain(truth_model, a) is None:
            out.append(f"the move {a} -> {b} makes the same levels as a link outside -> {b} reading {a} plus a drain {a} -> outside at"
                       " the same rate (one number more: parsimony picks the move)")
    return out


def _drain(tm: dict, j: str) -> dict | None:
    """j's proportional drain to outside that never changes (None if it has none)."""
    sched = {fid for c in (tm.get("schedule") or {}).get("changes") or [] for fid in c.get("set") or {}}
    for f in tm["flows"]:
        r = f.get("rate") or {}
        if f.get("from") == j and not f.get("to") and r.get("form") == "proportional" and r.get("stock") == j \
                and f["id"] not in sched and not f.get("effects") and not f.get("uses") and float(f.get("ratio") or 1) == 1:
            return f
    return None


def alternatives(tm: dict, measured: set) -> list[tuple[str, dict]]:
    """Structures with no more numbers than the truth that make exactly the same mean change of every
    measured stock (the same linear system: the levels' B and u are identified, their split into
    non-negative flows is not), so only the noise can tell them apart:

    - a link outside -> i reading j at k, where j drains to outside at d: with m = min(k, d), the move
      j -> i at m, the link at k - m and j's drain at d - m (k = d: one number fewer);
    - a move j -> i at k, where j also drains to outside at d: a link at k and j's drain at d + k;
    - an inflow with a negative term (a gap: c - k j): the inflow c and an outflow i -> outside
      reading j at k;
    - a co-flow (a flow using up `per` of R per unit): an outflow R -> outside at per x the flow's rate."""
    import copy
    out = []
    sched = {fid for c in (tm.get("schedule") or {}).get("changes") or [] for fid in c.get("set") or {}}

    def plain(f):
        return f["id"] not in sched and not f.get("effects") and float(f.get("ratio") or 1) == 1

    for fi, f in enumerate(tm["flows"]):
        if not plain(f):
            continue
        r = f.get("rate") or {}
        a, b = f.get("from"), f.get("to")
        form = r.get("form")
        if form == "gap":
            T = float(r.get("time") or 1)
            c, terms = float(r.get("goal") or 0) / T, [{"stock": r.get("stock"), "k": -1 / T}]
        elif form == "linear":
            c, terms = float(r.get("c") or 0), list(r.get("terms") or [])
        elif form == "proportional":
            c, terms = 0.0, [{"stock": r.get("stock"), "k": r.get("k")}]
        elif form == "constant":
            c, terms = float(r.get("value") or 0), []
        else:
            continue
        if f.get("uses"):
            for u in f["uses"]:
                R, per = u.get("stock"), float(u.get("per") or 0)
                if R not in measured or per <= 0:
                    continue
                alt = copy.deepcopy(tm)
                g = alt["flows"][fi]
                g["uses"] = [x for x in g["uses"] if x.get("stock") != R] or None
                if g["uses"] is None:
                    g.pop("uses")
                alt["flows"].append({"id": "alt_use", "name": "alt_use", "from": R, "to": None, "rate": _scaled(r, per)})
                out.append((f"the co-flow using {per:g} of {R} per unit of {a or 'outside'} -> {b or 'outside'} is an outflow {R} -> outside"
                            f" at {per:g} x that flow's rate", alt))
            continue
        if a is None and b in measured:
            for t in terms:
                j, k = t.get("stock"), float(t.get("k") or 0)
                if j not in measured:
                    continue
                if k < 0 and c > 0:                                     # c - k j: the inflow c and an outflow reading j
                    alt = copy.deepcopy(tm)
                    rest = [x for x in terms if x.get("stock") != j]
                    alt["flows"][fi] = {**alt["flows"][fi], "rate": _linear(c, rest)}
                    alt["flows"].append({"id": "alt_out", "name": "alt_out", "from": b, "to": None, "rate": {"form": "proportional", "stock": j, "k": -k}})
                    out.append((f"the inflow into {b} with {k:g} x {j} is the inflow {c:g} and an outflow {b} -> outside reading {j} at {-k:g}", alt))
                d = _drain(tm, j) if j != b else None
                if k > 0 and d is not None:                             # a link: part of it may be a move from j
                    dk = float(d["rate"]["k"])
                    m = min(k, dk)
                    alt = copy.deepcopy(tm)
                    rest = [x for x in terms if x.get("stock") != j] + ([{"stock": j, "k": k - m}] if k - m > 1e-12 else [])
                    if c or rest:
                        alt["flows"][fi] = {**alt["flows"][fi], "rate": _linear(c, rest)}
                    else:
                        alt["flows"][fi] = None
                    dd = next(x for x in alt["flows"] if x and x["id"] == d["id"])
                    if dk - m > 1e-12:
                        dd["rate"] = {**dd["rate"], "k": dk - m}
                    else:
                        alt["flows"].remove(dd)
                    alt["flows"] = [x for x in alt["flows"] if x]
                    alt["flows"].append({"id": "alt_move", "name": "alt_move", "from": j, "to": b, "rate": {"form": "proportional", "stock": j, "k": m}})
                    out.append((f"the link outside -> {b} reading {j} ({k:g}) with {j}'s drain {dk:g} is the move {j} -> {b} ({m:g})"
                                + (f" plus a link ({k - m:g})" if k - m > 1e-12 else "") + (f" with {j}'s drain {dk - m:g}" if dk - m > 1e-12 else " and no drain"),
                                alt))
        elif a in measured and b is None and form == "proportional" and r.get("stock") in measured:
            # an outflow reading j beside a constant inflow into the same stock: one inflow c - k j (fewer flows),
            # the same while c - k j stays above 0 on the run (the floor would otherwise show)
            j, k = r.get("stock"), float(r.get("k") or 0)
            for gi, g in enumerate(tm["flows"]):
                gr = g.get("rate") or {}
                gc = float(gr.get("value") or 0) if gr.get("form") == "constant" else float(gr.get("c") or 0) if gr.get("form") == "linear" else 0.0
                if gi == fi or g.get("from") is not None or g.get("to") != a or not plain(g) or g.get("uses") or gc <= 0 or k <= 0:
                    continue
                alt = copy.deepcopy(tm)
                gterms = list(gr.get("terms") or []) if gr.get("form") == "linear" else []
                alt["flows"][gi] = {**alt["flows"][gi], "rate": _linear(gc, gterms + [{"stock": j, "k": -k}])}
                alt["flows"].pop(fi)
                out.append((f"the inflow {gc:g} into {a} and its outflow {k:g} x {j} are one inflow {gc:g} - {k:g} x {j} (a gap)", alt))
                break
        elif a in measured and b in measured and form == "proportional" and r.get("stock") == a:
            d = _drain(tm, a)
            k = float(r.get("k") or 0)
            if d is None or k <= 0:
                continue
            alt = copy.deepcopy(tm)
            alt["flows"][fi] = {**alt["flows"][fi], "from": None}
            dd = next(x for x in alt["flows"] if x["id"] == d["id"])
            dd["rate"] = {**dd["rate"], "k": float(d["rate"]["k"]) + k}
            out.append((f"the move {a} -> {b} ({k:g}) with {a}'s drain {float(d['rate']['k']):g} is a link outside -> {b} reading {a} ({k:g})"
                        f" with {a}'s drain {float(d['rate']['k']) + k:g}", alt))
    return out


def _linear(c: float, terms: list[dict]) -> dict:
    if not terms:
        return {"form": "constant", "value": c}
    return {"form": "linear", **({"c": c} if c else {}), "terms": terms}


def _scaled(rate: dict, x: float) -> dict:
    r = dict(rate)
    form = r.get("form")
    if form == "constant":
        r["value"] = float(r.get("value") or 0) * x
    elif form == "proportional":
        r["k"] = float(r.get("k") or 0) * x
    elif form == "gap":
        r["time"] = float(r.get("time") or 1) / x
    elif form == "linear":
        r["c"] = float(r.get("c") or 0) * x
        r["terms"] = [{**t, "k": float(t.get("k") or 0) * x} for t in r.get("terms") or []]
    return r


def _separation(tp: TruthParams, alt_model: dict, d: dict, noise: str) -> float | None:
    """P(the likelihood prefers the truth to an alternative with the same means): the alternatives
    differ only in the noise's covariance; with D = sum of KL(truth || alternative) over the steps,
    the log-likelihood ratio is about N(D, 2D), so P = Phi(sqrt(D / 2)). None when the means differ
    (not an exact equivalent on this run)."""
    ta = TruthParams(alt_model, d, noise)
    if not ta.ok:
        return None
    m1, S1 = tp.mean_var(tp.theta0)
    m2, S2 = ta.mean_var(ta.theta0)
    if np.abs(m1 - m2).max() > 1e-6 * max(1.0, np.abs(m1).max()):
        return None
    if noise == "none":
        return 0.5
    n = S1.shape[1]
    S2i = np.linalg.inv(S2)
    kl = 0.5 * (np.einsum("kij,kji->k", S2i, S1) - n + np.linalg.slogdet(S2)[1] - np.linalg.slogdet(S1)[1])
    D = float(np.maximum(kl, 0).sum())
    return float(norm.cdf(math.sqrt(D / 2)))


def _mirror(case: dict) -> str | None:
    """A hidden stock H between A and B (A -> H -> B) whose B also drains: delay and drain swap."""
    stocks = {s["id"]: s for s in case["model"]["stocks"]}
    hidden = [s for s, x in stocks.items() if not x.get("measured", True)]
    for h in hidden:
        outs = [f for f in case["model"]["flows"] if f.get("from") == h and f.get("to")]
        for o in outs:
            b = o["to"]
            drains = [f for f in case["model"]["flows"] if f.get("from") == b and not f.get("to") and (f.get("rate") or {}).get("form") == "proportional"]
            k_out = (o.get("rate") or {}).get("k")
            if drains and k_out and abs(float(drains[0]["rate"]["k"]) - float(k_out)) > 1e-9:
                return (f"the mirror of {h}: delay 1/{float(drains[0]['rate']['k']):g} and {b}'s drain {float(k_out):g} (swapped from delay"
                        f" 1/{float(k_out):g}, drain {float(drains[0]['rate']['k']):g}) make the same {b} from the same input")
    return None


def _fin(x):
    return float(x) if x is not None and math.isfinite(x) else None


def _jsonable(x):
    if isinstance(x, dict):
        return {str(k): _jsonable(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_jsonable(v) for v in x]
    if isinstance(x, (np.floating, float)):
        return float(x) if math.isfinite(x) else None
    if isinstance(x, (np.integer,)):
        return int(x)
    if isinstance(x, np.bool_):
        return bool(x)
    return x


# ---- the cache ----

def _path(case_id: str, variant: str, case_hash: str) -> Path:
    return datamod.cache_root() / "analysis" / f"{case_id.replace('#', '~')}-{variant}-{case_hash}.json"


def get(case_id: str, variant: str, compute: bool = True) -> dict | None:
    """The analysis of a case and variant, from the cache (recomputed when the case, the analysis or
    the scorer's tolerance changed); None when not cached and not computed."""
    c = casemod.load(case_id)
    p = _path(case_id, variant, c["hash"])
    want = code_hash() + _tolerance_hash()
    if p.exists():
        try:
            got = json.loads(p.read_text())
            if got.get("code") == want or not compute:
                return got
        except ValueError:
            pass
    if not compute:
        return None
    got = analyse(case_id, variant)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(got))
    tmp.replace(p)
    return got


_brief: dict[str, tuple] = {}


def version() -> tuple:
    """Changes when an analysis is written (for the summary's cache)."""
    try:
        with os.scandir(datamod.cache_root() / "analysis") as it:
            m = [e.stat().st_mtime for e in it if e.name.endswith(".json")]
    except OSError:
        return (0, 0.0)
    return (len(m), max(m, default=0.0))


def cell(case_id: str, variant: str, case_hash: str) -> dict:
    """The few numbers a matrix cell carries ({} when not analysed yet): label, p."""
    p = _path(case_id, variant, case_hash)
    try:
        st = p.stat()
    except OSError:
        return {}
    have = _brief.get(str(p))
    if not have or have[0] != st.st_mtime:
        try:
            got = json.loads(p.read_text())
        except ValueError:
            return {}
        have = (st.st_mtime, {"analysis": got.get("label"), "achievable_p": got.get("p")})
        _brief[str(p)] = have
    return dict(have[1])


def _one(item: tuple) -> tuple:
    cid, v = item
    try:
        a = get(cid, v)
        return cid, v, a["label"], a.get("p"), None
    except Exception as e:                                           # noqa: BLE001  (reported, the rest carries on)
        return cid, v, "error", None, f"{type(e).__name__}: {e}"


def analyse_all(case_ids: list[str], jobs: int | None = None, on_done=None) -> list[tuple]:
    """Fill the cache for every variant of these cases, in parallel."""
    from concurrent.futures import ProcessPoolExecutor
    items = [(cid, v["name"]) for cid in case_ids for v in casemod.load(cid)["variants"]]
    out = []
    jobs = jobs or max(1, (os.cpu_count() or 2) - 1)
    if jobs == 1:
        for it in items:
            out.append(_one(it))
            if on_done:
                on_done(out[-1])
        return out
    with ProcessPoolExecutor(jobs) as ex:
        for r in ex.map(_one, items, chunksize=2):
            out.append(r)
            if on_done:
                on_done(r)
    return out
