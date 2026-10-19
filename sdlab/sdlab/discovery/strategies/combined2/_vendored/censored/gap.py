# Vendored for combined2 from sdlab/discovery/strategies/censored/gap.py at commit 6ca61d5 (HEAD 05ae898); imports
# rewritten to these copies, otherwise unchanged (CLAUDE.md invariant 11). Re-vendor rather than edit.
"""A gap to a target, floored at zero: an inflow max(0, a x_j - b x_own - sum b_m x_m (+ c)) beside a
drain e x_own.

Hiring that closes the gap to a target (a measured input or another stock) reads the target and the
stock it fills (and, when the gap counts more than one stock, those too): k x target - k x own level.
While the gap is open the row is a straight line, and its own-level term and the drain add up to one
number; where the target falls below the level the inflow stops at zero and the row is the drain
alone. That kink is what tells the two apart (125-floored-gap-to-measured-target, from
106-canonical-workforce). floor.py's hinge reads one level; this one reads the target and the row's
own level together, plus the other levels the caller passes (those the main line's row read).

Fitted by nonlinear least squares (scipy least_squares) from the straight line's numbers, the own
term split between the gap and the drain at several ratios; with and without a constant, the BIC
choosing; then refitted once with the steps weighted by their noise when it grows with what the
flows move (counting noise). Readers are screened first: a target raises the inflow, so only those
with a clearly positive number in the straight row (t > 2) are fitted. Offered only when the floor
binds on 3-97% of steps, the gap closes (a > 0, b > 0) and the drain is not negative.
"""

from __future__ import annotations

import math

import numpy as np
from scipy.optimize import least_squares


def _hinge(p, H, constant):
    """p = [a_j, b_own, b_m..., e, (c)] over H = [x_j, x_own, x_m...]."""
    n = len(H)
    return p[:n] @ H + (p[n + 1] if constant else 0.0)


def _resid(p, H, y, constant):
    n = len(H)
    return np.maximum(0.0, _hinge(p, H, constant)) - p[n] * H[1] - y


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


def _fit_one(y, H, constant, wt=None):
    T = len(y)
    n = len(H)
    A = np.vstack(list(H) + ([np.ones(T)] if constant else [])).T
    line = np.linalg.lstsq(A, y, rcond=None)[0]
    w = np.ones(T) if wt is None else wt
    best = None
    for lam in (0.5, 0.8, 0.95, 1.0, 1.2, 2.0):
        own = line[1]
        p0 = np.concatenate([[line[0], lam * own], line[2:n], [max(0.0, -(1 - lam) * own)], [line[n]] if constant else []])
        try:
            r = least_squares(lambda p: _resid(p, H, y, constant) * w, p0, method="trf", x_scale="jac", max_nfev=400)
        except (ValueError, np.linalg.LinAlgError):
            continue
        rss = float(r.fun @ r.fun)
        if best is None or rss < best[0]:
            best = (rss, np.asarray(r.x, dtype=float))
    return best


def _fit_weighted(y, H, constant):
    """The unweighted fit, then refitted once with the steps weighted by their noise; the rss
    reported is the unweighted one."""
    f = _fit_one(y, H, constant)
    if f is None:
        return None
    gross = lambda p: np.maximum(0.0, _hinge(p, H, constant)) + abs(p[len(H)]) * H[1]  # noqa: E731
    wt = _noise_weights(_resid(f[1], H, y, constant), gross(f[1]))
    if wt is None:
        return f
    g = _fit_one(y, H, constant, wt)
    if g is None:
        return f
    r = _resid(g[1], H, y, constant)
    return float(r @ r), g[1]


def search(y: np.ndarray, X: np.ndarray, i: int, readers: list[int], floor_rss: float, bind: tuple[float, float] = (0.03, 0.97),
           most: int = 3, max_steps: int = 4000, extra: list[int] = ()) -> list[dict]:
    """The best floored gap per reader: {j, extra, a, b, bm, c, e, rss, line_rss, binds}; X holds the
    levels then the inputs' values (names x T), i the row's own level, extra the other levels the
    gap also reads."""
    T = len(y)
    screened = []
    for j in readers:
        if j == i or j in extra or np.ptp(X[j]) <= 0:
            continue
        H = np.vstack([X[j], X[i]] + [X[m] for m in extra])
        A = np.vstack(list(H) + [np.ones(T)]).T
        coef, *_ = np.linalg.lstsq(A, y, rcond=None)
        r = y - A @ coef
        line_rss = float(r @ r)
        try:
            cov = np.linalg.inv(A.T @ A) * line_rss / max(1, T - A.shape[1])
        except np.linalg.LinAlgError:
            continue
        tstat = coef[0] / math.sqrt(max(cov[0, 0], 1e-300))
        if tstat > 2.0:
            screened.append((tstat, j, line_rss))
    out = []
    # a long run is fitted on every m-th step; the rss is then the whole run's
    step = max(1, T // max_steps)
    for _, j, line_rss in sorted(screened, reverse=True)[:most]:
        H = np.vstack([X[j], X[i]] + [X[m] for m in extra])
        n = len(H)
        fits = []
        for constant in (False, True):
            f = _fit_weighted(y[::step], H[:, ::step], constant)
            if f is None:
                continue
            p = f[1]
            r = _resid(p, H, y, constant)
            k = n + 1 + int(constant)
            fits.append((T * math.log(max(float(r @ r), floor_rss) / T) + k * math.log(T), (float(r @ r), p), constant))
        if not fits:
            continue
        _, (rss, p), constant = min(fits, key=lambda q: q[0])
        a, b, e = float(p[0]), float(p[1]), float(p[n])
        c = float(p[n + 1]) if constant else 0.0
        if a <= 0 or b >= 0 or e < 0:
            continue
        share = float((_hinge(p, H, constant) <= 0).mean())
        if not bind[0] <= share <= bind[1]:
            continue
        out.append({"j": j, "extra": list(extra), "a": a, "b": b, "bm": [float(v) for v in p[2:n]], "c": c, "e": e,
                    "rss": rss, "line_rss": line_rss, "binds": share})
    return out


def _r4(v: float) -> float:
    a = abs(v)
    return round(float(v), 2 if a >= 10 else 4 if a >= 1 else 6)


def _flow(src, dst, rate: dict, **extra) -> dict:
    return {"from": src, "to": dst, "ratio": 1, "rate": rate, "rates": [rate], "nearly": [], "bothWays": False, **extra}


def as_flows(fit: dict, row: str, names: list[str], inputs: list[str] = ()) -> list[dict]:
    """The floored gap as an inflow reading the target, the row's level and the other levels, and the
    row's drain."""
    j = names[fit["j"]]
    mark = {"input": j} if j in inputs else {}
    terms = [{"stock": j, "k": _r4(fit["a"])}, {"stock": row, "k": _r4(fit["b"])}]
    terms += [{"stock": names[m], "k": _r4(b)} for m, b in zip(fit.get("extra") or [], fit.get("bm") or [])]
    rate = {"form": "linear", "c": _r4(fit["c"]), "terms": terms}
    out = [_flow(None, row, rate, driver=j, floor=j, threshold_params=0, **mark)]
    if fit["e"] > 1e-12:
        out.append(_flow(row, None, {"form": "proportional", "stock": row, "k": _r4(fit["e"])}))
    return out
