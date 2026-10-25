"""Partial-model simulation: how badly a stock's own equations do when every other stock follows the
data (Homer 2012; Oliva 2003).

partial_errors (row_crossover): each stock run forward from many moments with the model's flows, every
other stock reset to its measured level after each step; its distance from what was measured `horizon`
steps later, relative to how far the data moved (0 = perfect, 1 = no better than assuming nothing
changes).

partial_error (inflow_attribution): one row simulated alone, its stock stepped forward by the row (its
numbers and its own outside inflow), every other level it reads fed in as measured; robust (medians
over starts), so a few stretches where no linear row can follow (a stock run dry) do not decide it:
0 = tracks its stock, 1 = no better than holding the level.
"""

from __future__ import annotations

import numpy as np

from .simulate import Model, levels_array, starts_for


def partial_errors(flows: list[dict], ids: list[str], t: list, levels: dict, horizon: int = 20, starts: int = 80) -> dict[str, float]:
    A = levels_array(levels, ids)
    n = A.shape[1]
    s0 = starts_for(n, horizon, starts)
    if not len(s0) or not flows:
        return {i: float("inf") for i in ids}
    model = Model(flows, ids)
    tt = np.asarray(t, dtype=float)
    sd = A.std(axis=1)
    sd[sd == 0] = 1
    obs = A[:, s0 + horizon - 1]
    moved = (((obs - A[:, s0 - 1]) / sd[:, None]) ** 2).sum(axis=1)
    out = {}
    for k, i in enumerate(ids):
        L = A[:, s0 - 1].copy()
        for h in range(horizon):
            L = model.step(L, tt[s0 + h])
            own = L[k].copy()
            L = A[:, s0 + h].copy()
            L[k] = own
        e = ((L[k] - obs[k]) / sd[k]) ** 2
        e[~np.isfinite(e)] = 1e6
        out[i] = float(e.sum() / max(1e-9, moved[k]))
    return out


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
