"""Minimising a sum of squared residuals over a box, by several families of optimiser, on a budget.

Every method gets the same things: residuals(x) -> vector, a start x0, a box [lo, hi] and a budget
of evaluations (every call of residuals counts, including the ones a method spends on finite
differences). Each returns the best point it evaluated, so a method stopped by the budget keeps what
it found. Methods work on the numbers scaled by their box (or their size), so one step size suits
rates, curve points and delays alike.

  fd      scipy least_squares (trust region reflective), Jacobian by finite differences
  lbfgs   scipy L-BFGS-B on the sum of squares, gradient by finite differences
  powell  scipy Powell (derivative-free line searches)
  nm      scipy Nelder-Mead (derivative-free simplex)
  cma     CMA-ES (the `cma` package)
  bo      Bayesian optimisation: a Gaussian process (Matern 5/2) on log cost, expected improvement
"""

from __future__ import annotations

import math
import warnings
from dataclasses import dataclass

import numpy as np
from scipy.optimize import least_squares, minimize
from scipy.stats import norm

METHODS = ("fd", "lbfgs", "powell", "nm", "cma", "bo")


class _Budget(Exception):
    pass


@dataclass
class Result:
    x: np.ndarray
    cost: float
    evals: int
    start_cost: float


class _Counted:
    def __init__(self, residuals, budget: int, scale: np.ndarray, lo: np.ndarray, hi: np.ndarray):
        self.f, self.budget, self.scale, self.lo, self.hi = residuals, budget, scale, lo, hi
        self.evals, self.best_x, self.best = 0, None, math.inf

    def r(self, z: np.ndarray) -> np.ndarray:
        if self.evals >= self.budget:
            raise _Budget
        x = np.clip(np.asarray(z, dtype=float) * self.scale, self.lo, self.hi)
        self.evals += 1
        r = self.f(x)
        c = float(r @ r)
        if not math.isfinite(c):
            c = 1e12
        if c < self.best:
            self.best, self.best_x = c, x.copy()
        return r

    def c(self, z: np.ndarray) -> float:
        r = self.r(z)
        c = float(r @ r)
        return c if math.isfinite(c) else 1e12


def minimise(method: str, residuals, x0: np.ndarray, lo: np.ndarray, hi: np.ndarray, budget: int, seed: int = 0) -> Result:
    x0 = np.clip(np.asarray(x0, dtype=float), lo, hi)
    scale = np.maximum(np.maximum(np.abs(x0), (hi - lo) / 10), 1e-9)
    F = _Counted(residuals, budget, scale, lo, hi)
    z0, zl, zh = x0 / scale, lo / scale, hi / scale
    try:
        start = F.c(z0)
        if len(x0) and budget > 1:
            _METHODS[method](F, z0, zl, zh, budget, seed)
    except _Budget:
        pass
    return Result(F.best_x if F.best_x is not None else x0, F.best, F.evals, start)


def _fd(F, z0, zl, zh, budget, seed):
    zh2 = np.where(zh > zl, zh, zl + 1e-9)
    least_squares(F.r, np.clip(z0, zl, zh2), bounds=(zl, zh2), diff_step=1e-3, method="trf", max_nfev=budget, x_scale=1.0)


def _lbfgs(F, z0, zl, zh, budget, seed):
    minimize(F.c, z0, method="L-BFGS-B", bounds=list(zip(zl, zh)), options={"maxfun": budget, "eps": 1e-3 * np.maximum(1, np.abs(z0))})


def _powell(F, z0, zl, zh, budget, seed):
    minimize(F.c, z0, method="Powell", bounds=list(zip(zl, zh)), options={"maxfev": budget, "xtol": 1e-3, "ftol": 1e-6})


def _nm(F, z0, zl, zh, budget, seed):
    n = len(z0)
    step = 0.25 * np.maximum(np.abs(z0), 0.1 * (zh - zl))
    simplex = [z0] + [np.clip(z0 + np.eye(n)[i] * step[i] * (1 if z0[i] + step[i] <= zh[i] else -1), zl, zh) for i in range(n)]
    minimize(F.c, z0, method="Nelder-Mead", bounds=list(zip(zl, zh)), options={"maxfev": budget, "initial_simplex": np.array(simplex), "xatol": 1e-4, "fatol": 1e-8, "adaptive": n > 4})


