"""A row's outside inflow: is it white without pieces, and its pieces pooled into a few values.

- white(): Ljung-Box (from earned_pieces/rows.py at commit aad5c7b). Chance pieces leave white
  residuals behind; an inflow that really changes leaves a slow pattern, even when no single change
  pays a textbook price.
- pool_recut(): many pieces of a stock that relaxes inside each of them take up part of its drain
  (with a value per stretch, the drain reads fast under counting noise: case 027). The pieces' values
  are pooled into 1..most values (weighted k-means), every step assigned again to a value (Viterbi,
  a change costing `change` x log T in the row's noise), the row's numbers refitted with the steps
  within `guard` of a change left out (a change placed a step late moves the drain by ~10%), a few
  rounds. The idea and the Viterbi/k-means are effect_hats/pieces.py's (commit aad5c7b), here
  applied to one row's regression rather than to a model's flows.

  Guarded against seasonal inflows (which a few values cannot follow): the pooled inflow is kept only
  when it prices better than the pieces themselves at the same price (one number per value and per
  change, `level_price` x log T more per value beyond the first), and leaves residuals as white as
  the pieces did (need_white, opts "pool_white": as white as white noise, whatever the pieces left:
  an inflow changing every 30 steps, sd-pipeline, pooled into a few values leaves a slow pattern).
"""

from __future__ import annotations

import math

import numpy as np
from numba import njit
from scipy.stats import chi2

ALPHA = 0.01


def white(e: np.ndarray, alpha: float = ALPHA) -> bool:
    """Ljung-Box: no autocorrelation in e up to lag ceil(sqrt(T)) at level alpha."""
    e = np.asarray(e, dtype=float) - float(np.mean(e))
    n = e.shape[0]
    v = float(e @ e)
    if n < 10 or v <= 0:
        return True
    m = min(n - 2, int(math.ceil(math.sqrt(n))))
    r = np.array([float(e[k:] @ e[:-k]) / v for k in range(1, m + 1)])
    q = n * (n + 2) * float(np.sum(r * r / (n - np.arange(1, m + 1))))
    return bool(chi2.sf(q, m) > alpha)


@njit(cache=True)
def _viterbi(u: np.ndarray, levels: np.ndarray, change: float) -> np.ndarray:
    """The state (index into levels) of each step: least squares to its level plus `change` per switch."""
    n, m = u.shape[0], levels.shape[0]
    acc = (u[0] - levels) ** 2
    back = np.zeros((n, m), dtype=np.int64)
    for t in range(1, n):
        best = 0
        for j in range(1, m):
            if acc[j] < acc[best]:
                best = j
        move = acc[best] + change
        nacc = np.empty(m)
        for j in range(m):
            if acc[j] <= move:
                back[t, j] = j
                nacc[j] = acc[j]
            else:
                back[t, j] = best
                nacc[j] = move
            nacc[j] += (u[t] - levels[j]) ** 2
        acc = nacc
    path = np.zeros(n, dtype=np.int64)
    best = 0
    for j in range(1, m):
        if acc[j] < acc[best]:
            best = j
    path[n - 1] = best
    for t in range(n - 1, 0, -1):
        path[t - 1] = back[t, path[t]]
    return path


def _kmeans(x: np.ndarray, w: np.ndarray, k: int) -> np.ndarray:
    order = np.argsort(x)
    cw = np.cumsum(w[order]) / w.sum()
    c = np.array([x[order][min(len(x) - 1, int(np.searchsorted(cw, (q + 0.5) / k)))] for q in range(k)], dtype=float)
    for _ in range(20):
        lab = np.argmin(np.abs(x[:, None] - c[None, :]), axis=1)
        new = np.array([np.average(x[lab == q], weights=w[lab == q]) if np.any(lab == q) else c[q] for q in range(k)])
        if np.allclose(new, c):
            break
        c = new
    return np.unique(np.round(c, 12))


def _segments(path: np.ndarray) -> list[tuple[int, int]]:
    T = len(path)
    edges = [0] + [k for k in range(1, T) if path[k] != path[k - 1]] + [T]
    return list(zip(edges[:-1], edges[1:]))


