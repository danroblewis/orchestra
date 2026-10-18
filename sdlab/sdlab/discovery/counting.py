"""Counting noise: a flow that moves whole things varies around its rate as much as its rate.

When things move one by one (orders placed, loaves baked, patients admitted), what a flow moves in a
step is a count around its rate, whose variance equals its mean (Poisson). A stock's change in a step
is the sum of what flows in minus what flows out, so the variance of its unexplained part is the
*gross* throughput: everything in plus everything out. A row's own terms say how much that is
(|inflow| + each level's |number| x the level); the residuals say how much it really is. A row whose
residuals vary far more than its terms can explain is missing a matched pair of flows (an outside
inflow and a drain that cancel on average: the drain has absorbed the inflow); one whose terms claim
far more throughput than the residuals show has a spurious pair (an inflow and a drain both too big).

The ratio is only a guide: a flow that converts units (a ratio, a co-flow's `per`) scales its
variance by the square, and a flow capped by what a stock holds varies less. So it flags only
clear disagreements (by default more than 4x either way).
"""

from __future__ import annotations

import numpy as np


def gross(coef_cols: np.ndarray, X: np.ndarray, inflow: np.ndarray) -> np.ndarray:
    """The throughput a row's terms imply at each step: |outside inflow| + sum |number| x level.
    coef_cols: numbers (columns); X: columns x steps; inflow: per step."""
    g = np.abs(inflow) + (np.abs(coef_cols) @ np.abs(X) if len(coef_cols) else 0.0)
    return np.maximum(0.5, g)


def robust_var(r: np.ndarray) -> float:
    """Variance from the median absolute deviation (steps where the row does not hold - a stock
    run dry, a burst - do not count)."""
    r = np.asarray(r, dtype=float)
    if not r.size:
        return 0.0
    return float((1.4826 * np.median(np.abs(r - np.median(r)))) ** 2)


def ratio(res: np.ndarray, g: np.ndarray) -> float:
    """Robust variance of the residuals in units of the throughput the row's terms imply: ~1 when the
    row accounts for every flow through the stock, >> 1 when flows are missing, << 1 when spurious."""
    return robust_var(res / np.sqrt(g))


def verdict(z: float, missing: float = 4.0, spurious: float = 0.25) -> str:
    return "missing" if z > missing else "spurious" if z < spurious else ""
