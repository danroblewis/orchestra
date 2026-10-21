"""Maximum likelihood for a master-equation model's numbers (the Gaussian approximation of fit.py with
the covariance a function of the numbers, the dispersion profiled out).

Generalised least squares (fit.fit) treats each step's covariance as known; the numbers then explain
the means only. But the covariance carries information too: two moves that cancel in the mean (a
two-way exchange between chambers) leave the same mean and twice the noise. The likelihood
-2 log L = N log(Q / N) + sum_k log det S_k (Q = sum_k r_k' S_k^-1 r_k) weighs both, and is
minimised here over the numbers (>= 0) by L-BFGS-B with its exact gradient. With the dispersion held
at 1 (P.phi1: counted units moving one by one, the noise exactly the multinomial's or Poisson's),
-2 log L = Q + sum_k log det S_k: the size of the noise then measures the size of the flows too (a
stock fed and drained in proportion: scaling both alike leaves the mean, not the noise).
"""

from __future__ import annotations

import numpy as np
from scipy.optimize import minimize

from . import fit as F
from . import terms as T


def objective(P: F.Problem, cols: np.ndarray, mode: str):
    D = P.D
    R = P.R[:, cols]                                   # n x M
    E = P.E[cols]                                      # M x S
    src = P.src[cols]
    N = P.N
    S = D.S
    eye = np.eye(S)[None]
    srcs = [i for i in np.unique(src) if i >= 0] if mode == "binomial" else []
    fixed = P.phi1                                     # the dispersion held at 1: the noise is exactly the counts'
    EE = (E[:, :, None] * E[:, None, :]).reshape(len(cols), S * S)      # e_m e_m' flattened

    def f(th):
        lam = R * th                                   # n x M
        r = D.d - lam @ E                              # n x S
        Sig = (lam @ EE).reshape(-1, S, S) + F.RIDGE * eye
        V, X = {}, {}
        for i in srcs:
            sel = src == i
            v = lam[:, sel] @ E[sel]
            xi = np.maximum(np.maximum(D.x[:, i], 1.0), lam[:, sel].sum(axis=1))
            Sig -= (v[:, :, None] * v[:, None, :]) / xi[:, None, None]
            V[i], X[i] = v, xi
        try:
            L = np.linalg.cholesky(Sig)
        except np.linalg.LinAlgError:
            return 1e30, np.zeros_like(th)
        Si = np.linalg.inv(Sig)                        # n x S x S
        w = (Si @ r[..., None])[..., 0]             # S^-1 r
        Q = float((r * w).sum())
        ld = float(2 * np.log(np.diagonal(L, axis1=1, axis2=2)).sum())
        val = (Q if fixed else N * np.log(max(Q, 1e-300) / N)) + ld
        ew = w @ E.T                                   # n x M: e_m' w
        eSe = Si.reshape(-1, S * S) @ EE.T            # n x M: e_m' S^-1 e_m
        dQ = -2 * (R * ew).sum(axis=0) - (R * ew ** 2).sum(axis=0)
        dL = (R * eSe).sum(axis=0)
        for i in srcs:
            sel = np.flatnonzero(src == i)
            v, xi = V[i], X[i]
            vw = (v * w).sum(axis=1)                   # n
            Sv = (Si @ v[..., None])[..., 0]        # n x S
            Rm = R[:, sel] / xi[:, None]
            dQ[sel] += 2 * (Rm * ew[:, sel] * vw[:, None]).sum(axis=0)
            dL[sel] -= 2 * (Rm * (Sv @ E[sel].T)).sum(axis=0)
        grad = (dQ if fixed else N / max(Q, 1e-300) * dQ) + dL
        return val, grad

    return f


def refine(P: F.Problem, cols, theta0: np.ndarray, mode: str, maxiter: int = 200) -> F.Fit:
    """The ML numbers of the terms `cols`, from theta0; returned as a fit.Fit (its covariance at them)."""
    cols = np.asarray(sorted(set(int(c) for c in cols)), int)
    if len(cols) == 0:
        return F.fit(P, cols, mode)
    th0 = np.asarray(theta0, float)
    th0 = np.concatenate([th0, np.zeros(max(0, len(P.pool) - len(th0)))])[cols]
    scale = np.maximum(th0, 1e-6 * max(1e-12, float(th0.max()) if th0.size else 1.0))
    f = objective(P, cols, mode)

    def g(z):
        v, gr = f(z * scale)
        return v, gr * scale

    v0, _ = f(th0)
    sol = minimize(g, th0 / scale, jac=True, method="L-BFGS-B", bounds=[(0, None)] * len(cols), options={"maxiter": maxiter})
    th = sol.x * scale if sol.fun <= v0 else th0
    theta = np.zeros(len(P.pool))
    theta[cols] = th
    keep = cols[th > 0]
    return F.fit(P, keep, mode, theta, iters=0)


NONLINEAR_PRICE = 2.0     # a product (bind, catalysed move) costs this many numbers: a curve must beat a line clearly