def _fit(y: np.ndarray, X: np.ndarray, path: np.ndarray, m: int, guard: int):
    """Least squares of y on X and one indicator per value, without the steps near a change."""
    T = len(y)
    D = np.zeros((m, T))
    D[path, np.arange(T)] = 1.0
    Z = np.vstack([X, D])
    keep = np.ones(T, bool)
    for a, _ in _segments(path)[1:]:
        keep[max(0, a - guard): a + guard] = False
    if keep.sum() < Z.shape[0] + 5 or np.any(D[:, keep].sum(axis=1) == 0):
        keep[:] = True
    Zk, yk = Z[:, keep], y[keep]
    G = Zk @ Zk.T
    G[np.diag_indices_from(G)] += 1e-9 * (np.abs(np.diag(G)) + 1)
    try:
        inv = np.linalg.inv(G)
    except np.linalg.LinAlgError:
        inv = np.linalg.pinv(G)
    theta = inv @ (Zk @ yk)
    rk = yk - theta @ Zk
    s2 = float(rk @ rk) / max(1, int(keep.sum()) - Z.shape[0])
    se = np.sqrt(np.maximum(0, np.diag(inv)) * s2)
    k = X.shape[0]
    return theta[:k], theta[k:], se[:k]


def pool_recut(y: np.ndarray, X: np.ndarray, cuts: list[int], floor: float = 0.0, most: int = 4, change: float = 2.0,
               guard: int = 2, level_price: float = 2.0, alpha: float = ALPHA, need_white: bool = False) -> dict | None:
    """The row y ~ X (the chosen columns) + pieces at `cuts`, with its pieces pooled and re-cut: {beta,
    rss, se, cuts, segments [(a, b, value)], labels (each step's value index)}, or None when the
    pieces themselves price better or the pooled inflow leaves residuals less white."""
    T = len(y)
    logT = math.log(T)
    k = X.shape[0]
    n = len(cuts) - 1
    lab0 = np.repeat(np.arange(n), np.diff(cuts))
    b0, v0, _ = _fit(y, X, lab0, n, 0)
    e0 = y - (b0 @ X if k else 0.0) - v0[lab0]
    rss0 = float(e0 @ e0)
    price = lambda rss, values, changes: T * math.log(max(rss, floor, 1e-12) / T) + (k + values + changes + level_price * (values - 1)) * logT  # noqa: E731
    p0 = price(rss0, n, n - 1) - level_price * (n - 1) * logT      # the pieces: a value and a change each
    w = np.diff(cuts).astype(float)
    best = None
    for m in range(1, min(most, n) + 1):
        levels = _kmeans(v0, w, m)
        beta = b0
        s2 = max(1e-12, rss0 / T)
        for _ in range(4):
            u = y - (beta @ X if k else 0.0)
            path = _viterbi(np.ascontiguousarray(u, dtype=float), np.ascontiguousarray(levels, dtype=float), change * s2 * logT)
            used = np.unique(path)
            path = np.searchsorted(used, path)
            beta, new, se = _fit(y, X, path, len(used), guard)
            done = len(new) == len(levels) and np.allclose(new, levels, rtol=1e-6, atol=1e-9)
            levels = new
            r = y - (beta @ X if k else 0.0) - levels[path]
            s2 = max(1e-12, float(r @ r) / T)
            if done:
                break
        order = np.argsort(levels)
        levels, path = levels[order], np.argsort(order)[path]
        e = y - (beta @ X if k else 0.0) - levels[path]
        rss = float(e @ e)
        segs = _segments(path)
        sc = price(rss, len(levels), len(segs) - 1)
        if best is None or sc < best["sc"]:
            best = {"sc": sc, "beta": beta, "se": se, "rss": rss, "labels": path, "levels": levels, "e": e, "segs": segs}
    if best is None or best["sc"] >= p0:
        return None
    if (need_white or white(e0, alpha)) and not white(best["e"], alpha):
        return None
    segs = best["segs"]
    return {"beta": best["beta"], "se": best["se"], "rss": best["rss"], "cuts": [a for a, _ in segs] + [T],
            "segments": [(a, b, float(best["levels"][best["labels"][a]])) for a, b in segs], "labels": best["labels"]}
