"""The oracle for a truth with a hidden stock: the truth's own structure fitted by maximum likelihood
on the measured data (the hidden level followed by a one-state Kalman filter), and the standard
error of each number from the curvature of the likelihood. Like the linear oracle (oracle.py), it
says how precisely the run pins each number down, so a found number is allowed z standard errors.

The truth it covers: measured A and B only, an unmeasured H between them (A -> H reading A, H -> B
reading H, nothing else touching H), and every other flow linear in A and B with A's row reading
only A and B's row only B:

    A(t) - A(t-1) = cA(w) - (kin + kAo) A(t-1)
    H(t)          = (1 - d) H(t-1) + kin A(t-1)
    B(t) - B(t-1) = cB(w) + d H(t-1) - kb B(t-1)

cA and cB get one number per window when the truth's changes between windows (as the linear oracle
does); kin, kAo, d, kb must hold still. Numbers the truth does not have (kAo, cB, kb at 0) are not
fitted. H's start is a free number (no method sees it). Every flow is a count around its rate, so
the noise is shared: what leaves A towards H is seen in A's change and in H's, what leaves H in H's
and B's (the filter of strategies/hidden_transit/kalman.py, copied here so the scorer does not move
with a strategy). Whole-number data are counts (noise scale 1); other data have the scale
concentrated out. Without noise there is no oracle (the SE would be about 0 anyway).

Fitted from the truth's numbers (a local maximum next to the truth: the mirror, d and kb swapped, is
another one and is not wanted) by L-BFGS-B; SEs from the inverse of the numerical Hessian of
-log L. The delay's SE is d's by the delta method (SE(d) / d^2). Results are cached per
(truth, data).

**A hidden stock fed from outside** (2026-10-19, with the scoring of such paths: a supply line,
a delayed input; 133, 134): one measured B, an unmeasured H fed from outside at a linear rate of
B and the measured inputs (floored at 0), released into B at d H, B's other flows linear in B:

    H(t)          = (1 - d) H(t-1) + max(0, c_in + sum_j k_j x_j(t-1))
    B(t) - B(t-1) = cB(w) + d H(t-1) - kb B(t-1)          (announced injections into B added first)

fitted and given SEs the same way (filter `_filter_out`: the inflow's count is seen only in H, the
release in H's and B's changes). The SEs of the inflow's numbers are the oracle's for the scorer's
("via", None, B, reader) parts, d's for the delay. A compiled DELAYn (n > 1: several hidden
stocks) or any other shape is not covered (the tolerances alone apply, as before).
"""

from __future__ import annotations

import hashlib
import json
import math

import numpy as np
from numba import njit
from scipy.optimize import minimize

from .parts import ONE, _hidden_chains, form_over, linear_system

FLOOR = 0.05       # a count's variance is never taken below this
_CACHE: dict[str, dict | None] = {}


@njit(cache=True)
def _filter(A, B, cA, cB, kin, kAo, d, kb, m0, P0):
    n = A.shape[0]
    m, P = m0, P0
    ss = 0.0
    ld = 0.0
    for t in range(1, n):
        a = A[t - 1]
        b = B[t - 1]
        vo = max(kin * a, FLOOR)
        vA = abs(cA[t - 1]) + max(kAo * a, 0.0) + FLOOR
        vp = max(d * max(m, 0.0), FLOOR)
        vB = max(kb * b, 0.0) + abs(cB[t - 1]) + FLOOR
        muA = cA[t - 1] - (kin + kAo) * a
        muB = cB[t - 1] + d * m - kb * b
        muH = (1.0 - d) * m + kin * a
        sA = vA + vo
        sB = d * d * P + vp + vB
        sH = (1.0 - d) * (1.0 - d) * P + vo + vp
        cAH = -vo
        cBH = d * (1.0 - d) * P - vp
        eA = (A[t] - a) - muA
        eB = (B[t] - b) - muB
        ss += eA * eA / sA + eB * eB / sB
        ld += math.log(sA) + math.log(sB)
        m = muH + cAH / sA * eA + cBH / sB * eB
        P = sH - cAH * cAH / sA - cBH * cBH / sB
        if P < 1e-9:
            P = 1e-9
    return ss, ld


