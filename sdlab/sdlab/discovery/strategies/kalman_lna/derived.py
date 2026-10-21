"""Columns a row may read beyond the levels, and a slow outside drive read as a schedule (kubernetes 310, 2026-10-21).

docs/research/fixes/310-kalman_lna.md. rows.py reads each stock's change as a sparse linear function of the levels,
or that plus one term floored at 0. Two kinds of rate are outside that library, and both are general:

1. **Derived columns.** A flow proportional to one stock that switches on past a threshold of another (the first
   segment of an effect table: `X * max(0, Y - theta)`, or below it, `X * max(0, theta - Y)`), and a rate per unit
   of another stock (`X / max(1, Y)`, an amount per pod). `search` scores every such column, for every pair of
   measured stocks and (for the switch) a grid of thresholds refined by golden section, by how much of each row's
   residual it explains; the best one joins the readers when it gains PRICE log T on some row. Up to ROUNDS
   columns are added, each searched on the residuals the earlier ones leave.
2. **A schedule.** A stock fed from outside by something nobody measures that drifts slowly (an unmeasured
   integrator, a trend) leaves a row residual that is smooth in time. rows.py fits the row with a continuous
   piecewise-linear function of time (a knot every P steps) as fixed effects, the readers chosen on what that
   leaves, for a few knot spacings, by BIC (one number a knot); the inflow carries the schedule as time segments,
   each block of P steps at the schedule's mean over it. It is offered only on a declared (or undeclared)
   inflow side, where the row without it leaves 100 times the rounding.

Nothing reads the case or its truth; the same search runs on every row.
"""

from __future__ import annotations

import math

import numpy as np

ROUNDS = 3             # at most this many derived columns
THETAS = 40            # threshold grid of a switch column (quantiles of the switch's reader)
SLOW = 0.9             # a residual this autocorrelated (lag 1) is a slow drive, a schedule may carry it
PIECES = (10, 20, 30, 50, 100)   # block sizes a schedule is tried at (at least 3 blocks)


def hinge_expr(x: str, y: str, theta: float, up: bool) -> str:
    return f"{x} * max(0, {y} - {theta!r})" if up else f"{x} * max(0, {theta!r} - {y})"


def ratio_expr(x: str, y: str) -> str:
    return f"{x} / max(1, {y})"


def blocks(T: int, P: int) -> np.ndarray:
    return np.arange(T) // P


def basis(T: int, P: int) -> np.ndarray:
    """An orthonormal basis of the continuous piecewise-linear functions of time with a knot every P steps."""
    knots = np.arange(0, T - 1 + P, P, dtype=float)
    knots[-1] = max(knots[-1], T - 1)
    knots = np.unique(np.minimum(knots, T - 1))
    t = np.arange(T, dtype=float)
    H = np.zeros((T, len(knots)))
    for k, c in enumerate(knots):
        left = knots[k - 1] if k else None
        right = knots[k + 1] if k + 1 < len(knots) else None
        h = np.zeros(T)
        if left is not None:
            m = (t >= left) & (t <= c)
            h[m] = (t[m] - left) / (c - left)
        if right is not None:
            m = (t >= c) & (t <= right)
            h[m] = (right - t[m]) / (right - c)
        h[t == c] = 1.0
        H[:, k] = h
    Q, _ = np.linalg.qr(H)
    return Q


def demean(A: np.ndarray, Q: np.ndarray) -> np.ndarray:
    """What the schedule (the span of Q) leaves of A: the fixed effects' projection."""
    A = np.asarray(A, dtype=float)
    return A - Q @ (Q.T @ A)


def fitted(r: np.ndarray, Q: np.ndarray) -> np.ndarray:
    return Q @ (Q.T @ r)


def slow(r: np.ndarray) -> bool:
    r = np.asarray(r, dtype=float) - float(np.mean(r))
    d = float(r @ r)
    return d > 0 and float(r[1:] @ r[:-1]) / d > SLOW


def _gain(c: np.ndarray, r: np.ndarray, sse: float, floor: float, T: int) -> float:
    cc = float(c @ c)
    if cc <= 0:
        return -math.inf
    red = float(c @ r) ** 2 / cc
    return T * math.log((sse + floor) / (max(0.0, sse - red) + floor))


