"""A row's numbers measured on short stretches, each with its own outside inflow.

A drain fitted over the whole run is biased by everything else that moves the level slowly: an
outside inflow that changes (more arrives, the level settles higher, yet the level does not drain any
faster than before), or a stretch where a flow is capped (a stock run dry: the level climbs while the
row says it should fall). Within a short stretch the outside inflow is nearly constant, and what is
left is how the level's own wiggles feed back: the drain. So the run is cut into stretches of fixed
length, each fitted on its own with its own intercept, and the numbers are the median over stretches
(a pooled fit would be ruled by the few stretches where the level moves most, which are the capped
ones). Stretches where the row does not hold are then found by counting noise (counting.py): their
residuals vary far more than the throughput the row implies there, and they are left out of the
median (bisquare weights on that ratio, relative to the run's median).
"""

from __future__ import annotations

import numpy as np

from .counting import gross


def blocks(T: int, length: int) -> list[int]:
    cuts = list(range(0, T, length)) + [T]
    if len(cuts) > 2 and cuts[-1] - cuts[-2] < length // 2:
        cuts.pop(-2)
    return cuts


def weighted_median(v: np.ndarray, w: np.ndarray) -> float:
    o = np.argsort(v)
    c = np.cumsum(w[o])
    return float(v[o][np.searchsorted(c, 0.5 * c[-1])])


def stretch_fit(y: np.ndarray, X: np.ndarray, length: int = 25, iters: int = 3, c: float = 4.0, own: int | None = None) -> dict:
    """y (steps), X (columns x steps): each number the weighted median of its fits within stretches
    of `length` steps (longer with many columns); own: the column that is the stock's own level. Returns {"beta", "weights", "cuts", "per"}."""
    T = y.shape[0]
    p = X.shape[0]
    cuts = blocks(T, max(length, 6 * (p + 1)))
    nb = len(cuts) - 1
    if not p:
        return {"beta": np.zeros(0), "weights": np.ones(nb), "cuts": cuts, "per": np.zeros((nb, 0))}
    per = np.zeros((nb, p))
    ok = np.ones(nb, bool)
    for b, (a, e) in enumerate(zip(cuts[:-1], cuts[1:])):
        Xb = X[:, a:e] - X[:, a:e].mean(axis=1, keepdims=True)
        yb = y[a:e] - y[a:e].mean()
        G = Xb @ Xb.T
        if np.linalg.matrix_rank(G) < p:
            ok[b] = False
            continue
        per[b] = np.linalg.solve(G, Xb @ yb)
        if own is not None:
            # a short stretch's own intercept biases the level's feedback on itself towards a faster
            # drain (Hurwicz / Kendall: phi is found low by (1 + 3 phi) / n); undone to first order
            n = e - a
            phi = 1 + per[b, own]
            per[b, own] = (n * phi + 1) / (n - 3) - 1
    w = ok.astype(float)
    if not ok.any():
        return {"beta": np.zeros(p), "weights": w, "cuts": cuts, "per": per}
    beta = np.array([weighted_median(per[:, q], w) for q in range(p)])
    seg = np.repeat(np.arange(nb), np.diff(cuts))
    lens = np.diff(cuts)
    for _ in range(iters):
        fit = y - beta @ X
        a = np.add.reduceat(fit, cuts[:-1]) / lens
        r = fit - a[seg]
        g = gross(beta, X, a[seg])
        rho = (np.add.reduceat(r * r, cuts[:-1]) / lens) / (np.add.reduceat(g, cuts[:-1]) / lens)
        ref = float(np.median(rho[ok]))
        q = rho / max(ref, 1e-12) / c
        nw = np.where(ok & (q < 1), (1 - q * q) ** 2, 0.0)
        if nw.sum() < 0.25 * ok.sum():
            break
        w = nw
        nbeta = np.array([weighted_median(per[:, k], w) for k in range(p)])
        if np.allclose(nbeta, beta):
            break
        beta = nbeta
    return {"beta": beta, "weights": w, "cuts": cuts, "per": per}
