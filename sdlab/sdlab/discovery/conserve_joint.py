"""Conservation as equality constraints across rows, solved jointly with PySINDy's ConstrainedSR3.

What leaves a stock through a term (k x A, or k x A x C) and arrives in same-unit stocks arrives at
the same number: xi[A][f] + sum over receivers r of xi[r][f] = 0. The rows are fitted together, each
scaled by its own noise, so the constraint takes each number from the rows that measure it best (a
precise source row fixes a receiver whose row cannot tell two collinear levels apart, and the other
way round). Each row keeps the terms its sparse fit chose (the others are held at 0 by equality
constraints); a conservation constraint is kept only if it costs the joint fit less than log T.
"""

from __future__ import annotations

import math
import warnings

import numpy as np
from pysindy.optimizers import ConstrainedSR3

from .library import factors


def _solve(R: np.ndarray, Z: np.ndarray, zeros: list[tuple[int, int]], sums: list[list[tuple[int, float]]], n: int, S: int) -> np.ndarray:
    """min sum_s |Z_s - R w_s|^2 subject to w[s, q] = 0 for (s, q) in zeros and, for each list in
    sums, sum of weight x w[s, q] = 0; w is S x n (targets x features)."""
    rows = []
    for s, q in zeros:
        r = np.zeros(S * n)
        r[s * n + q] = 1.0
        rows.append(r)
    for terms in sums:
        r = np.zeros(S * n)
        for (s, q), wgt in terms:
            r[s * n + q] = wgt
        rows.append(r)
    if not rows:
        return np.linalg.lstsq(R, Z, rcond=None)[0].T
    C = np.array(rows)
    opt = ConstrainedSR3(reg_weight_lam=0.0, regularizer="l0", relax_coeff_nu=1e9, tol=1e-12, max_iter=50,
                         constraint_lhs=C, constraint_rhs=np.zeros(len(rows)), constraint_order="target", equality_constraints=True)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        opt.fit(R, Z)
    return np.asarray(opt.coef_full_)


def conserve(rows: list[dict], terms: list[tuple], X: np.ndarray, dy: np.ndarray, u: np.ndarray, unit: list[str], final: set[int]) -> dict:
    """rows: each {"terms": [term index], "beta": [...]} from the sparse fits; X: library values
    (terms x steps); u: each row's outside inflow (stocks x steps), taken as known. Updates the rows'
    numbers in place; returns what was tried and kept."""
    S, T = dy.shape
    used = sorted({f for r in rows for f in r["terms"]})
    if not used:
        return {"kept": [], "tried": 0}
    n = len(used)
    pos = {f: q for q, f in enumerate(used)}
    A = X[used]
    d = np.sqrt((A * A).sum(axis=1))
    d[d == 0] = 1.0
    As = A / d[:, None]
    yz = dy - u
    sig = np.array([math.sqrt(max(r["rss"], 1e-12) / T) for r in rows])
    G = As @ As.T + 1e-10 * np.eye(n)
    try:
        R = np.linalg.cholesky(G).T
    except np.linalg.LinAlgError:
        w, V = np.linalg.eigh(G)
        R = (V * np.sqrt(np.maximum(w, 0))).T
    Z = np.linalg.lstsq(R.T, As @ (yz / sig[:, None]).T, rcond=None)[0]       # n x S
    zeros = [(s, q) for s in range(S) for q in range(n) if used[q] not in rows[s]["terms"]]

    def cost(W):
        return float(((Z - R @ W.T) ** 2).sum())

    def to_xi(W):                                         # back to numbers per step
        return W * sig[:, None] / d[None, :]

    base = _solve(R, Z, zeros, [], n, S)
    c0 = cost(base)
    xi = to_xi(base)
    cands = []
    for f in used:
        q = pos[f]
        v = {s: xi[s, q] for s in range(S) if used[q] in rows[s]["terms"]}
        srcs = [a for a in dict.fromkeys(factors(terms[f])) if v.get(a, 0) < 0 and a not in final]
        for a in srcs:
            recv = [s for s, k in v.items() if s != a and k > 0 and unit[s] == unit[a]]
            if recv:
                cands.append((f, [((a, q), sig[a] / d[q])] + [((s, q), sig[s] / d[q]) for s in recv]))
                break
    log_t = math.log(T)
    kept = []
    for f, c in cands:
        W = _solve(R, Z, zeros, [c], n, S)
        if cost(W) - c0 < log_t:
            kept.append((f, c))
    if kept:
        W = _solve(R, Z, zeros, [c for _, c in kept], n, S)
        if cost(W) - c0 > log_t * len(kept):          # together they do not hold: keep the cheapest half
            costs = sorted(kept, key=lambda fc: cost(_solve(R, Z, zeros, [fc[1]], n, S)))
            kept = costs[: max(1, len(kept) // 2)]
            W = _solve(R, Z, zeros, [c for _, c in kept], n, S)
        xi = to_xi(W)
    else:
        xi = to_xi(base)
    for s, r in enumerate(rows):
        r["beta"] = [float(xi[s, pos[f]]) for f in r["terms"]]
    return {"kept": [f for f, _ in kept], "tried": len(cands)}