def bic(f: F.Fit, pen: float) -> float:
    """BIC; with no boundary declared, each outside flow (a term's era splits are one flow) also pays
    the boundary claim's price, P.claim_price (boundary.CLAIM_PRICE) numbers (0 where declared: the
    pool then holds only the outside terms the boundary allows)."""
    claim = getattr(f.P, "claim_price", 0.0)
    flows = {(t.kind, t.src, t.dst, t.other) for t, _ in f.terms() if T.outside_sides(t)} if claim else ()
    return f.nll2() + pen * (sum(NONLINEAR_PRICE if t.kind in ("bind", "catal") else 1.0 for t, _ in f.terms()) + claim * len(flows))


def active(f: F.Fit) -> list[int]:
    return [int(a) for a in f.active if f.theta[a] > 0]


def wald(f: F.Fit) -> tuple[list[int], np.ndarray]:
    """The active terms and their t^2 at f's covariance (weakest first)."""
    cols = active(f)
    G, _, _, _ = F.whiten(f.P, f.Sig, np.asarray(cols, int))
    th = f.theta[cols]
    try:
        var = np.diag(np.linalg.inv(G + 1e-12 * np.eye(len(cols)) * max(1.0, np.trace(G) / max(1, len(cols)))))
    except np.linalg.LinAlgError:
        var = 1.0 / np.maximum(np.diag(G), 1e-300)
    return cols, f.phi * th ** 2 / np.maximum(var, 1e-300)


BATCH_T2 = 1.0            # terms this weak (Wald t^2) are first dropped together


def prune(f: F.Fit, pen: float, tries: int = 2, deadline: float | None = None, protect: set | None = None,
          maxiter: int = 60) -> F.Fit:
    """Backward elimination by BIC with ML refits: the weakest few terms (Wald) are each dropped and the
    rest refitted; the best drop is kept while it lowers BIC. Terms far below any price (t^2 under
    BATCH_T2) are first tried all at once."""
    import time
    cur = bic(f, pen)
    batch = True
    while True:
        if deadline is not None and time.perf_counter() > deadline:
            return f
        cols, t2 = wald(f)
        if len(cols) <= 1:
            return f
        weak = [c for c, v in zip(cols, t2) if v < BATCH_T2 and not (protect and c in protect)]
        if batch and len(weak) >= 2:
            g = refine(f.P, [c for c in cols if c not in weak], f.theta, f.mode, maxiter=maxiter)
            if bic(g, pen) < cur:
                cur, f = bic(g, pen), g
                continue
            batch = False
        best = None
        for pos in np.argsort(t2)[: tries + len(protect or ())]:
            if protect and cols[pos] in protect:
                continue
            g = refine(f.P, cols[:pos] + cols[pos + 1:], f.theta, f.mode, maxiter=maxiter)
            b = bic(g, pen)
            if best is None or b < best[0]:
                best = (b, g)
        if best is None or best[0] >= cur:
            return f
        cur, f = best


def swap(f: F.Fit, alternatives: dict[int, list[int]], pen: float, rounds: int = 20, tries: int = 4, deadline: float | None = None) -> F.Fit:
    """fit.swap's ranking (the swap's GLS numbers priced by the likelihood as they stand), the best few
    refitted by ML; the best kept while it lowers BIC."""
    import time
    P = f.P
    for _ in range(rounds):
        if deadline is not None and time.perf_counter() > deadline:
            return f
        cols = active(f)
        pool = sorted(set(cols) | {c for a in cols for c in alternatives.get(a, [])})
        if len(pool) == len(cols):
            return f
        G, b, _, _ = F.whiten(P, f.Sig, np.asarray(pool, int))
        at = {cc: k for k, cc in enumerate(pool)}
        ranked = []
        for pos, a in enumerate(cols):
            for alt in alternatives.get(a, []):
                if alt in cols:
                    continue
                cs = cols[:pos] + [alt] + cols[pos + 1:]
                idx = [at[x] for x in cs]
                th = np.zeros(len(P.pool))
                th[cs] = F.nnls_gram(G[np.ix_(idx, idx)], b[idx])
                ranked.append((F.nll_at(P, th, f.mode), cs, th))
        ranked.sort(key=lambda x: x[0])
        cur = bic(f, pen)
        better = None
        for _, cs, th in ranked[:tries]:
            g = refine(P, cs, th, f.mode, maxiter=100)
            if bic(g, pen) + 1e-6 < cur and (better is None or bic(g, pen) < bic(better, pen)):
                better = g
        if better is None:
            return f
        f = better
    return f


def rank_additions(f: F.Fit, cand: list[int]) -> list[tuple[float, int]]:
    """Candidate terms ranked by the likelihood with each added (its GLS numbers at f's covariance,
    priced with the covariance they imply: a reverse move earns its place by the noise, not the mean)."""
    P = f.P
    cols = active(f)
    pool = np.asarray(cols + [c for c in cand if c not in cols], int)
    G, b, _, _ = F.whiten(P, f.Sig, pool)
    k = len(cols)
    out = []
    for j in range(k, len(pool)):
        idx = list(range(k)) + [j]
        th = np.zeros(len(P.pool))
        th[pool[idx]] = F.nnls_gram(G[np.ix_(idx, idx)], b[idx])
        if th[pool[j]] > 0:
            out.append((F.nll_at(P, th, f.mode), int(pool[j])))
    out.sort()
    return out