@njit(cache=True)
def _filter_out(B, X, cin, k, cB, d, kb, m0, P0):
    """The filter of a hidden stock fed from outside (B's levels already include the injections made at
    the start of each step: B[t - 1] is the level the step starts from, dB[t] its change)."""
    n = B.shape[0]
    m, P = m0, P0
    ss = 0.0
    ld = 0.0
    for t in range(1, n):
        b = B[t - 1]
        rin = cin
        for j in range(k.shape[0]):
            rin += k[j] * X[j, t - 1]
        if rin < 0.0:
            rin = 0.0
        vin = max(rin, FLOOR)
        vp = max(d * max(m, 0.0), FLOOR)
        vB = max(kb * b, 0.0) + abs(cB[t - 1]) + FLOOR
        muB = cB[t - 1] + d * m - kb * b
        muH = (1.0 - d) * m + rin
        sB = d * d * P + vp + vB
        sH = (1.0 - d) * (1.0 - d) * P + vin + vp
        cBH = d * (1.0 - d) * P - vp
        eB = X[X.shape[0] - 1, t] - muB
        ss += eB * eB / sB
        ld += math.log(sB)
        m = muH + cBH / sB * eB
        P = sH - cBH * cBH / sB
        if P < 1e-9:
            P = 1e-9
    return ss, ld


def _structure_out(truth_flows: list[dict], ids: list[str], wins: list[tuple[int, int]], chains: dict, used: set, inputs: list[str]) -> dict | None:
    """The truth's numbers in the outside-fed shape, per window; None when it is not that shape."""
    if len(ids) != 1 or len(chains) != 1 or next(iter(chains))[0] is not None:
        return None
    (_, b), chain = next(iter(chains.items()))
    if "time" in chain or chain.get("stages"):
        return None
    h = chain["via"]
    if any(f.get("effects") or f.get("uses") or float(f.get("ratio") or 1) != 1 for f in chain["in"] + chain["out"]):
        return None
    if any((f.get("from") == h or f.get("to") == h) and i not in used for i, f in enumerate(truth_flows)):
        return None
    rest = [f for i, f in enumerate(truth_flows) if i not in used]
    readers = [b] + list(inputs)
    per: dict = {"cin": [], "k": [], "d": [], "cB": [], "kb": []}
    for w in wins:
        sys_ = linear_system(rest, ids, w)
        if sys_ is None:
            return None
        Bm, u = sys_
        forms_in = [form_over(f, *w) for f in chain["in"]]
        forms_out = [form_over(f, *w) for f in chain["out"]]
        if any(lf is None or set(lf[1]) - set(readers) for lf in forms_in):
            return None
        if any(lf is None or lf[0] or set(lf[1]) - {h} for lf in forms_out):
            return None
        per["cin"].append(sum(lf[0] for lf in forms_in))
        per["k"].append([sum(lf[1].get(r, 0.0) for lf in forms_in) for r in readers])
        per["d"].append(sum(lf[1].get(h, 0.0) for lf in forms_out))
        per["cB"].append(float(u[0]))
        per["kb"].append(float(-Bm[0, 0]))
    for key in ("cin", "d", "kb"):
        if any(abs(v - per[key][0]) > 1e-12 for v in per[key]):
            return None
    if any(any(abs(x - y) > 1e-12 for x, y in zip(kk, per["k"][0])) for kk in per["k"]):
        return None
    if not 0 < per["d"][0] < 1 or per["kb"][0] < 0:
        return None
    return {"B": b, "H": h, "readers": readers, **per}


