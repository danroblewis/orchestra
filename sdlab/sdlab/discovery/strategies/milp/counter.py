"""Counters fitted in level space (the idea of k8s-303-c1, written afresh for milp; docs/research/k8s-306-s2.md).

A final stock (a counter: nothing leaves it) grows to many times what moves into it in a step. With
measurement error proportional to its level, its one-step changes carry the difference of two level
errors, which buries a small inflow (306 meas-short: errors_total takes 0.03 x inflight, about 21 a
step, against a change scatter of 265). Its level keeps everything that came in, so its row is fitted
in level space instead: the level less a free start against the cumulative sum of what the model moves
into it, each step weighed by the level's own noise sd.

Which counters: those whose change residual shows measurement error, i.e. a lag-1 autocorrelation
below -3 / sqrt(T) (differenced white level error gives -0.5; process noise, counts or a missing
smooth inflow do not give a negative one). The level noise variance a + b x level^2 comes from the same
signature: a level error of variance s2(t) makes the lag-1 covariance of the changes -s2(t), so
-e[k] e[k+1] is regressed on (1, level^2) (non-negative, trimmed).
"""

from __future__ import annotations

import numpy as np
from scipy.optimize import nnls

TRIM = 25.0           # a product counts at most this many times its fitted variance (outliers)


def _ends(st, i: int) -> np.ndarray:
    """The stock's level at the end of each step (the level its level row compares)."""
    return np.append(st.L[i, 1:], st.L[i, -1] + st.dy[i, -1])


def level_rows(s) -> dict[int, np.ndarray]:
    """{stock index: level noise sd per step} for the final stocks whose changes show measurement error."""
    st = s.st
    out = {}
    if st.T < 20:
        return out
    e = st.dy - s.change()
    for x in sorted(st.final):
        i = st.ids.index(x)
        ei = e[i] - e[i].mean()
        v = float(ei @ ei)
        if v <= 0:
            continue
        r1 = float(ei[1:] @ ei[:-1]) / v
        if r1 >= -3.0 / np.sqrt(st.T):
            continue
        prod = -ei[1:] * ei[:-1]                     # E = s2 at the shared level (the end of step k)
        lev2 = _ends(st, i)[:-1] ** 2
        X = np.column_stack([np.ones(len(prod)), lev2])
        w = np.ones(len(prod))
        ab = np.array([max(float(np.mean(prod)), 1e-12), 0.0])
        for _ in range(4):
            fit = np.maximum(X @ ab, 1e-12)
            z = np.clip(prod, -TRIM * fit, TRIM * fit)
            w = 1.0 / fit ** 2
            A = X * np.sqrt(w)[:, None]
            ab = nnls(A, z * np.sqrt(w))[0]
            if ab.sum() <= 0:
                break
        if ab.sum() <= 0:
            continue
        L2 = _ends(st, i) ** 2
        out[i] = np.sqrt(np.maximum(ab[0] + ab[1] * L2, 1e-12))
    return out


def adds(s) -> list:
    """Local-search moves: a proportional move X -> R into each counter R with a level row, from every
    stock X that is not a counter (where the model has none yet), at a small start."""
    st = s.st
    out = []
    for i in st.level_rows:
        r = st.ids[i]
        for x in st.ids:
            if x == r or x in st.final or any(q[0] == "term" and q[1:4] == (x, r, x) for q in s.parts):
                continue
            c = s.without(len(s.parts))
            c.parts.append(("term", x, r, x))
            c.theta, c.lo, c.hi = np.append(c.theta, 1e-4), np.append(c.lo, 0.0), np.append(c.hi, 1.0)
            out.append(c)
    return out
