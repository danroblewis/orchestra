"""Fitting one stock's row: which levels and inputs its change follows, and its outside inflow.

The matrix method's row (sdlab/discovery/matrix.py fit_row, at 76d41ae), with the same choices
(stepwise by BIC, an outside inflow that is none, a constant, or pieces found by PELT in what the
levels leave unexplained, pieces only for a stock whose inflow is clearly one way), on the sums of
gram.py, so a row never re-reads the T-long columns except to take its residual.

The candidate columns are the row's screen (blocks.py): the row's own level, the inputs, and the
levels that explain its change best, so a row of a 230-stock model looks at a few dozen columns.
"""

from __future__ import annotations

import math

import numpy as np

from ...changes import pelt
from .gram import Design, bic, solve, stepwise


def scan(r: np.ndarray, mult: float, min_piece: int = 5, stride: int = 1) -> list[int]:
    """Changes in the mean of a residual series; with stride > 1 found on the means of `stride` steps
    (a long run's pieces at a fraction of the cost), cut positions mapped back to steps."""
    n = len(r)
    if stride <= 1 or n < 40 * stride:
        return pelt(r, min_piece, mult)
    m = n // stride
    agg = r[: m * stride].reshape(m, stride).mean(axis=1)
    cuts = pelt(agg, max(2, min_piece // stride), mult)
    out = [0] + [c * stride for c in cuts[1:-1]] + [n]
    return list(dict.fromkeys(out))


def fit_row(d: Design, X: np.ndarray, s: int, allowed: np.ndarray, opts: dict, positive: np.ndarray | None = None) -> dict:
    """Row s: chosen columns (indices into X), numbers in X's units, the outside inflow's pieces."""
    T = d.T
    lt = math.log(T)
    add_gain = opts.get("add_gain", lt)
    form = opts.get("inflow", "pieces")
    most = opts.get("most")
    stride = opts.get("scan_stride", 1)
    y = d.dy[s]
    cuts = [0, T] if form != "none" else None
    chosen: list[int] = []
    for p in range(opts.get("passes", 4) if form == "pieces" else 1):
        sm = d.sums(s, cuts)
        chosen = stepwise(sm, chosen, allowed, add_gain, 3 * (most or 12) + 4, most, partner=s)
        if positive is not None:
            # columns that may only add (a delayed copy is a stage that feeds the row's stock): one
            # with a negative number leaves the row's candidates and the row is chosen again
            allowed = allowed.copy()
            for _ in range(4):
                beta, _, _ = solve(sm, chosen)
                neg = [c for c, b in zip(chosen, beta) if positive[c] and b < 0]
                if not neg:
                    break
                allowed[neg] = False
                chosen = stepwise(sm, [c for c in chosen if c not in neg], allowed, add_gain, 3 * (most or 12) + 4, most, partner=s)
        if form != "pieces":
            break
        beta, _, _ = solve(sm, chosen)
        res = y - ((beta / d.scale[chosen]) @ X[chosen] if chosen else 0.0)
        nxt = scan(res, 0.5 if p == 0 else 1.0, opts.get("min_piece", 5), stride)
        if nxt == cuts and p >= 1:
            break
        cuts = nxt

    def fit(c, extra):
        sm = d.sums(s, c)
        beta, rss, inv = solve(sm, chosen)
        return {"cuts": c, "beta": beta, "rss": rss, "sc": bic(T, rss, len(chosen) + extra)}

    none = fit(None, 0)
    const = fit([0, T], 1)
    pick = none if none["sc"] <= const["sc"] else const
    if form == "none":
        pick = none
    elif form == "pieces" and cuts and len(cuts) > 2:
        pc = fit(cuts, len(cuts) - 1)
        vals = piece_values(y, X, chosen, pc["beta"] / d.scale[chosen] if chosen else np.zeros(0), cuts)
        w = np.array([v["w"] for v in vals], float)
        v = np.array([v["v"] for v in vals])
        mean = float((w * v).sum() / w.sum())
        sd = float(np.sqrt((w * (v - mean) ** 2).sum() / w.sum()))
        if (pick is const or abs(mean) > 0.5 * sd) and pc["sc"] < pick["sc"]:
            pick = pc
    beta = pick["beta"] / d.scale[chosen] if chosen else np.zeros(0)
    if positive is not None and opts.get("_depth", 0) < 3:
        neg = [c for c, b in zip(chosen, beta) if positive[c] and b < 0]
        if neg:                                     # the final fit turned a copy negative: the row again without it
            allowed = allowed.copy()
            allowed[neg] = False
            return fit_row(d, X, s, allowed, {**opts, "_depth": opts.get("_depth", 0) + 1}, positive)
    pieces = piece_values(y, X, chosen, beta, pick["cuts"]) if pick["cuts"] else []
    return {"set": chosen, "beta": beta, "cuts": pick["cuts"], "pieces": pieces, "rss": pick["rss"],
            "p": len(chosen) + (len(pick["cuts"]) - 1 if pick["cuts"] else 0)}


def piece_values(y: np.ndarray, X: np.ndarray, cols: list[int], beta: np.ndarray, cuts: list[int]) -> list[dict]:
    """Each piece's level of the outside inflow, with the columns' part taken out."""
    res = y - (beta @ X[cols] if cols else 0.0)
    return [{"a": a, "b": b, "w": b - a, "v": float(res[a:b].mean())} for a, b in zip(cuts[:-1], cuts[1:])]


def hinge(X: np.ndarray, y: np.ndarray, own: int, cols: list[int], rss0: float, p0: int, iters: int = 8) -> dict | None:
    """The row as two floored rates of the same columns (the stock's own level among them), one in
    and one out: change = max(0, u0 + U x) - max(0, w0 + W x), as SD Lab's rates are floored at 0 (a
    controller that scales up on a gap and down after it, an inflow that stops at a threshold).
    Fitted by alternating: each step is assigned to the larger running rate (none: no change), and
    each rate is fitted by least squares on its steps. Kept when it beats the linear
    row (rss0 with p0 numbers) by more than 2 log T per number. None otherwise."""
    cols = list(dict.fromkeys([own] + [c for c in cols if c != own]))
    T = len(y)
    Z = np.vstack([np.ones(T), X[cols]]).T                       # T x (1 + K)
    lin = np.linalg.lstsq(Z, y, rcond=None)[0]
    pred = Z @ lin
    up, dn = pred > 0, pred < 0
    U = W = np.zeros(Z.shape[1])
    best = None
    for _ in range(iters):
        if up.sum() < Z.shape[1] + 5 or dn.sum() < Z.shape[1] + 5:
            return None
        U = np.linalg.lstsq(Z[up], y[up], rcond=None)[0]
        W = np.linalg.lstsq(Z[dn], -y[dn], rcond=None)[0]
        a, b = np.maximum(0, Z @ U), np.maximum(0, Z @ W)
        rss = float(((y - a + b) ** 2).sum())
        if best is not None and rss >= best[0] - 1e-9 * best[0]:
            break
        best = (rss, U.copy(), W.copy())
        zu, zw = Z @ U, Z @ W
        nu = (zu > 0) & (zu >= zw)                                 # the in rate runs (and is the larger)
        nd = (zw > 0) & ~nu
        if (nu == up).all() and (nd == dn).all():
            break
        up, dn = nu, nd
    if best is None:
        return None
    rss, U, W = best
    p = 2 * Z.shape[1]
    lt = math.log(T)
    if bic(T, rss, p) >= bic(T, rss0, p0) - 2 * lt * max(1, p - p0):
        return None
    return {"cols": cols, "up": U, "down": W, "rss": rss}