def _fit_out(st: dict, data: dict, wins: list[tuple[int, int]]) -> dict | None:
    t = data["t"]
    if len(t) < 10:
        return None
    b = st["B"]
    lv = np.asarray(data["levels"][b], dtype=float)
    inj = np.zeros(len(t))
    tindex = {v: i for i, v in enumerate(t)}
    for j in data.get("injections") or []:
        if j.get("stock") == b and j["t"] in tindex:
            inj[tindex[j["t"]]] += float(j["amount"])
    # the level each step starts from (injections made first) and the level it ends at
    start = np.concatenate([lv[:-1] + inj[1:], lv[-1:]])
    inputs = data.get("inputs") or {}
    rows = [start] + [np.concatenate([np.asarray(inputs[r], dtype=float)[1: len(t)], [0.0]]) for r in st["readers"][1:]]
    # X: the readers per step start (b's level with the injection, each input during the step), then B's change
    X = np.ascontiguousarray(np.vstack(rows + [np.concatenate([[0.0], lv[1:] - start[:-1]])]))
    Bv = np.ascontiguousarray(start)
    counts = bool(np.all(lv == np.round(lv)))
    steps = np.asarray(t[1:])
    win = np.zeros(len(steps), dtype=int)
    for w, (lo, hi) in enumerate(wins):
        win[(steps >= lo) & (steps <= hi)] = w
    W = len(wins)
    names: list[tuple[str, int | None, float]] = []
    if abs(st["cin"][0]) > 0:
        names.append(("cin", None, st["cin"][0]))
    for r, kv in zip(st["readers"], st["k"][0]):
        if abs(kv) > 0:
            names.append((f"k:{r}", None, kv))
    vals = st["cB"]
    if any(abs(v) > 0 for v in vals):
        if any(abs(v - vals[0]) > 1e-12 for v in vals):
            names += [("cB", w, vals[w]) for w in range(W)]
        else:
            names.append(("cB", None, vals[0]))
    names.append(("d", None, st["d"][0]))
    if abs(st["kb"][0]) > 0:
        names.append(("kb", None, st["kb"][0]))
    hidden = data.get("all_levels", {}).get(st["H"])
    names.append(("m0", None, float(hidden[0]) if hidden is not None and len(hidden) else 0.0))
    x0 = np.array([v for _, _, v in names], dtype=float)
    scale = np.array([max(abs(v), 1e-3) if k in ("d", "kb") or k.startswith("k:") else max(abs(v), 1.0) for k, _, v in names])
    n = len(lv) - 1
    nr = len(st["readers"])

    def unpack(x):
        p = {"cin": 0.0, "k": np.zeros(nr), "cB": np.zeros(len(lv) - 1), "d": 0.0, "kb": 0.0, "m0": 0.0}
        for (k, w, _), v in zip(names, x):
            if k == "cB":
                if w is None:
                    p["cB"][:] = v
                else:
                    p["cB"][win == w] = v
            elif k.startswith("k:"):
                p["k"][st["readers"].index(k[2:])] = v
            else:
                p[k] = float(v)
        return p

    def nll(y):
        p = unpack(y * scale)
        if not (0 < p["d"] < 1) or p["kb"] < 0:
            return 1e300
        ss, ld = _filter_out(Bv, X, p["cin"], p["k"], p["cB"], p["d"], p["kb"], p["m0"], 1e-9)
        if counts:
            return 0.5 * (ss + ld)
        return 0.5 * (n * math.log(max(ss / n, 1e-300)) + ld)

    bounds = []
    for (k, _, _), sc in zip(names, scale):
        lo = {"d": 1e-6, "kb": 0.0, "m0": 0.0}.get(k)
        hi = 0.999 if k == "d" else None
        bounds.append((None if lo is None else lo / sc, None if hi is None else hi / sc))
    return _hessian_se(nll, x0 / scale, scale, bounds, names, W, {"B": b})


