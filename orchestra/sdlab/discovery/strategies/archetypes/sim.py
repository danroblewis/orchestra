"""The free run of a term model, stepped exactly as the engine steps it (sdlab/discovery/simulate.py):
Euler with dt = 1, every amount theta x monomial (>= 0), a stock's outflows sharing what it holds
when they want more, levels floored at 0, announced injections added at the start of their step."""

from __future__ import annotations

import numpy as np
from numba import njit


@njit(cache=True)
def run(theta, x0, src, dst, a, b, inj, T, cap):
    """Levels (stocks x T + 1) from x0; inj is (T + 1) x stocks (added before the step that ends
    at that sample); a level above cap stops the run (the rest stay at cap)."""
    n = x0.shape[0]
    K = theta.shape[0]
    X = np.empty((n, T + 1))
    L = x0.copy()
    for i in range(n):
        X[i, 0] = L[i]
    amt = np.empty(K)
    want = np.empty(n)
    blown = False
    for k in range(1, T + 1):
        if blown:
            for i in range(n):
                X[i, k] = cap
            continue
        for i in range(n):
            L[i] = max(0.0, L[i] + inj[k, i])
            want[i] = 0.0
        for q in range(K):
            v = theta[q]
            if a[q] >= 0:
                v *= L[a[q]]
            if b[q] >= 0:
                v *= L[b[q]]
            amt[q] = v if v > 0.0 else 0.0
            if src[q] >= 0:
                want[src[q]] += amt[q]
        for q in range(K):
            s = src[q]
            if s >= 0 and want[s] > L[s] and L[s] > -1.0:
                amt[q] *= max(0.0, L[s]) / want[s]
        nxt = L.copy()
        for q in range(K):
            if src[q] >= 0:
                nxt[src[q]] -= amt[q]
            if dst[q] >= 0:
                nxt[dst[q]] += amt[q]
        for i in range(n):
            v = nxt[i] if nxt[i] >= 0.0 else 0.0
            if not np.isfinite(v) or v > cap:
                blown = True
                v = cap
            L[i] = v
            X[i, k] = v
    return X
