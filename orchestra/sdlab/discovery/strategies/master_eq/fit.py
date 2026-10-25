"""Fitting a master-equation model's numbers to counted levels (docs/research/master_eq.md).

E[change of a step | levels at its start] = sum over terms of theta_m x base_m x e_m (terms.py): the
mean-field step, linear in the numbers. Its covariance comes from the same numbers: a term's units
arrive as Poisson counts of mean lambda_m = theta_m x base_m, except that the units of one source
region split among the terms taking from it (a multinomial over the region's x_i units, each going
with probability lambda_m / x_i), which makes the moves out of a region quieter (variance
lambda (1 - p)) and negatively correlated. Two noise readings are offered and chosen by likelihood:

  binomial   the multinomial (particles: every unit decides on its own)
  poisson    every term Poisson (the ladder's counting noise)

The numbers are found by generalised least squares on the Gaussian approximation (each step's
change whitened by its covariance, the covariance re-evaluated at the new numbers a few times), with
every number >= 0 (non-negative least squares on the whitened Gram matrix). The whitened residuals
then have unit variance (times a dispersion phi fitted beside them), so a term is worth keeping when
it lowers the whitened RSS by more than phi x log(N) (BIC, N = steps x stocks).
"""

from __future__ import annotations

import math

import numpy as np
from scipy.optimize import nnls

from . import terms as T

RIDGE = 0.05          # added to every stock's variance: a step where nothing can move is not infinitely sure
ITER = 3              # covariance re-evaluations


class Problem:
    """The data and a pool of terms: bases R (n x M) and effects E (M x S)."""

    def __init__(self, D: T.Data, pool: list[T.Term]):
        self.D = D
        self.pool = list(pool)
        self.R = np.column_stack([T.base(t, D) for t in self.pool]) if self.pool else np.zeros((D.n, 0))
        self.E = np.array([T.effect(t, D.S) for t in self.pool]).reshape(len(self.pool), D.S)
        self.src = np.array([-1 if T.takes_from(t) is None else T.takes_from(t) for t in self.pool], int)
        self.N = D.n * D.S
        self.phi1 = False          # the dispersion held at 1 (ml.py) instead of fitted

    def add(self, more: list[T.Term]) -> list[int]:
        """Add terms (those not already in the pool); their indices."""
        have = {t.key(): k for k, t in enumerate(self.pool)}
        new = [t for t in more if t.key() not in have]
        if new:
            self.R = np.column_stack([self.R] + [T.base(t, self.D) for t in new])
            self.E = np.vstack([self.E] + [T.effect(t, self.D.S)[None] for t in new])
            self.src = np.concatenate([self.src, [-1 if T.takes_from(t) is None else T.takes_from(t) for t in new]]).astype(int)
            self.pool += new
            have = {t.key(): k for k, t in enumerate(self.pool)}
        return [have[t.key()] for t in more]


def covariance(P: Problem, theta: np.ndarray, mode: str) -> np.ndarray:
    """Each step's covariance of the change (n x S x S) at these numbers."""
    D = P.D
    act = np.flatnonzero(theta > 0)
    lam = np.maximum(P.R[:, act] * theta[act], 0.0)                    # n x a
    E = P.E[act]                                                        # a x S
    S = D.S
    Sig = (lam @ (E[:, :, None] * E[:, None, :]).reshape(len(act), S * S)).reshape(-1, S, S)
    if mode == "binomial":
        for i in np.unique(P.src[act]):
            if i < 0:
                continue
            sel = P.src[act] == i
            v = lam[:, sel] @ E[sel]                                        # n x S: the region's expected outgoing change
            xi = np.maximum(np.maximum(D.x[:, i], 1.0), lam[:, sel].sum(axis=1))      # never more units out than there are
            Sig -= (v[:, :, None] * v[:, None, :]) / xi[:, None, None]
    Sig += RIDGE * np.eye(D.S)[None]
    return Sig


def whiten(P: Problem, Sig: np.ndarray, cols: np.ndarray, chunk: int = 256) -> tuple[np.ndarray, np.ndarray, float, float]:
    """(G, b, c, logdet) of the whitened problem over the columns `cols`: G = sum_k Dk' S_k^-1 Dk,
    b = sum_k Dk' S_k^-1 d_k, c = sum_k d_k' S_k^-1 d_k, logdet = sum_k log det S_k."""
    D = P.D
    M = len(cols)
    G, b, c, ld = np.zeros((M, M)), np.zeros(M), 0.0, 0.0
    E = P.E[cols]
    for a in range(0, D.n, chunk):
        sl = slice(a, min(D.n, a + chunk))
        L = np.linalg.cholesky(Sig[sl])                                    # k x S x S
        Dk = np.einsum("km,ms->ksm", P.R[sl][:, cols], E)                  # k x S x M
        Wd = np.linalg.solve(L, Dk)                                        # L^-1 Dk
        wy = np.linalg.solve(L, D.d[sl][..., None])[..., 0]                # k x S
        Wf = Wd.reshape(-1, M)
        G += Wf.T @ Wf
        b += Wf.T @ wy.reshape(-1)
        c += float((wy ** 2).sum())
        ld += float(2 * np.log(np.diagonal(L, axis1=1, axis2=2)).sum())
    return G, b, c, ld