def _hessian_se(nll, y0, scale, bounds, names, W: int, out: dict) -> dict | None:
    """Fit by L-BFGS-B from the truth's numbers; SEs from the inverse numerical Hessian of -log L (a
    number at its bound held there); the delay's SE from d's by the delta method."""
    res = minimize(nll, y0, method="L-BFGS-B", bounds=bounds, options={"maxiter": 500})
    y = res.x
    f0 = nll(y)
    if not math.isfinite(f0) or f0 >= 1e299:
        return None
    free = [i for i, (lo, hi) in enumerate(bounds) if not ((lo is not None and y[i] - lo < 1e-6) or (hi is not None and hi - y[i] < 1e-6))]
    k = len(free)
    H = np.zeros((k, k))
    hstep = 1e-2

    def at(i, si, j=None, sj=0.0):
        z = y.copy()
        z[free[i]] += si
        if j is not None:
            z[free[j]] += sj
        return nll(z)

    for i in range(k):
        for j in range(i, k):
            if i == j:
                v = (at(i, hstep) - 2 * f0 + at(i, -hstep)) / hstep ** 2
            else:
                v = (at(i, hstep, j, hstep) - at(i, hstep, j, -hstep) - at(i, -hstep, j, hstep) + at(i, -hstep, j, -hstep)) / (4 * hstep ** 2)
            H[i, j] = H[j, i] = v
    try:
        evals = np.linalg.eigvalsh(H)
        if not np.all(np.isfinite(evals)) or evals.min() <= 0:
            return None
        cov = np.linalg.inv(H)
    except np.linalg.LinAlgError:
        return None
    se = np.zeros(len(y))
    se[free] = np.sqrt(np.diag(cov)) * scale[free]
    est = y * scale
    out = {**out, "W": W}
    for (name, w, _), e, s in zip(names, est, se):
        for ww in range(W) if w is None else [w]:
            out.setdefault(name, {"est": [None] * W, "se": [None] * W})
            out[name]["est"][ww], out[name]["se"][ww] = float(e), float(s)
    d = out["d"]
    out["delay"] = {"est": [1 / x for x in d["est"]], "se": [s / (x * x) for x, s in zip(d["est"], d["se"])]}
    return out


def _structure(truth_flows: list[dict], ids: list[str], wins: list[tuple[int, int]]) -> dict | None:
    """The truth's numbers in the covered shape, per window; None when it is not that shape."""
    if len(ids) != 2:
        return None
    measured = set(ids)
    chains, used = _hidden_chains(truth_flows, measured)
    if len(chains) != 1:
        return None
    (a, b), chain = next(iter(chains.items()))
    if "time" in chain:                                   # a compiled DELAYn chain: not this shape
        return None
    h = chain["via"]
    if any(f.get("effects") or f.get("uses") or float(f.get("ratio") or 1) != 1 for f in chain["in"] + chain["out"]):
        return None
    if any((f.get("from") == h or f.get("to") == h) and i not in used for i, f in enumerate(truth_flows)):
        return None
    rest = [f for i, f in enumerate(truth_flows) if i not in used]
    ia, ib = ids.index(a), ids.index(b)
    per: dict[str, list[float]] = {k: [] for k in ("cA", "cB", "kin", "kAo", "d", "kb")}
    for w in wins:
        sys_ = linear_system(rest, ids, w)
        if sys_ is None:
            return None
        Bm, u = sys_
        if abs(Bm[ia, ib]) > 1e-12 or abs(Bm[ib, ia]) > 1e-12:
            return None
        forms_in = [form_over(f, *w) for f in chain["in"]]
        forms_out = [form_over(f, *w) for f in chain["out"]]
        if any(lf is None or lf[0] or set(lf[1]) - {a} for lf in forms_in):
            return None
        if any(lf is None or lf[0] or set(lf[1]) - {h} for lf in forms_out):
            return None
        per["kin"].append(sum(lf[1].get(a, 0.0) for lf in forms_in))
        per["d"].append(sum(lf[1].get(h, 0.0) for lf in forms_out))
        per["cA"].append(float(u[ia]))
        per["cB"].append(float(u[ib]))
        per["kAo"].append(float(-Bm[ia, ia]))
        per["kb"].append(float(-Bm[ib, ib]))
    for k in ("kin", "kAo", "d", "kb"):
        if any(abs(v - per[k][0]) > 1e-12 for v in per[k]) or per[k][0] < 0:
            return None
    if not 0 < per["d"][0] < 1 or per["kin"][0] <= 0:
        return None
    return {"A": a, "B": b, "H": h, **per}


