"""A gap to a target, floored at zero: an inflow max(0, a x_j - b x_own (+ c)) beside a drain e x_own.

Hiring that closes the gap to a target (a measured input or another stock) reads both the target and
the stock it fills: k x target - k x own level. While the gap is open the row is a straight line, and
its own-level term and the drain add up to one number; where the target falls below the level the
inflow stops at zero and the row is the drain alone. That kink is what tells the two apart
(125-floored-gap-to-measured-target, from 106-canonical-workforce). floor.py's hinge reads one level;
this one reads the target and the row's own level together.

Fitted by nonlinear least squares (scipy least_squares) from the straight line's numbers, the own
term split between the gap and the drain at several ratios; with and without a constant, the BIC
choosing. Offered only when the floor binds on 3-97% of steps, the gap closes (a > 0, b > 0) and the
drain is not negative.
"""

from __future__ import annotations

import math

import numpy as np
from scipy.optimize import least_squares


def _gross(p, xj, xi, constant):
    """What the two flows move per step (in plus out)."""
    c = p[3] if constant else 0.0
    return np.maximum(0.0, p[0] * xj + p[1] * xi + c) + abs(p[2]) * xi


def _noise_weights(r, gross):
    """Counting noise grows with what the flows move: the squared residuals regressed on it give each
    step's variance; None when it does not grow (then every step counts the same)."""
    r2 = r * r
    m = float(r2.mean())
    if m <= 0 or np.ptp(gross) <= 0:
        return None
    a, b = np.linalg.lstsq(np.vstack([np.ones_like(gross), gross]).T, r2, rcond=None)[0]
    if b <= 0:
        return None
    var = np.maximum(a + b * gross, 0.05 * m)
    return 1.0 / np.sqrt(var / var.mean())


def _fit_one(y, xj, xi, constant, wt=None):
    T = len(y)
    A = np.vstack([xj, xi] + ([np.ones(T)] if constant else [])).T
    line = np.linalg.lstsq(A, y, rcond=None)[0]
    w = np.ones(T) if wt is None else wt
    best = None
    for lam in (0.5, 0.8, 0.95, 1.0, 1.2, 2.0):
        own = line[1]
        p0 = [line[0], lam * own, max(0.0, -(1 - lam) * own)] + ([line[2]] if constant else [])

        def res(p):
            c = p[3] if constant else 0.0
            return (np.maximum(0.0, p[0] * xj + p[1] * xi + c) - p[2] * xi - y) * w

        try:
            r = least_squares(res, p0, method="trf", x_scale="jac", max_nfev=400)
        except (ValueError, np.linalg.LinAlgError):
            continue
        rss = float(r.fun @ r.fun)
        if best is None or rss < best[0]:
            best = (rss, np.asarray(r.x, dtype=float))
    return best


def _fit_weighted(y, xj, xi, constant):
    """The unweighted fit, then refitted once with the steps weighted by their noise (counting noise
    is larger where the flows move more); the rss reported is the unweighted one."""
    f = _fit_one(y, xj, xi, constant)
    if f is None:
        return None
    c = f[1][3] if constant else 0.0
    r = np.maximum(0.0, f[1][0] * xj + f[1][1] * xi + c) - f[1][2] * xi - y
    wt = _noise_weights(r, _gross(f[1], xj, xi, constant))
    if wt is None:
        return f
    g = _fit_one(y, xj, xi, constant, wt)
    if g is None:
        return f
    c = g[1][3] if constant else 0.0
    r = np.maximum(0.0, g[1][0] * xj + g[1][1] * xi + c) - g[1][2] * xi - y
    return float(r @ r), g[1]


def search(y: np.ndarray, X: np.ndarray, i: int, readers: list[int], floor_rss: float, bind: tuple[float, float] = (0.03, 0.97),
           most: int = 3, max_steps: int = 4000) -> list[dict]:
    """The best floored gap per reader: {j, a, b, c, e, rss, line_rss, binds}; X holds the levels then
    the inputs' values (names x T), i the row's own level."""
    T = len(y)
    xi = X[i]
    # a target raises the inflow: only readers whose number in the straight row is clearly positive
    # (t > 2), the `most` clearest, are fitted
    screened = []
    for j in readers:
        xj = X[j]
        if j == i or np.ptp(xj) <= 0:
            continue
        A = np.vstack([xj, xi, np.ones(T)]).T
        coef, *_ = np.linalg.lstsq(A, y, rcond=None)
        r = y - A @ coef
        line_rss = float(r @ r)
        try:
            cov = np.linalg.inv(A.T @ A) * line_rss / max(1, T - 3)
        except np.linalg.LinAlgError:
            continue
        tstat = coef[0] / math.sqrt(max(cov[0, 0], 1e-300))
        if tstat > 2.0:
            screened.append((tstat, j, line_rss))
    out = []
    # a long run is fitted on every m-th step; the rss is then the whole run's
    m = max(1, T // max_steps)
    for _, j, line_rss in sorted(screened, reverse=True)[:most]:
        xj = X[j]
        fits = []
        for constant in (False, True):
            f = _fit_weighted(y[::m], xj[::m], xi[::m], constant)
            if f is not None:
                p = f[1]
                r = np.maximum(0.0, p[0] * xj + p[1] * xi + (p[3] if constant else 0.0)) - p[2] * xi - y
                f = (float(r @ r), p)
                k = 4 if constant else 3
                fits.append((T * math.log(max(f[0], floor_rss) / T) + k * math.log(T), f, constant))
        if not fits:
            continue
        _, (rss, p), constant = min(fits, key=lambda q: q[0])
        a, b, e = float(p[0]), float(p[1]), float(p[2])
        c = float(p[3]) if constant else 0.0
        if a <= 0 or b >= 0 or e < 0:
            continue
        share = float((a * xj + b * xi + c <= 0).mean())
        if not bind[0] <= share <= bind[1]:
            continue
        out.append({"j": j, "a": a, "b": b, "c": c, "e": e, "rss": rss, "line_rss": line_rss, "binds": share})
    return out


def _r4(v: float) -> float:
    a = abs(v)
    return round(float(v), 2 if a >= 10 else 4 if a >= 1 else 6)


def _flow(src, dst, rate: dict, **extra) -> dict:
    return {"from": src, "to": dst, "ratio": 1, "rate": rate, "rates": [rate], "nearly": [], "bothWays": False, **extra}


def as_flows(fit: dict, row: str, names: list[str], inputs: list[str] = ()) -> list[dict]:
    """The floored gap as an inflow reading the target and the row's level, and the row's drain."""
    j = names[fit["j"]]
    mark = {"input": j} if j in inputs else {}
    rate = {"form": "linear", "c": _r4(fit["c"]), "terms": [{"stock": j, "k": _r4(fit["a"])}, {"stock": row, "k": _r4(fit["b"])}]}
    out = [_flow(None, row, rate, driver=j, floor=j, threshold_params=0, **mark)]
    if fit["e"] > 1e-12:
        out.append(_flow(row, None, {"form": "proportional", "stock": row, "k": _r4(fit["e"])}))
    return out
