"""A row's change as a piecewise-linear curve of the row's own level, with free points.

The curve g(x) through points (a_k, w_k) is sum_k w_k h_k(x), h_k the tent that is 1 at a_k and 0 at
its neighbours (flat beyond the end points, as an SD Lab table effect is), so for fixed points the
values are a least-squares fit, beside any other columns (levels of other stocks, measured inputs).

The points are found by backward elimination from a dense grid over the level's range (quantiles
and even spacing), each count's points then moved continuously (Nelder-Mead) to where the curve
bends, and the count chosen by BIC (a value and, between the ends, a position per point). A segment
must hold at least `support` steps, so the curve is never bent where the run has not been.
"""

from __future__ import annotations

import math

import numpy as np
from scipy.optimize import minimize


def hats(x: np.ndarray, kn: np.ndarray) -> np.ndarray:
    """K x n: tent k of every value of x (flat beyond the end points)."""
    x = np.clip(np.asarray(x, dtype=float), kn[0], kn[-1])
    K = len(kn)
    out = np.zeros((K, x.shape[0]))
    i = np.clip(np.searchsorted(kn, x, side="right") - 1, 0, K - 2)
    w = (x - kn[i]) / np.maximum(1e-12, kn[i + 1] - kn[i])
    out[i, np.arange(x.shape[0])] = 1 - w
    out[i + 1, np.arange(x.shape[0])] += w
    return out


def fit(y: np.ndarray, x: np.ndarray, kn: np.ndarray, Z: np.ndarray, wt: np.ndarray | None = None) -> tuple[np.ndarray, float]:
    """(the curve's values then Z's numbers, the weighted rss)."""
    A = np.vstack([hats(x, kn), Z]).T if len(Z) else hats(x, kn).T
    if wt is not None:
        A, y = A * wt[:, None], y * wt
    b = np.linalg.lstsq(A, y, rcond=None)[0]
    r = y - A @ b
    return b, float(r @ r)


def _supported(x: np.ndarray, kn: np.ndarray, support: int) -> bool:
    counts = np.histogram(x, bins=kn)[0]
    return bool(np.all(counts >= support))


def search(y: np.ndarray, x: np.ndarray, Z: np.ndarray, floor: float, wt: np.ndarray | None = None, grid: int = 40,
           support: int | None = None, most: int = 12, refine: int = 8, max_steps: int = 2000) -> dict | None:
    """The best curve by BIC: {knots, values, z (Z's numbers), rss, bic, line_bic}; None if the level
    barely moves."""
    T = len(y)
    lo, hi = float(np.min(x)), float(np.max(x))
    if hi - lo <= 1e-9 * max(1.0, abs(hi)):
        return None
    support = support or max(10, T // 100)
    M = len(Z)
    g = np.unique(np.concatenate([np.quantile(x, np.linspace(0, 1, grid // 2 + 1)), np.linspace(lo, hi, grid // 2 + 1)]))
    kn = [lo]
    for v in g[1:-1]:
        if v - kn[-1] > 2e-3 * (hi - lo) and hi - v > 2e-3 * (hi - lo):
            kn.append(float(v))
    kn = np.array(kn + [hi])
    # the grid's points where the run has barely been go first
    while len(kn) > 2 and not _supported(x, kn, support):
        counts = np.histogram(x, bins=kn)[0]
        j = int(np.argmin(counts))
        kn = np.delete(kn, j + 1 if j + 1 < len(kn) - 1 else j)

    def bic(rss: float, K: int) -> float:
        return T * math.log(max(rss, floor) / T) + (K + max(0, K - 2) + M) * math.log(T)

    # a long run: the points are chosen on every n-th step (the rss scaled back up), the values on all
    full = (y, x, Z, wt)
    n = max(1, T // max_steps)
    if n > 1:
        y, x, Z, wt = y[::n], x[::n], Z[:, ::n], None if wt is None else wt[::n]
        support = max(2, support // n)

    path = {len(kn): (n * fit(y, x, kn, Z, wt)[1], kn)}
    while len(kn) > 2:
        best = None
        for j in range(1, len(kn) - 1):
            k2 = np.delete(kn, j)
            r = n * fit(y, x, k2, Z, wt)[1]
            if best is None or r < best[0]:
                best = (r, k2)
        kn = best[1]
        path[len(kn)] = best
    # each small count's points moved to where the curve bends
    gap = 1e-3 * (hi - lo)
    for K in sorted(path):
        if K <= 2 or K > refine:
            continue
        rss0, k0 = path[K]

        def obj(v):
            k2 = np.concatenate([[lo], np.sort(np.clip(v, lo, hi)), [hi]])
            if np.any(np.diff(k2) < gap) or not _supported(x, k2, support):
                return rss0 * 10 + 1.0
            return n * fit(y, x, k2, Z, wt)[1]

        res = minimize(obj, k0[1:-1], method="Nelder-Mead", options={"xatol": 1e-7 * (hi - lo), "fatol": 1e-14, "maxiter": 150 * K})
        if res.fun < rss0:
            path[K] = (float(res.fun), np.concatenate([[lo], np.sort(np.clip(res.x, lo, hi)), [hi]]))
    K = min((k for k in path if k <= most), key=lambda k: bic(path[k][0], k))
    rss, kn = path[K]
    y, x, Z, wt = full
    b, rss = fit(y, x, kn, Z, wt)
    line = fit(y, x, np.array([lo, hi]), Z, wt)[1]
    return {"knots": kn, "values": b[:K], "z": b[K:], "rss": rss, "bic": bic(rss, K), "line_bic": bic(line, 2), "line_rss": line}
