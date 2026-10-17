"""Changes in a series' mean: optimal partitioning with pruning (PELT).

A stock's outside inflow may change over time (demand rises, a budget is set, night falls): it is a
series of pieces whose changes are found in what the levels leave unexplained.
"""

from __future__ import annotations

import math

import numpy as np
from numba import njit


@njit(cache=True)
def _last_cut(r: np.ndarray, min_len: int, pen: float) -> np.ndarray:
    n = r.shape[0]
    pre = np.zeros(n + 1)
    pre2 = np.zeros(n + 1)
    for i in range(n):
        pre[i + 1] = pre[i] + r[i]
        pre2[i + 1] = pre2[i] + r[i] * r[i]
    f = np.empty(n + 1)
    last = np.zeros(n + 1, np.int64)
    f[0] = -pen
    cand = np.empty(n + 1, np.int64)
    cand[0] = 0
    nc = 1
    for t in range(1, n + 1):
        best = np.inf
        arg = 0
        for ci in range(nc):
            s0 = cand[ci]
            if t - s0 < min_len and t != n:
                continue
            s = pre[t] - pre[s0]
            v = f[s0] + (pre2[t] - pre2[s0] - s * s / (t - s0)) + pen
            if v < best:
                best = v
                arg = s0
        if best == np.inf:
            s = pre[t]
            best = f[0] + (pre2[t] - s * s / t) + pen
            arg = 0
        f[t] = best
        last[t] = arg
        k = 0
        for ci in range(nc):
            s0 = cand[ci]
            s = pre[t] - pre[s0]
            if f[s0] + (pre2[t] - pre2[s0] - s * s / (t - s0)) <= f[t] + pen:
                cand[k] = s0
                k += 1
        cand[k] = t
        nc = k + 1
    return last


def pelt(r: np.ndarray, min_len: int, mult: float) -> list[int]:
    """Cuts 0 = c0 < c1 < ... < ck = n of r into pieces of constant mean. Each change costs
    mult x log n x the noise variance (estimated from successive differences, so that the changes
    themselves do not inflate it)."""
    r = np.nan_to_num(np.asarray(r, dtype=float))
    n = r.shape[0]
    dv = float(np.sum(np.diff(r) ** 2))
    pen = mult * math.log(n) * ((dv / (2 * max(1, n - 1))) or 1.0)
    last = _last_cut(r, int(min_len), pen)
    cuts = []
    t = n
    while t > 0:
        cuts.append(t)
        t = int(last[t])
    cuts.append(0)
    return cuts[::-1]