def nnls_gram(G: np.ndarray, b: np.ndarray) -> np.ndarray:
    """argmin theta' G theta - 2 b' theta over theta >= 0."""
    M = len(b)
    if M == 0:
        return np.zeros(0)
    s = np.sqrt(np.maximum(np.diag(G), 1e-300))
    Gs = G / s[:, None] / s[None, :]
    bs = b / s
    Gs = Gs + 1e-10 * np.eye(M)
    try:
        R = np.linalg.cholesky(Gs)
    except np.linalg.LinAlgError:
        w, V = np.linalg.eigh(Gs)
        R = (V * np.sqrt(np.maximum(w, 1e-12))).T
        z = np.linalg.lstsq(R.T, bs, rcond=None)[0]
        x = nnls(R, z, maxiter=50 * M)[0]
        return x / s
    z = np.linalg.solve(R, bs)                                            # R R' = Gs: min |R' x - z|
    x = nnls(R.T, z, maxiter=50 * M)[0]
    return x / s


def rss_of(G, b, c, th) -> float:
    return float(c - 2 * b @ th + th @ G @ th)


class Fit:
    def __init__(self, P: Problem, active: np.ndarray, theta: np.ndarray, mode: str, rss: float, logdet: float, Sig: np.ndarray):
        self.P, self.active, self._theta, self.mode, self.rss, self.logdet, self.Sig = P, active, theta, mode, rss, logdet, Sig

    @property
    def theta(self) -> np.ndarray:
        """The numbers over the whole pool (terms added to the pool since the fit: 0)."""
        M = len(self.P.pool)
        if len(self._theta) < M:
            self._theta = np.concatenate([self._theta, np.zeros(M - len(self._theta))])
        return self._theta

    @property
    def phi(self) -> float:
        return self.rss / max(1, self.P.N)

    def nll2(self) -> float:
        """-2 log likelihood of the Gaussian approximation, the dispersion fitted."""
        N = self.P.N
        if self.P.phi1:
            return self.rss + self.logdet
        return N * math.log(max(self.phi, 1e-300)) + self.logdet + N

    def terms(self) -> list[tuple[T.Term, float]]:
        return [(self.P.pool[a], float(self.theta[a])) for a in self.active if self.theta[a] > 0]


def start_numbers(P: Problem, cols: np.ndarray) -> np.ndarray:
    """Numbers from a roughly weighted least squares: each step's change scaled by its size."""
    D = P.D
    v = np.maximum(np.abs(D.d).mean(axis=0), 1.0)
    Sig = np.repeat(np.diag(v)[None], D.n, axis=0)
    G, b, _, _ = whiten(P, Sig, cols)
    th = np.zeros(len(P.pool))
    th[cols] = nnls_gram(G, b)
    return th


def fit(P: Problem, cols, mode: str, theta0: np.ndarray | None = None, iters: int = ITER) -> Fit:
    """GLS numbers of the terms `cols` (>= 0) under one noise reading."""
    cols = np.asarray(sorted(set(int(c) for c in cols)), int)
    th = start_numbers(P, cols) if theta0 is None else _restrict(theta0, cols, len(P.pool))
    if not th[cols].any():
        th = start_numbers(P, cols)
    for _ in range(iters):
        Sig = covariance(P, th, mode)
        G, b, c, ld = whiten(P, Sig, cols)
        new = np.zeros(len(P.pool))
        new[cols] = nnls_gram(G, b)
        th = new
    Sig = covariance(P, th, mode)
    G, b, c, ld = whiten(P, Sig, cols)
    return Fit(P, cols, th, mode, rss_of(G, b, c, th[cols]), ld, Sig)


def _restrict(theta0, cols, M):
    th = np.zeros(M)
    th0 = np.asarray(theta0, float)
    k = min(len(th0), M)
    th[:k] = th0[:k]
    keep = np.zeros(M, bool)
    keep[cols] = True
    th[~keep] = 0.0
    return th


