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


def nll(theta: np.ndarray, V: np.ndarray, Z: np.ndarray, Y: np.ndarray, delta: float = ROUNDING, grad: bool = True):
    """The negative log-likelihood (without the constant) and its gradient in theta.
    V: stocks x flows; Z: flows x steps; Y: stocks x steps."""
    S, T = Y.shape
    q = np.maximum(theta, 0.0)[:, None] * Z                       # F x T
    r = Y - V @ q                                                   # S x T
    sig = np.einsum("if,ft,jf->tij", V, q, V, optimize=True)
    sig[:, np.arange(S), np.arange(S)] += delta
    W = np.linalg.inv(sig)                                          # T x S x S
    sign, logdet = np.linalg.slogdet(sig)
    a = np.einsum("tij,jt->ti", W, r)                               # T x S
    val = 0.5 * float(logdet.sum() + np.einsum("it,ti->", r, a))
    if not grad:
        return val
    va = V.T @ a.T                                                  # F x T
    M = np.einsum("tij,jf->tif", W, V, optimize=True)
    dq = np.einsum("if,tif->ft", V, M, optimize=True)               # v_f' W_t v_f
    g = (Z * (-va + 0.5 * (dq - va * va))).sum(axis=1)
    return val, g


def gaussian_nll(Y: np.ndarray, mu: np.ndarray) -> float:
    """Homoscedastic, independent rows (for the noise-free check): 0.5 T sum_s log(rss_s / T)."""
    T = Y.shape[1]
    rss = ((Y - mu) ** 2).sum(axis=1)
    return 0.5 * T * float(np.log(np.maximum(rss / T, 1e-300)).sum())