def _cma(F, z0, zl, zh, budget, seed):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        import cma
    if len(z0) == 1:                       # CMA-ES needs two dimensions; a line search does for one
        _powell(F, z0, zl, zh, budget, seed)
        return
    span = np.where(np.isfinite(zh - zl), zh - zl, np.abs(z0) + 1)
    sigma = 0.2
    opts = {"bounds": [list(zl), list(zh)], "maxfevals": budget, "verbose": -9, "seed": seed + 1,
            "CMA_stds": list(np.maximum(1e-6, np.minimum(np.maximum(np.abs(z0), 0.5), span))), "tolfun": 1e-10, "tolx": 1e-8}
    es = cma.CMAEvolutionStrategy(list(z0), sigma, opts)
    while not es.stop():
        xs = es.ask()
        es.tell(xs, [F.c(np.asarray(x)) for x in xs])


def _bo(F, z0, zl, zh, budget, seed):
    """Expected improvement on a GP of log cost over the box, scaled to the unit cube."""
    rng = np.random.default_rng(seed)
    n = len(z0)
    span = np.where(zh > zl, zh - zl, 1.0)
    to_z = lambda u: zl + u * span          # noqa: E731
    U = [(z0 - zl) / span]
    Y = [math.log(F.best + 1e-12)]
    for u in _lhs(rng, min(2 * n + 2, max(1, budget // 3)), n):
        U.append(u)
        Y.append(math.log(F.c(to_z(u)) + 1e-12))
    while True:
        X, y = np.array(U), np.array(Y)
        mu, sd_y = y.mean(), y.std() or 1.0
        yn = (y - mu) / sd_y
        ell = _fit_length(X, yn)
        K = _matern(X, X, ell) + 1e-6 * np.eye(len(X))
        L = np.linalg.cholesky(K)
        alpha = np.linalg.solve(L.T, np.linalg.solve(L, yn))
        best = yn.min()
        ub = X[np.argmin(yn)]
        cand = np.vstack([rng.random((1500, n)), np.clip(ub + 0.05 * rng.standard_normal((500, n)), 0, 1), np.clip(ub + 0.01 * rng.standard_normal((200, n)), 0, 1)])
        ks = _matern(cand, X, ell)
        m = ks @ alpha
        v = np.maximum(1e-12, 1.0 - (np.linalg.solve(L, ks.T) ** 2).sum(axis=0))
        s = np.sqrt(v)
        g = (best - m) / s
        ei = s * (g * norm.cdf(g) + norm.pdf(g))
        u = cand[int(np.argmax(ei))]
        U.append(u)
        Y.append(math.log(F.c(to_z(u)) + 1e-12))


def _lhs(rng, k: int, n: int) -> np.ndarray:
    return (np.argsort(rng.random((n, k)), axis=1).T + rng.random((k, n))) / k


def _matern(A: np.ndarray, B: np.ndarray, ell: float) -> np.ndarray:
    d = np.sqrt(np.maximum(0.0, ((A[:, None, :] - B[None, :, :]) ** 2).sum(-1))) / ell
    return (1 + math.sqrt(5) * d + 5 / 3 * d * d) * np.exp(-math.sqrt(5) * d)


def _fit_length(X: np.ndarray, y: np.ndarray) -> float:
    """The length scale with the best marginal likelihood on a small grid."""
    best, ell_best = -math.inf, 0.3
    for ell in (0.05, 0.1, 0.2, 0.3, 0.5, 0.8, 1.2):
        K = _matern(X, X, ell) + 1e-4 * np.eye(len(X))
        try:
            L = np.linalg.cholesky(K)
        except np.linalg.LinAlgError:
            continue
        a = np.linalg.solve(L.T, np.linalg.solve(L, y))
        ll = -0.5 * y @ a - np.log(np.diag(L)).sum()
        if ll > best:
            best, ell_best = ll, ell
    return ell_best


_METHODS = {"fd": _fd, "lbfgs": _lbfgs, "powell": _powell, "nm": _nm, "cma": _cma, "bo": _bo}
