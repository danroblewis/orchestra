"""Adaptive Metropolis (Haario, Saksman, Tamminen 2001) on a negative log-posterior, started at its
mode with the inverse of a finite-difference Hessian as the first proposal covariance."""

from __future__ import annotations

import math
import time
import warnings

import numpy as np
from scipy.optimize import minimize

FULL_HESSIAN = 30     # beyond this many parameters, the Hessian's diagonal only


def mode(f, x0: np.ndarray, free: np.ndarray | None = None, until: float = math.inf, maxiter: int = 200) -> np.ndarray:
    """f's minimum from x0 over the `free` coordinates (Nelder-Mead below 3 free, else Powell: no
    gradients, robust to the boxes' infinities)."""
    free = np.ones(len(x0), bool) if free is None else free
    if not free.any():
        return x0
    best = [f(x0), x0.copy()]

    def g(y):
        if time.monotonic() > until:
            raise TimeoutError
        x = x0.copy()
        x[free] = y
        v = f(x)
        if v < best[0]:
            best[0], best[1] = v, x
        return v
    try:
        with warnings.catch_warnings(), np.errstate(all="ignore"):
            warnings.simplefilter("ignore", RuntimeWarning)       # Powell's line search meets the boxes' infinities
            r = minimize(g, x0[free], method="Powell", options={"maxiter": maxiter, "maxfev": 60 * int(free.sum()) + 200,
                                                                   "xtol": 1e-4, "ftol": 1e-7})
        y = r.x
    except TimeoutError:
        return best[1]                                         # the best point seen when the time ran out
    x = x0.copy()
    x[free] = y
    return x if f(x) <= best[0] else best[1]


def _step(x: np.ndarray) -> np.ndarray:
    return 1e-3 * np.maximum(np.abs(x), 1e-2)


def hessian(f, x: np.ndarray, until: float = math.inf) -> np.ndarray | None:
    """Central-difference Hessian of f at x (diagonal only beyond FULL_HESSIAN). A coordinate whose
    step leaves the prior's box (a noise number at its bound) gets no curvature and no coupling: its
    proposal then comes from the adaptation alone. None when the time runs out."""
    d = len(x)
    h = _step(x)
    f0 = f(x)
    H = np.zeros((d, d))
    ok = np.ones(d, bool)
    for i in range(d):
        e = np.zeros(d)
        e[i] = h[i]
        a, b = f(x + e), f(x - e)
        if not (math.isfinite(a) and math.isfinite(b)):
            ok[i] = False
            continue
        H[i, i] = (a - 2 * f0 + b) / h[i] ** 2
        if time.monotonic() > until:
            return None
    if d <= FULL_HESSIAN:
        for i in range(d):
            for j in range(i):
                if not (ok[i] and ok[j]):
                    continue
                ei, ej = np.zeros(d), np.zeros(d)
                ei[i], ej[j] = h[i], h[j]
                v = (f(x + ei + ej) - f(x + ei - ej) - f(x - ei + ej) + f(x - ei - ej)) / (4 * h[i] * h[j])
                H[i, j] = H[j, i] = v if math.isfinite(v) else 0.0
            if time.monotonic() > until:
                return None
    for i in np.flatnonzero(~ok):
        H[i, i] = math.nan                                # no curvature known: proposal() gives it a default
    return H


def proposal(H: np.ndarray | None, x: np.ndarray) -> np.ndarray:
    """A proposal covariance from the Hessian: its inverse, made positive definite (eigenvalues
    floored); a small diagonal where there is none (no Hessian, or a coordinate without curvature)."""
    default = (0.01 * np.maximum(np.abs(x), 1e-3)) ** 2
    if H is None:
        return np.diag(default)
    known = np.isfinite(np.diag(H))
    C = np.diag(default)
    if known.any():
        Hk = H[np.ix_(known, known)]
        w, U = np.linalg.eigh(0.5 * (Hk + Hk.T))
        top = max(float(np.max(np.abs(w))), 1e-12)
        w = np.maximum(w, 1e-8 * top)
        Ck = (U / w) @ U.T
        cap = (np.maximum(np.abs(x[known]), 1.0) * 10.0) ** 2       # no proposal wider than ten times the value
        s = np.sqrt(np.minimum(np.diag(Ck), cap) / np.maximum(np.diag(Ck), 1e-300))
        C[np.ix_(known, known)] = Ck * np.outer(s, s)
    return C


def sample(f, x0: np.ndarray, C0: np.ndarray, until: float, n: int = 4000, burn: int = 1000, seed: int = 0,
           adapt_every: int = 100) -> dict:
    """Adaptive Metropolis on exp(-f): draws after burn-in (as many as the time allows), the
    acceptance rate, and how many iterations ran."""
    rng = np.random.default_rng(seed)
    d = len(x0)
    sd = 2.38 ** 2 / d
    C = C0.copy()
    x, fx = x0.copy(), f(x0)
    chain = np.zeros((n + burn, d))
    acc = 0
    it = 0
    eps = 1e-10 * np.eye(d)
    for it in range(n + burn):
        if time.monotonic() > until:
            break
        if it and it % adapt_every == 0 and it >= 2 * adapt_every:
            past = chain[max(0, it // 2 - 1): it]        # the chain's second half so far
            Cn = np.cov(past.T) if d > 1 else np.atleast_2d(np.var(past))
            if np.all(np.isfinite(Cn)) and np.trace(Cn) > 0:
                C = Cn + eps * max(1e-12, float(np.mean(np.diag(Cn))))
        try:
            L = np.linalg.cholesky(sd * C + eps)
        except np.linalg.LinAlgError:
            L = np.diag(np.sqrt(np.maximum(np.diag(sd * C), 1e-30)))
        y = x + L @ rng.standard_normal(d)
        fy = f(y)
        if math.isfinite(fy) and math.log(rng.random() + 1e-300) < fx - fy:
            x, fx = y, fy
            acc += 1
        chain[it] = x
    ran = it + 1 if time.monotonic() <= until else it
    draws = chain[burn: ran] if ran > burn else chain[ran // 2: ran]
    return {"draws": draws, "accept": acc / max(1, ran), "iterations": ran, "burn": min(burn, ran // 2) if ran <= burn else burn}


def ess(x: np.ndarray) -> float:
    """Effective sample size of one chain (Geyer's initial positive sequence, truncated)."""
    n = len(x)
    if n < 10 or np.var(x) <= 0:
        return float(n)
    y = x - x.mean()
    f = np.fft.rfft(y, 2 * n)
    ac = np.fft.irfft(f * np.conj(f))[:n] / (n * np.var(x))
    s = 0.0
    for k in range(1, n - 1, 2):
        pair = ac[k] + ac[k + 1]
        if pair <= 0:
            break
        s += pair
    return float(n / max(1.0, 1 + 2 * s))
