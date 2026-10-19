"""Changes in a series' mean (PELT), with the noise variance floored at the data's precision.

Copied from sdlab/discovery/changes.py at commit aad5c7b (its numba core `_last_cut` is used from
there, unchanged); changed here only: `var_floor` (opts "exact", common_cause's exact-data fix from
common_cause/exact.py at 19de233): on exact data the residual's successive differences are ~1e-28,
so a change would cost nothing and the ridge's tiny systematic bias would be cut into pieces.
"""

from __future__ import annotations

import math

import numpy as np

from ...changes import _last_cut


def pelt(r: np.ndarray, min_len: int, mult: float, var_floor: float = 0.0) -> list[int]:
    """Cuts 0 = c0 < c1 < ... < ck = n of r into pieces of constant mean. Each change costs
    mult x log n x the noise variance (estimated from successive differences, so that the changes
    themselves do not inflate it), never below var_floor."""
    r = np.nan_to_num(np.asarray(r, dtype=float))
    n = r.shape[0]
    dv = float(np.sum(np.diff(r) ** 2))
    var = (dv / (2 * max(1, n - 1))) or 1.0
    if var_floor:
        var = max(var, var_floor)
    pen = mult * math.log(n) * var
    last = _last_cut(r, int(min_len), pen)
    cuts = []
    t = n
    while t > 0:
        cuts.append(t)
        t = int(last[t])
    cuts.append(0)
    return cuts[::-1]