def search(X: np.ndarray, names: list, stock_cols: list[int], resid: dict, floors: dict, proj: dict, T: int,
           taken: set[str]):
    """The best derived column for the rows' residuals: (gain, name-free meta, series) or None.
    resid: {row: residual}; proj: {row: block index or None} (a row fitted with a schedule is searched on the
    within-block changes); meta: {"expr", "reads", "base"}."""
    logT = math.log(T)
    best = None
    prepared = {S: (proj[S], (demean(r, proj[S]) if proj[S] is not None else r)) for S, r in resid.items()}
    sses = {S: float(rr @ rr) for S, (_, rr) in prepared.items()}

    def score(col):
        top = (-math.inf, None)
        for S, (idx, rr) in prepared.items():
            c = demean(col, idx) if idx is not None else col
            g = _gain(c, rr, sses[S], floors[S], T)
            if g > top[0]:
                top = (g, S)
        return top

    for ia in stock_cols:
        xa = X[:, ia]
        for ib in stock_cols:
            if ib == ia:
                continue
            xb = X[:, ib]
            e = ratio_expr(names[ia], names[ib])
            if e not in taken:
                col = xa / np.maximum(1.0, xb)
                g, S = score(col)
                if g - logT > (best[0] if best else -math.inf):
                    best = (g - logT, {"expr": e, "reads": [names[ia], names[ib]], "base": names[ia], "row": S}, col)
            lo, hi = float(np.min(xb)), float(np.max(xb))
            if hi <= lo:
                continue
            for up in (True, False):
                qs = np.quantile(xb, np.linspace(0.5, 0.995, THETAS) if up else np.linspace(0.005, 0.5, THETAS))

                def f(theta, up=up):
                    col = xa * (np.maximum(0.0, xb - theta) if up else np.maximum(0.0, theta - xb))
                    return score(col)[0], col

                vals = [f(q)[0] for q in qs]
                k = int(np.argmax(vals))
                if not math.isfinite(vals[k]):
                    continue
                a = float(qs[max(0, k - 1)])
                b = float(qs[min(len(qs) - 1, k + 1)])
                gr = (math.sqrt(5) - 1) / 2                      # golden section on the threshold
                c1, c2 = b - gr * (b - a), a + gr * (b - a)
                f1, f2 = f(c1)[0], f(c2)[0]
                for _ in range(24):
                    if f1 > f2:
                        b, c2, f2 = c2, c1, f1
                        c1 = b - gr * (b - a)
                        f1 = f(c1)[0]
                    else:
                        a, c1, f1 = c1, c2, f2
                        c2 = a + gr * (b - a)
                        f2 = f(c2)[0]
                cands = [(vals[k], float(qs[k])), (f1, c1), (f2, c2)]
                g, theta = max(cands)
                e = hinge_expr(names[ia], names[ib], theta, up)
                if e in taken:
                    continue
                g -= 2 * logT                                     # its number and its threshold
                if g > (best[0] if best else -math.inf):
                    best = (g, {"expr": e, "reads": [names[ia], names[ib]], "base": names[ia], "row": score(f(theta)[1])[1],
                                "hinge": (ia, ib, up, theta),
                                "switch": np.maximum(0.0, xb - theta) if up else np.maximum(0.0, theta - xb)}, f(theta)[1])
    return best


def refine(X: np.ndarray, names: list, meta: dict, parts: dict) -> tuple[dict, np.ndarray]:
    """A switch column's threshold refitted on the rows that read it (parts: {row: what the column and the
    residual leave of it}), the other terms of each row held: golden section around the searched threshold."""
    if not meta.get("hinge"):
        return meta, None
    ia, ib, up, theta = meta["hinge"]
    xa, xb = X[:, ia], X[:, ib]
    span = 0.02 * float(np.ptp(xb)) or 1.0

    def col(th):
        return xa * (np.maximum(0.0, xb - th) if up else np.maximum(0.0, th - xb))

    def sse(th):
        c = col(th)
        cc = float(c @ c)
        if cc <= 0:
            return math.inf
        return sum(float(z @ z) - float(c @ z) ** 2 / cc for z in parts.values())

    a, b = theta - span, theta + span
    gr = (math.sqrt(5) - 1) / 2
    c1, c2 = b - gr * (b - a), a + gr * (b - a)
    f1, f2 = sse(c1), sse(c2)
    for _ in range(60):
        if f1 < f2:
            b, c2, f2 = c2, c1, f1
            c1 = b - gr * (b - a)
            f1 = sse(c1)
        else:
            a, c1, f1 = c1, c2, f2
            c2 = a + gr * (b - a)
            f2 = sse(c2)
    th = c1 if f1 < f2 else c2
    if not sse(th) < sse(theta):
        return meta, None
    return {**meta, "expr": hinge_expr(names[ia], names[ib], th, up), "hinge": (ia, ib, up, th),
            "switch": np.maximum(0.0, xb - th) if up else np.maximum(0.0, th - xb)}, col(th)


# 3. A hidden integrator (310): a stock nobody measures, fed at a constant rate and drained in proportion to itself,
#    at a constant rate or switched by one of the derived switches (derived column / its base), read by one row.
#    Its level is linear in its initial level and its inflow for a given drain rate a, so the row reads two
#    columns per a; a is searched on a grid and refined by golden section.

DECAYS = 24            # drain rates on the grid (log-spaced, per unit of the switch's mean, and 0)


def integrator(a: float, s: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """(response to a unit initial level, response to a unit inflow) of h' = 1 - a s h, read at each step's start."""
    T = len(s)
    g = np.clip(1.0 - a * s, 0.0, None)
    h0, h1 = np.empty(T), np.empty(T)
    x0, x1 = 1.0, 0.0
    for k in range(T):
        h0[k], h1[k] = x0, x1
        x0, x1 = x0 * g[k], x1 * g[k] + 1.0
    return h0, h1


def decays(s: np.ndarray) -> list[float]:
    m = float(np.mean(np.abs(s))) or 1.0
    return [0.0] + list(np.geomspace(1e-4, 1.0, DECAYS - 1) / m)


def golden(f, a: float, b: float, rounds: int = 30) -> tuple[float, float]:
    """(argmin, min) of f on [a, b]."""
    gr = (math.sqrt(5) - 1) / 2
    c1, c2 = b - gr * (b - a), a + gr * (b - a)
    f1, f2 = f(c1), f(c2)
    for _ in range(rounds):
        if f1 < f2:
            b, c2, f2 = c2, c1, f1
            c1 = b - gr * (b - a)
            f1 = f(c1)
        else:
            a, c1, f1 = c1, c2, f2
            c2 = a + gr * (b - a)
            f2 = f(c2)
    return (c1, f1) if f1 < f2 else (c2, f2)
