"""Partial-model simulation: how badly each stock's own equations do when every other stock follows
the data.

A stock is run forward from many moments in the data with the model's flows, while every other
stock is reset to its measured level after each step; its distance from what was measured `horizon`
steps later, relative to how far the data moved, says how much of the model's error is that stock's
row (0 = perfect, 1 = no better than assuming nothing changes).
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
