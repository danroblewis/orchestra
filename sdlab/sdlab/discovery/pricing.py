"""What a change in a stock's outside inflow costs, priced honestly.

PELT (changes.py) prices a change as mult x log n x the noise variance. Two things decide whether
that price is honest:

- **mult.** A change has a value and a place, so BIC charges it 2 x log n. At 1 x log n the scan
  finds chance changes in plain noise.
- **the variance.** The scan's cost is a sum of squares, and the gain from a chance change in it is
  about (the variance of a piece's mean) x n, which for residuals that are correlated in time (a
  level the row does not use, a hidden stock feeding it) is the *long-run* variance
  sigma^2 (1 + rho) / (1 - rho), not sigma^2. Successive differences estimate sigma^2 (1 - rho):
  the more a missing level leaves in the residual, the cheaper changes get.

`noise_variance` gives each estimate; `scan` runs PELT at a price in those units; `prune` then
merges adjacent pieces until every remaining change pays its price on its own (PELT's optimum may
keep a change that only pays together with its neighbours).
"""

from __future__ import annotations

import math

import numpy as np

from .changes import _last_cut


def _cuts_from(last: np.ndarray, n: int) -> list[int]:
    cuts, t = [], n
    while t > 0:
        cuts.append(t)
        t = int(last[t])
    cuts.append(0)
    return cuts[::-1]


def _fit_cuts(r: np.ndarray, min_len: int, pen: float) -> list[int]:
    return _cuts_from(_last_cut(r, int(min_len), float(pen)), r.shape[0])


def noise_variance(r: np.ndarray, how: str = "diff") -> float:
    """The noise variance of r in the units the change price uses.

    diff: half the mean squared successive difference: sigma^2 (1 - rho) for AR(1) noise.
    long: the long-run variance sigma^2 (1 + rho) / (1 - rho), the variance of a long piece's mean
          times its length. rho is read off the differences too (their lag-1 autocorrelation is
          -(1 - rho) / 2), so that changes in the mean, which touch single differences, do not
          inflate it; clipped to [0, 0.9]."""
    r = np.nan_to_num(np.asarray(r, dtype=float))
    n = r.shape[0]
    d = np.diff(r)
    dv = float(d @ d) / (2 * max(1, n - 1)) or 1.0
    if how == "diff":
        return dv
    dc = d - d.mean()
    rd = float(dc[1:] @ dc[:-1]) / max(1e-12, float(dc @ dc))
    rho = min(0.9, max(0.0, 1 + 2 * rd))
    return dv * (1 + rho) / (1 - rho) ** 2


def prune(r: np.ndarray, cuts: list[int], pen: float) -> list[int]:
    """Merge the two neighbouring pieces whose merging costs least, while that cost is below pen:
    every change left pays for itself."""
    cuts = list(cuts)
    pre = np.concatenate([[0.0], np.cumsum(r)])

    def cost(i):  # the rise in the sum of squares from removing cut i (1 <= i < len - 1)
        a, m, b = cuts[i - 1], cuts[i], cuts[i + 1]
        s1, s2 = pre[m] - pre[a], pre[b] - pre[m]
        n1, n2 = m - a, b - m
        return (s1 / n1 - s2 / n2) ** 2 * n1 * n2 / (n1 + n2)

    while len(cuts) > 2:
        costs = [cost(i) for i in range(1, len(cuts) - 1)]
        i = int(np.argmin(costs))
        if costs[i] >= pen:
            break
        del cuts[i + 1]
    return cuts


def scan(r: np.ndarray, min_len: int, mult: float, how: str = "diff", each: bool = False) -> list[int]:
    """Cuts of r into pieces of constant mean, each change priced mult x log n x the noise variance
    (estimated as `how` says); with each=True every change must also pay that price on its own."""
    r = np.nan_to_num(np.asarray(r, dtype=float))
    n = r.shape[0]
    pen = mult * math.log(n) * noise_variance(r, how)
    cuts = _fit_cuts(r, min_len, pen)
    return prune(r, cuts, pen) if each else cuts