def prune(f: Fit, pen: float, protect: set | None = None, deadline: float | None = None) -> Fit:
    """Backward elimination at a fixed covariance: drop the active term whose removal raises the
    whitened RSS least while that rise is under pen x phi; then refit with the covariance renewed."""
    import time
    P = f.P
    cols = [int(a) for a in f.active if f.theta[a] > 0]
    G, b, c, _ = whiten(P, f.Sig, np.asarray(cols, int))
    th = f.theta[cols].copy()
    base = rss_of(G, b, c, th)
    phi = max(base / P.N, 1e-12)
    while len(cols) > 0:
        if deadline is not None and time.perf_counter() > deadline:
            break
        best = None
        # rank by the unconstrained t^2 on the active set, then check the best few exactly
        try:
            Ginv = np.linalg.inv(G + 1e-12 * np.eye(len(cols)) * max(1.0, np.trace(G) / max(1, len(cols))))
            t2 = th ** 2 / np.maximum(np.diag(Ginv), 1e-300)
        except np.linalg.LinAlgError:
            t2 = th ** 2 * np.diag(G)
        order = np.argsort(t2)
        for pos in order[:4]:
            if protect and cols[pos] in protect:
                continue
            keep = np.delete(np.arange(len(cols)), pos)
            th2 = nnls_gram(G[np.ix_(keep, keep)], b[keep])
            r = rss_of(G[np.ix_(keep, keep)], b[keep], c, th2)
            if best is None or r < best[0]:
                best = (r, pos, keep, th2)
        if best is None or best[0] - base > pen * phi:
            break
        _, pos, keep, th2 = best
        cols = [cols[k] for k in keep]
        G, b = G[np.ix_(keep, keep)], b[keep]
        th = th2
        base = best[0]
        # zeros from the refit go too
        nz = th > 0
        if not nz.all():
            cols = [cc for cc, z in zip(cols, nz) if z]
            G, b, th = G[np.ix_(nz, nz)], b[nz], th[nz]
    theta = np.zeros(len(P.pool))
    theta[cols] = th
    return fit(P, cols, f.mode, theta)


def gain_of(f: Fit, cand: list[int]) -> list[tuple[float, int]]:
    """For each candidate column: how much adding it alone lowers the whitened RSS (at f's covariance)."""
    P = f.P
    cols = [int(a) for a in f.active if f.theta[a] > 0]
    allc = np.asarray(cols + [c for c in cand if c not in cols], int)
    G, b, c, _ = whiten(P, f.Sig, allc)
    k = len(cols)
    th = f.theta[cols]
    base = rss_of(G[:k, :k], b[:k], c, th)
    out = []
    for j in range(k, len(allc)):
        idx = list(range(k)) + [j]
        Gs, bs = G[np.ix_(idx, idx)], b[idx]
        th2 = nnls_gram(Gs, bs)
        out.append((base - rss_of(Gs, bs, c, th2), int(allc[j])))
    return out


def nll_at(P: Problem, theta: np.ndarray, mode: str) -> float:
    """-2 log likelihood (dispersion 1) of these numbers as they stand: no refit."""
    Sig = covariance(P, theta, mode)
    act = np.flatnonzero(theta > 0)
    r = P.D.d - (P.R[:, act] * theta[act]) @ P.E[act]
    L = np.linalg.cholesky(Sig)
    w = np.linalg.solve(L, r[..., None])[..., 0]
    return float((w ** 2).sum() + 2 * np.log(np.diagonal(L, axis1=1, axis2=2)).sum())


def swap(f: Fit, alternatives: dict[int, list[int]], rounds: int = 20, tries: int = 6) -> Fit:
    """Replace an active term by one of its alternatives (the same source sent elsewhere) while that
    raises the likelihood (backward elimination never swaps one reading for another of the same size:
    a slow bin's drain and a move into its neighbour). Every swap is first priced with the term's
    number carried over (the likelihood with the covariance the swap implies: a move changes the
    variance as well as the mean, so the RSS alone misleads), and the best few are refitted."""
    P = f.P
    for _ in range(rounds):
        cols = [int(a) for a in f.active if f.theta[a] > 0]
        pool = sorted(set(cols) | {c for a in cols for c in alternatives.get(a, [])})
        if len(pool) == len(cols):
            return f
        G, b, _, _ = whiten(P, f.Sig, np.asarray(pool, int))
        at = {cc: k for k, cc in enumerate(pool)}
        ranked = []
        for pos, a in enumerate(cols):
            for alt in alternatives.get(a, []):
                if alt in cols:
                    continue
                cs = cols[:pos] + [alt] + cols[pos + 1:]
                idx = [at[x] for x in cs]
                th = np.zeros(len(P.pool))
                th[cs] = nnls_gram(G[np.ix_(idx, idx)], b[idx])
                ranked.append((nll_at(P, th, f.mode), cs, th))
        ranked.sort(key=lambda x: x[0])
        better = None
        for _, cs, th in ranked[:tries]:
            g = fit(P, cs, f.mode, th, iters=2)
            if g.nll2() + 1e-6 < f.nll2() and (better is None or g.nll2() < better.nll2()):
                better = g
        if better is None:
            return f
        f = better
    return f
