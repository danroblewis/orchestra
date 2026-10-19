"""A stage's numbers refitted by a Kalman filter's likelihood, for counts (stage.py chooses its terms).

The least-squares profile treats the hidden chain as a fixed filter of what feeds it; with counts,
the chain's own flows are counts too, so its levels wander from that filter, and the regression
reads the delay and the drain off by more than the data's own error. Here the chain (n stages) is
the state; each step every flow is a count around its rate (variance = rate) and its noise is
shared by both its ends: what entered H_1 (from outside, or from X: rework), what moved between
stages, what reached X from H_n, X's drain and its direct terms. X's change is observed; the chain is
corrected by it. Kept flows (moves to other measured stocks) add their gross amount to X's variance.
"""

from __future__ import annotations

import math

import numpy as np
from numba import njit
from scipy.optimize import minimize

from .stage import is_move

FLOOR = 0.05


@njit(cache=True)
def _nll(dX, X, U, Wd, gross, d, kX, move, h0, n):
    """-2 log-likelihood (up to a constant) of X's changes. U: what enters H_1 each step; Wd: the
    direct terms' net amount each step; gross: the kept flows' gross amount through X. State index
    n is X's change."""
    T = dX.shape[0]
    m = h0.copy()
    mn = np.empty(n)
    P = np.zeros((n, n))
    C = np.zeros((n + 1, n + 1))
    for i in range(n):
        P[i, i] = max(1.0, abs(h0[i]))
    ss = 0.0
    ld = 0.0
    for t in range(T):
        u = U[t]
        for i in range(n):
            mn[i] = (1.0 - d) * m[i] + (d * m[i - 1] if i > 0 else u)
        mux = d * m[n - 1] - kX * X[t] + Wd[t] - (u if move else 0.0)
        # propagated covariance: G P G^T, G's rows: stage i = (1-d) e_i + d e_(i-1); X's change = d e_(n-1)
        for i in range(n + 1):
            for j in range(n + 1):
                acc = 0.0
                for k in range(n):
                    gi = (1.0 - d if k == i else 0.0) + (d if k == i - 1 else 0.0) if i < n else (d if k == n - 1 else 0.0)
                    if gi == 0.0:
                        continue
                    for q in range(n):
                        gj = (1.0 - d if q == j else 0.0) + (d if q == j - 1 else 0.0) if j < n else (d if q == n - 1 else 0.0)
                        if gj != 0.0:
                            acc += gi * P[k, q] * gj
                C[i, j] = acc
        # each flow's count noise, on both its ends
        vin = max(abs(u), FLOOR)
        C[0, 0] += vin
        if move:
            C[n, n] += vin
            C[0, n] -= vin
            C[n, 0] -= vin
        for i in range(n):
            v = max(d * max(m[i], 0.0), FLOOR)
            j = i + 1
            C[i, i] += v
            C[j, j] += v
            C[i, j] -= v
            C[j, i] -= v
        C[n, n] += max(kX * X[t], 0.0) + abs(Wd[t]) + gross[t] + FLOOR
        S = C[n, n]
        e = dX[t] - mux
        ss += e * e / S
        ld += math.log(S)
        for i in range(n):
            m[i] = mn[i] + C[i, n] / S * e
        for i in range(n):
            for j in range(n):
                P[i, j] = C[i, j] - C[i, n] * C[j, n] / S
            if P[i, i] < 1e-9:
                P[i, i] = 1e-9
    return ss + ld


def refine(fit: dict, y: np.ndarray, X: np.ndarray, cands: dict, direct: dict, gross: np.ndarray, x: str) -> dict:
    """The stage's numbers (rate per stage, u's terms, X's drain, the direct terms, the starting
    levels) by the filter's likelihood, from the least-squares fit; the fit unchanged if it does not
    improve."""
    n = fit["n"]
    terms, dterms = list(fit["terms"]), list(fit["direct"])
    Z = np.array([cands[s] for s in terms])
    Wm = np.array([direct[s] for s in dterms]).reshape(len(dterms), len(y))
    drained = fit["kX"] != 0.0
    move = is_move(fit, x)                                      # X -> H, X's own drain beside it (>= 0)
    y, X, gross = (np.ascontiguousarray(v, dtype=float) for v in (y, X, gross))

    def unpack(p):
        d = 0.9 / (1.0 + math.exp(-max(-50.0, min(50.0, p[0]))))
        a = np.asarray(p[1 : 1 + len(terms)])
        i = 1 + len(terms)
        kX = math.exp(max(-30.0, min(3.0, p[i]))) if drained else 0.0
        i += drained
        b = np.asarray(p[i : i + len(dterms)])
        h0 = np.asarray(p[i + len(dterms) :], dtype=float)
        return d, a, kX, b, h0

    def cost(p):
        d, a, kX, b, h0 = unpack(p)
        U = np.ascontiguousarray(a @ Z)
        Wd = np.ascontiguousarray(b @ Wm) if len(dterms) else np.zeros(len(y))
        v = _nll(y, X, U, Wd, gross, d, kX, move, np.ascontiguousarray(h0), n)
        return v if math.isfinite(v) else 1e300

    dd = min(0.899, max(1e-4, fit["d"]))
    own = max(1e-4 * fit["kX"], fit["kX"] - fit["terms"][x]) if move else fit["kX"]
    drained = drained or move
    x0 = [math.log(dd / (0.9 - dd))] + [fit["terms"][s] for s in terms] + ([math.log(own)] if drained else [])
    x0 += [fit["direct"][s] for s in dterms] + list(fit["start"])
    x0 = np.array(x0, dtype=float)
    c0 = cost(x0)
    o = minimize(cost, x0, method="Nelder-Mead", options={"maxfev": 3000, "xatol": 1e-7, "fatol": 1e-6, "adaptive": True})
    o2 = minimize(cost, o.x, method="L-BFGS-B", options={"maxiter": 300})
    best = o2 if o2.fun < o.fun else o
    if not best.fun < c0:
        return fit
    d, a, kX, b, h0 = unpack(best.x)
    terms_out = dict(zip(terms, a.tolist()))
    return {**fit, "d": d, "terms": terms_out, "kX": kX + (terms_out[x] if move else 0.0), "direct": dict(zip(dterms, b.tolist())),
            "start": h0.tolist(), "kf": True}