def _fit(truth_flows: list[dict], data: dict, wins: list[tuple[int, int]]) -> dict | None:
    ids = list(data["levels"])
    chains, used = _hidden_chains(truth_flows, set(ids))
    if chains and all(a is None for a, _ in chains):
        inputs = [k for k in (data.get("inputs") or {}) if k not in ids]
        st = _structure_out(truth_flows, ids, wins, chains, used, inputs)
        return None if st is None else _fit_out(st, data, wins)
    st = _structure(truth_flows, ids, wins)
    t = data["t"]
    if st is None or len(t) < 10:
        return None
    A = np.ascontiguousarray(data["levels"][st["A"]], dtype=float)
    B = np.ascontiguousarray(data["levels"][st["B"]], dtype=float)
    if data.get("injections"):
        return None
    counts = bool(np.all(A == np.round(A)) and np.all(B == np.round(B)))
    steps = np.asarray(t[1:])
    win = np.zeros(len(steps), dtype=int)
    for w, (lo, hi) in enumerate(wins):
        win[(steps >= lo) & (steps <= hi)] = w
    W = len(wins)
    # the free numbers: (name, window or None, truth's value)
    names: list[tuple[str, int | None, float]] = []
    for k in ("cA", "cB"):
        vals = st[k]
        if any(abs(v) > 0 for v in vals):
            if any(abs(v - vals[0]) > 1e-12 for v in vals):
                names += [(k, w, vals[w]) for w in range(W)]
            else:
                names.append((k, None, vals[0]))
    for k in ("kin", "kAo", "d", "kb"):
        if k in ("kin", "d") or abs(st[k][0]) > 0:
            names.append((k, None, st[k][0]))
    hidden = data.get("all_levels", {}).get(st["H"])
    h0 = float(hidden[0]) if hidden is not None and len(hidden) else 0.0
    names.append(("m0", None, h0))
    x0 = np.array([v for _, _, v in names], dtype=float)
    rates = ("kin", "kAo", "d", "kb")
    scale = np.array([abs(v) if k in rates else max(abs(v), 1.0) for k, _, v in names])    # every number near 1
    n = 2 * (len(A) - 1)
    P0 = 1e-9

    def unpack(x):
        p = {"cA": np.zeros(len(A) - 1), "cB": np.zeros(len(A) - 1), "kin": 0.0, "kAo": 0.0, "d": 0.0, "kb": 0.0, "m0": 0.0}
        for (k, w, _), v in zip(names, x):
            if k in ("cA", "cB"):
                if w is None:
                    p[k][:] = v
                else:
                    p[k][win == w] = v
            else:
                p[k] = float(v)
        return p

    def nll(y):
        x = y * scale
        p = unpack(x)
        if not (0 < p["d"] < 1) or p["kin"] <= 0 or p["kAo"] < 0 or p["kb"] < 0:
            return 1e300
        ss, ld = _filter(A, B, p["cA"], p["cB"], p["kin"], p["kAo"], p["d"], p["kb"], p["m0"], P0)
        if counts:
            return 0.5 * (ss + ld)
        return 0.5 * (n * math.log(max(ss / n, 1e-300)) + ld)

    bounds = []
    for (k, _, _), s in zip(names, scale):
        lo = {"kin": 1e-6, "d": 1e-6, "kAo": 0.0, "kb": 0.0, "m0": 0.0}.get(k)
        hi = 0.999 if k == "d" else None
        bounds.append((None if lo is None else lo / s, None if hi is None else hi / s))
    y0 = x0 / scale
    res = minimize(nll, y0, method="L-BFGS-B", bounds=bounds, options={"maxiter": 500})
    y = res.x
    f0 = nll(y)
    if not math.isfinite(f0) or f0 >= 1e299:
        return None
    # a number at its bound (H's start at 0) is held there: the curvature is taken over the others
    free = [i for i, (lo, hi) in enumerate(bounds) if not ((lo is not None and y[i] - lo < 1e-6) or (hi is not None and hi - y[i] < 1e-6))]
    k = len(free)
    H = np.zeros((k, k))
    hstep = 1e-2                 # 1e-4 measured the kink at the variance floor, not the curvature (docs/research/review-hidden-oracle.md)

    def at(i, si, j=None, sj=0.0):
        z = y.copy()
        z[free[i]] += si
        if j is not None:
            z[free[j]] += sj
        return nll(z)

    for i in range(k):
        for j in range(i, k):
            if i == j:
                v = (at(i, hstep) - 2 * f0 + at(i, -hstep)) / hstep ** 2
            else:
                v = (at(i, hstep, j, hstep) - at(i, hstep, j, -hstep) - at(i, -hstep, j, hstep) + at(i, -hstep, j, -hstep)) / (4 * hstep ** 2)
            H[i, j] = H[j, i] = v
    try:
        evals = np.linalg.eigvalsh(H)
        if not np.all(np.isfinite(evals)) or evals.min() <= 0:
            return None
        cov = np.linalg.inv(H)
    except np.linalg.LinAlgError:
        return None
    se = np.zeros(len(y))
    se[free] = np.sqrt(np.diag(cov)) * scale[free]
    est = y * scale
    out: dict = {"A": st["A"], "B": st["B"], "W": W}
    for (name, w, _), e, s in zip(names, est, se):
        for ww in range(W) if w is None else [w]:
            out.setdefault(name, {"est": [None] * W, "se": [None] * W})
            out[name]["est"][ww], out[name]["se"][ww] = float(e), float(s)
    d = out["d"]
    out["delay"] = {"est": [1 / x for x in d["est"]], "se": [s / (x * x) for x, s in zip(d["est"], d["se"])]}
    return out


