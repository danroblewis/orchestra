"""Least squares with signs, and the price of a fit (engine_forms).

A stock's one-step change y is fitted by columns X with bounds per column (a drain's number is at
most 0 in the change, a table's heights at least 0); the fit is priced by BIC on its residual,
with the residual's sum of squares floored so a noise-free fit is not worth infinitely much.
"""

from __future__ import annotations

import math

import numpy as np
from scipy.optimize import lsq_linear


def bounded(X: np.ndarray, y: np.ndarray, lo: np.ndarray, hi: np.ndarray) -> np.ndarray:
    """argmin |X b - y| with lo <= b <= hi (columns scaled for the solver)."""
    if X.shape[1] == 0:
        return np.zeros(0)
    scale = np.sqrt((X ** 2).mean(axis=0))
    scale[scale < 1e-12] = 1.0
    if np.all(np.isinf(lo)) and np.all(np.isinf(hi)):
        b, *_ = np.linalg.lstsq(X / scale, y, rcond=None)
        return b / scale
    r = lsq_linear(X / scale, y, bounds=(lo * scale, hi * scale), method="bvls", lsmr_tol="auto")
    return r.x / scale


def sse(r: np.ndarray, floor: float) -> float:
    return max(float(r @ r), floor)


def bic(r: np.ndarray, p: int, floor: float) -> float:
    n = len(r)
    return n * math.log(sse(r, floor) / n) + p * math.log(n)


def floor_of(y: np.ndarray) -> float:
    """The smallest sum of squares a fit is credited with: a relative 1e-6 of the change's size
    (levels are reported to about 6 significant digits)."""
    n = len(y)
    s = float(np.sqrt(np.mean(y ** 2))) + 1e-12
    return n * (1e-6 * s) ** 2
