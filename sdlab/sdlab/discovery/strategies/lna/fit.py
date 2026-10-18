"""Fitting atoms' numbers by the linear noise approximation's likelihood, and choosing which atoms
stay (backward elimination by BIC)."""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from scipy.optimize import lsq_linear, minimize

from .atoms import Atom, features, pooling, stoich
from .likelihood import ROUNDING, nll


@dataclass
class Data:
    prev: np.ndarray              # stocks x steps: levels at the start of each step
    dy: np.ndarray                # stocks x steps: each step's change
    cfg: np.ndarray | None        # the configuration (era) in force at each step
    delta: float = ROUNDING
    free: np.ndarray | None = None   # the stocks whose variance beyond counting noise is fitted (others: 0)


@dataclass
class Fitted:
    atoms: list[Atom]
    theta: np.ndarray
    nll: float
    tau: np.ndarray | None = None          # each stock's variance beyond counting noise

    @property
    def p(self) -> int:
        return int((self.theta > 0).sum())


def mean_start(atoms: list[Atom], d: Data) -> np.ndarray:
    """Non-negative least squares on the means, each row weighted by its spread."""
    V, Z = stoich(atoms, d.prev.shape[0]), features(atoms, d.prev, d.cfg)
    S, T = d.dy.shape
    w = 1 / np.sqrt(np.maximum(d.dy.var(axis=1), 1e-9))
    D = (V[:, :, None] * Z[None, :, :]) * w[:, None, None]          # S x F x T
    A = D.transpose(0, 2, 1).reshape(S * T, len(atoms))
    b = (d.dy * w[:, None]).reshape(-1)
    sc = np.maximum(np.abs(A).max(axis=0), 1e-12)
    r = lsq_linear(A / sc, b, bounds=(0, np.inf), method="bvls" if len(atoms) < 60 else "trf")
    return r.x / sc


def fit(atoms: list[Atom], d: Data, start: np.ndarray | None = None, maxiter: int = 400, tau: np.ndarray | None = None) -> Fitted:
    """The atoms' numbers (>= 0) and each stock's extra variance, by maximum likelihood."""
    S, T = d.dy.shape
    V, Z = stoich(atoms, S), features(atoms, d.prev, d.cfg)
    scale = np.maximum(Z.mean(axis=1), 1e-9) if atoms else np.zeros(0)   # theta x scale: the mean amount per step
    if atoms:
        x0 = (mean_start(atoms, d) if start is None else np.asarray(start, float)) * scale
        x0 = np.maximum(x0, 1e-3)
    else:
        x0 = np.zeros(0)
    vs = np.maximum(d.dy.var(axis=1), 1.0)                            # tau's scale: each stock's spread
    free = np.ones(S, bool) if d.free is None else d.free
    t0 = np.where(free, (np.zeros(S) if tau is None else np.asarray(tau, float)) / vs, 0.0)
    pool, sign = pooling(atoms)
    F = len(atoms)

    def f(x):
        v, g = nll(x[:F] / scale, V, Z, d.dy, d.delta, pool=pool, sign=sign, tau=x[F:] * vs)
        if not np.isfinite(v):
            return 1e300, np.zeros_like(x)
        return v, np.concatenate([g[:F] / scale, g[F:] * vs])

    r = minimize(f, np.concatenate([x0, t0]), jac=True, method="L-BFGS-B", bounds=[(0, None)] * F + [(0, None) if f else (0, 0) for f in free], options={"maxiter": maxiter})
    th = r.x[:F] / scale
    th[r.x[:F] < 1e-6] = 0.0
    return Fitted(list(atoms), th, float(r.fun), r.x[F:] * vs)


def extra_variance(cur: Fitted, d: Data, price: float | None = None) -> np.ndarray:
    """Which stocks need variance beyond counting noise: those where fixing it at 0 costs more than
    the BIC price (so a model that fits as counting noise predicts reads the noise at full strength)."""
    S, T = d.dy.shape
    price = 0.5 * math.log(T) if price is None else price
    free = np.ones(S, bool)
    for s in np.argsort(cur.tau if cur.tau is not None else np.zeros(S)):
        trial = free.copy()
        trial[s] = False
        g = fit(cur.atoms, Data(d.prev, d.dy, d.cfg, d.delta, trial), cur.theta, maxiter=200, tau=cur.tau)
        if g.nll - cur.nll < price:
            free, cur = trial, g
    return free


def prune(fitted: Fitted, d: Data, price: float | None = None) -> Fitted:
    """Flows whose removal costs less than the BIC price (log T / 2 in the negative log-likelihood,
    per number) go, one at a time, the cheapest first. A flow is all the atoms with one key (its
    numbers per era, its inflow's pieces): they go together. Atoms at zero go at once."""
    T = d.dy.shape[1]
    price = 0.5 * math.log(T) if price is None else price
    cur = fitted
    while True:
        live = [i for i, th in enumerate(cur.theta) if th > 0]
        if len(live) < len(cur.atoms):
            cur = fit([cur.atoms[i] for i in live], d, cur.theta[live], tau=cur.tau)
            continue
        best = None
        for key in dict.fromkeys(a.key() for a in cur.atoms):
            rest = [j for j, a in enumerate(cur.atoms) if a.key() != key]
            n = len(cur.atoms) - len(rest)
            g = fit([cur.atoms[j] for j in rest], d, cur.theta[rest], maxiter=200, tau=cur.tau)
            cost = (g.nll - cur.nll) / n
            if best is None or cost < best[0]:
                best = (cost, g)
        if best is None or best[0] >= price:
            return cur
        cur = best[1]
