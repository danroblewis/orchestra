"""Partial-model simulation of one row (Homer 2012; Oliva 2003).

A row is simulated alone: its stock's level is stepped forward by the row (its numbers and its own
outside inflow), while every other level the row reads is fed in as measured. A row whose one-step fit
is fine but whose stock drifts off when it has to carry itself (a missing inflow, a drain that is
nearly zero) fails here at once, where the whole-model judge sees it only in aggregate.

The error is robust (medians over starts), so a few stretches where no linear row can follow (a
stock run dry) do not decide it: 0 = tracks its stock, 1 = no better than holding the level.
"""

from __future__ import annotations

import numpy as np

from .simulate import starts_for


def partial_error(s: int, cols: list[tuple[int, np.ndarray | None]], beta: np.ndarray, inflow: np.ndarray,
                  levels: np.ndarray, horizon: int = 20, starts: int = 80) -> float:
    """s: the stock's index in levels (stocks x times); cols: the row's columns as (stock index,
    mask over steps or None: the column is that level while the mask holds); beta: their numbers;
    inflow: the row's outside inflow per step (step k goes from time k to k + 1)."""
    n = levels.shape[1]
    T = n - 1
    s0 = starts_for(n, horizon, starts) - 1
    s0 = s0[s0 + horizon <= T]
    if not len(s0):
        return float("inf")
    x = levels[s, s0].astype(float)
    for h in range(horizon):
        k = s0 + h
        d = inflow[k].astype(float).copy()
        for (j, mask), b in zip(cols, beta):
            v = x if j == s else levels[j, k]
            d += b * (v if mask is None else v * mask[k])
        x = np.maximum(0.0, x + d)
    obs = levels[s, s0 + horizon]
    e = np.median((x - obs) ** 2)
    base = np.median((levels[s, s0] - obs) ** 2)
    return float(e / max(base, 1e-9))
