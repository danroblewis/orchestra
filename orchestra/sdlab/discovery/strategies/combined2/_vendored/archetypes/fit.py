# Vendored for combined2 from sdlab/discovery/strategies/archetypes/fit.py at commit 3c3e009 (HEAD ebe9a4f); imports
# rewritten to these copies, otherwise unchanged (CLAUDE.md invariant 11). Re-vendor rather than edit.
"""Fitting a term model to the measured levels by its free run (output error), and pricing it.

Measurement error, not process noise, is what a short series of counts or shares mostly carries, so
the numbers are fitted to the levels the model runs to from its own starting levels (fitted too),
not to the one-step changes (which errors in the levels bias). Each stock's error has its own scale,
sd_i x w_it, with w_it = max(|y_it|, 5% of the stock's largest level) ** power: power 0 is a
constant error, 1 an error proportional to the level, 0.5 in between (counts). The scales are
concentrated out, so the negative log-likelihood is sum_i (n/2) log(RSS_i / n) + sum log w_it, and
a model is priced by AICc (the small-sample Akaike criterion), counting every rate number, every
starting level and every scale.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
from scipy.optimize import least_squares

from .sim import run
from .terms import Term, arrays

GROWTH = 3.0


@dataclass
class Data:
    Y: np.ndarray                 # measured stocks x samples
    inj: np.ndarray               # samples x stocks (all stocks, hidden ones too)
    power: float = 0.0
    hidden: int = 0               # unmeasured stocks after the measured ones
    allow: object = None          # (boundary: docs/research/declared-boundary.md) term -> bool: terms with an outside end off a declared boundary
    claim: float = 0.0            # (boundary: docs/research/declared-boundary.md) what each outside term adds to AICc with no boundary declared
    W: np.ndarray = field(init=False)
    scale: np.ndarray = field(init=False)
    cap: float = field(init=False)
    floor: np.ndarray = field(init=False)

    def __post_init__(self):
        Y = self.Y
        top = np.maximum(np.max(np.abs(Y), axis=1), 1e-9)
        self.W = np.maximum(np.abs(Y), 0.05 * top[:, None]) ** self.power
        d = np.diff(Y, axis=1) / self.W[:, 1:]
        d2 = np.diff(Y, n=2, axis=1) / self.W[:, 2:] if Y.shape[1] > 2 else d
        s = np.std(d2, axis=1) / math.sqrt(6) if d2.size else np.ones(Y.shape[0])
        self.scale = np.maximum(s, 1e-6 * np.maximum(np.mean(np.abs(Y) / self.W, axis=1), 1e-9))
        self.cap = float(1e3 * max(1.0, float(np.max(np.abs(Y)))))
        # the smallest error a stock is credited with (its rounding): a noise-free fit is not worth -inf
        self.floor = (1e-6 * np.maximum(np.mean(np.abs(Y) / self.W, axis=1), 1e-9)) ** 2

    @property
    def m(self) -> int:
        return self.Y.shape[0]

    @property
    def T(self) -> int:
        return self.Y.shape[1] - 1

    @property
    def n_obs(self) -> int:
        return self.Y.size


@dataclass
class Fit:
    terms: list[Term]
    theta: np.ndarray
    x0: np.ndarray
    nll: float
    k: int
    aicc: float
    X: np.ndarray
    bounded: bool = True
    score: float = math.nan       # what the search ranks by (search.search: AICc plus the search's price)
    family: str = ""

    @property
    def size(self) -> int:
        return len(self.terms)


def nll_of(X: np.ndarray, D: Data) -> float:
    R = (X[: D.m] - D.Y) / D.W
    n = D.Y.shape[1]
    rss = np.maximum(np.sum(R * R, axis=1), D.floor * n)
    return float(np.sum(0.5 * n * np.log(rss / n)) + np.sum(np.log(D.W)))


def aicc(nll: float, k: int, N: int) -> float:
    if N - k - 1 <= 0:
        return math.inf
    return 2 * nll + 2 * k + 2 * k * (k + 1) / (N - k - 1)


def fit(terms: list[Term], D: Data, theta0: np.ndarray, x00: np.ndarray, iters: int = 200) -> Fit:
    if D.allow is not None:                              # (boundary: docs/research/declared-boundary.md): a term off the declared boundary is left out
        keep = [k for k, t in enumerate(terms) if D.allow(t)]
        if len(keep) < len(terms):
            terms, theta0 = [terms[k] for k in keep], np.asarray(theta0, dtype=float)[keep]
    src, dst, a, b = arrays(terms)
    K = len(terms)
    n = D.m + D.hidden

    def simulate(p):
        return run(p[:K], p[K:], src, dst, a, b, D.inj, D.T, D.cap)

    scale = D.scale.copy()

    def resid(p):
        X = simulate(p)
        return (((X[: D.m] - D.Y) / D.W) / scale[:, None]).ravel()

    p0 = np.concatenate([np.maximum(theta0, 0.0), np.maximum(x00, 0.0)])
    best = p0
    for _ in range(2):                                   # the scales re-read once from the fit
        try:
            r = least_squares(resid, best, bounds=(0.0, np.inf), x_scale="jac", max_nfev=iters * (len(p0) + 1),
                              method="trf", ftol=1e-10, xtol=1e-10)
            best = r.x
        except (ValueError, FloatingPointError):
            break
        X = simulate(best)
        rms = np.sqrt(np.mean(((X[: D.m] - D.Y) / D.W) ** 2, axis=1))
        new = np.maximum(rms, np.sqrt(D.floor))
        if np.all(np.abs(np.log(new / scale)) < 0.2):
            break
        scale = new
    X = simulate(best)
    nll = nll_of(X, D)
    k = K + n + D.m
    ok = bounded(best[:K], X, src, dst, a, b, D)
    claims = D.claim * sum(1 for t, th in zip(terms, best[:K]) if (t.src is None) != (t.dst is None) and th > 0)   # (boundary: docs/research/declared-boundary.md)
    return Fit(list(terms), best[:K].copy(), best[K:].copy(), nll, k, aicc(nll, k, D.n_obs) + claims if ok else math.inf, X, ok)


def bounded(theta, X, src, dst, a, b, D: Data) -> bool:
    """The SD prior that nothing grows without limit: the free run, continued for as many steps as
    the run (at least 10) from where the fit ends and from every measured state (the hidden stocks
    at their fitted levels), keeps every measured stock within GROWTH times its largest measured
    level (a stock that never rose above 0 within GROWTH times the largest of all). A model fitted
    on one path that explodes from a state next to it would forecast nothing from a measured level."""
    H = max(10, D.T)
    inj = np.zeros((H + 1, X.shape[0]))
    top = np.max(np.abs(D.Y), axis=1)
    lim = GROWTH * np.where(top > 0, top, max(1e-9, float(np.max(top))))
    starts = [X[:, -1]] + [np.concatenate([D.Y[:, k], X[D.m:, k]]) for k in range(D.Y.shape[1])]
    for x in starts:
        Z = run(theta, x.copy(), src, dst, a, b, inj, H, D.cap)
        if not (np.all(np.isfinite(Z)) and np.all(np.max(Z[: D.m], axis=1) <= lim)):
            return False
    return True