def _key(truth_flows, data, wins) -> str:
    h = hashlib.sha256()
    h.update(json.dumps(truth_flows, sort_keys=True, default=str).encode())
    h.update(json.dumps(wins).encode())
    h.update(np.asarray(data["t"], dtype=float).tobytes())
    for s in sorted(data["levels"]):
        h.update(s.encode())
        h.update(np.asarray(data["levels"][s], dtype=float).tobytes())
    h.update(json.dumps(data.get("injections") or []).encode())
    h.update(json.dumps(data.get("inputs") or {}, sort_keys=True).encode())
    return h.hexdigest()


class HiddenOracle:
    def __init__(self, truth_flows: list[dict], data: dict, wins: list[tuple[int, int]], noise: str):
        self.fit = None
        if noise != "none":
            key = _key(truth_flows, data, wins)
            if key not in _CACHE:
                _CACHE[key] = _fit(truth_flows, data, wins)
            self.fit = _CACHE[key]
        self.ok = self.fit is not None

    def _se(self, name: str, window: int) -> float | None:
        v = (self.fit or {}).get(name)
        return None if v is None else v["se"][window]

    def part_se(self, key: tuple, window: int) -> float | None:
        """A true part's standard error in a window; None for a part the oracle has no number for."""
        if not self.ok:
            return None
        if "A" not in self.fit:                              # a hidden stock fed from outside into B
            return self._part_se_out(key, window)
        A, B = self.fit["A"], self.fit["B"]
        if key[0] != "flow":
            return None
        _, a, b, j = key
        if j == ONE and None in (a, b) and A in (a, b):
            return self._se("cA", window)
        if j == ONE and None in (a, b) and B in (a, b):
            return self._se("cB", window)
        if (a, b, j) == (A, None, A):
            return self._se("kAo", window)
        if (a, b, j) == (B, None, B):
            return self._se("kb", window)
        return None

    def _part_se_out(self, key: tuple, window: int) -> float | None:
        B = self.fit["B"]
        if key[0] == "via" and key[1] is None and key[2] == B:
            return self._se("cin" if key[3] == ONE else f"k:{key[3]}", window)
        if key[0] != "flow":
            return None
        _, a, b, j = key
        if j == ONE and None in (a, b) and B in (a, b):
            return self._se("cB", window)
        if (a, b, j) == (B, None, B):
            return self._se("kb", window)
        return None

    def hidden_se(self, key: tuple, window: int) -> dict | None:
        """{"k_in", "delay"} standard errors of the hidden part (A, B) in a window ({"delay"} for a path
        fed from outside)."""
        if not self.ok or key[0] != "hidden":
            return None
        if "A" not in self.fit:
            return {"delay": self._se("delay", window)} if (key[1], key[2]) == (None, self.fit["B"]) else None
        if (key[1], key[2]) != (self.fit["A"], self.fit["B"]):
            return None
        return {"k_in": self._se("kin", window), "delay": self._se("delay", window)}
