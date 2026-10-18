"""The linear noise approximation's likelihood of a run's per-step changes.

Each flow f moves q_f(t) = theta_f x z_f(t) in step t (z_f: 1 for an outside inflow, the driver's
level for a proportional flow, masked to the steps where the flow's number holds). Counting noise
draws each flow's amount around q_f on its own (Poisson: variance = mean), and every stock the flow
touches sees the same draw (v_f: -1 at the source, +1 at the destination, -per at a stock a co-flow
uses up). So a step's change is, to second order,

    dy_t ~ Normal(V q_t, V diag(q_t) V' + delta I)

(the compartmental analogue's Cov(changes) = S diag(q) S'; delta is the levels' rounding to whole
things). A move and a link with the same mean differ here: a move's draw leaves its source in the
same step it arrives, a link's does not.
"""

from __future__ import annotations

import numpy as np

ROUNDING = 1 / 6        # the variance of a change between two levels each rounded to a whole thing


def nll(theta: np.ndarray, V: np.ndarray, Z: np.ndarray, Y: np.ndarray, delta: float = ROUNDING, grad: bool = True,
        pool: np.ndarray | None = None, sign: np.ndarray | None = None, eps: float = 0.05, tau: np.ndarray | None = None):
    """The negative log-likelihood (without the constant) and its gradient in theta.
    V: stocks x flows; Z: flows x steps; Y: stocks x steps.

    pool (optional, per atom): the stock whose outside inflow the atom is part of (-1: none). An
    outside inflow is one draw, whatever its equation: its constant (sign +1) and the terms that
    lower it as a level rises (a gap, sign -1) add up to one rate, whose variance is that rate
    (its size, kept above eps).

    tau (optional, per stock): variance beyond counting noise (what the flows do not explain: a
    misfit, an unmodelled input), so that no reading buys variance with flows that cancel. With tau,
    the gradient is returned for (theta, tau)."""
    S, T = Y.shape
    F = len(theta)
    pool = np.full(F, -1) if pool is None else pool
    sign = np.ones(F) if sign is None else sign
    q = np.maximum(theta, 0.0)[:, None] * Z                       # F x T
    r = Y - V @ q                                                   # S x T
    rest = pool < 0
    Vr = V[:, rest]
    sig = np.einsum("if,ft,jf->tij", Vr, q[rest], Vr, optimize=True)
    pooled = ~rest
    net = np.zeros((S, T))
    if pooled.any():
        np.add.at(net, pool[pooled], sign[pooled, None] * q[pooled])
    # a rate below zero is not a draw of nothing: what a gap takes beyond the inflow is noise again
    live = np.abs(net) > eps
    sig[:, np.arange(S), np.arange(S)] += np.where(live, np.abs(net), eps).T + delta + (0.0 if tau is None else np.maximum(tau, 0.0))
    W = np.linalg.inv(sig)                                          # T x S x S
    _, logdet = np.linalg.slogdet(sig)
    a = np.einsum("tij,jt->ti", W, r)                               # T x S
    val = 0.5 * float(logdet.sum() + np.einsum("it,ti->", r, a))
    if not grad:
        return val
    Wd = W[:, np.arange(S), np.arange(S)].T                         # S x T
    va = V.T @ a.T                                                  # F x T: v_f . a_t (the mean's part)
    g = np.empty(F)
    M = np.einsum("tij,jf->tif", W, Vr, optimize=True)
    dq = np.einsum("if,tif->ft", Vr, M, optimize=True)              # v_f' W_t v_f
    g[rest] = (Z[rest] * (-va[rest] + 0.5 * (dq - va[rest] ** 2))).sum(axis=1)
    if pooled.any():
        p = pool[pooled]
        dvar = sign[pooled, None] * (live * np.sign(net))[p] * (Wd[p] - a.T[p] ** 2)
        g[pooled] = (Z[pooled] * (-va[pooled] + 0.5 * dvar)).sum(axis=1)
    if tau is not None:
        return val, np.concatenate([g, 0.5 * (Wd - a.T ** 2).sum(axis=1)])
    return val, g


def gaussian_nll(Y: np.ndarray, mu: np.ndarray) -> float:
    """Homoscedastic, independent rows (for the noise-free check): 0.5 T sum_s log(rss_s / T)."""
    T = Y.shape[1]
    rss = ((Y - mu) ** 2).sum(axis=1)
    return 0.5 * T * float(np.log(np.maximum(rss / T, 1e-300)).sum())
