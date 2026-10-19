"""Which specialists cannot matter on these data, so combined2 skips them (time).

- common_cause is for stocks that move alike: independent but identical systems, a common cause
  read as a cross-link, levels that are exact linear combinations of each other (a shared mode
  without noise, 032). Without two stocks whose changes move together (|correlation| at least
  ALIKE) and without a near-exact linear tie among the levels, it is skipped.
- odefit is for smooth measured data (physics, measured continuous levels): on counts it is
  skipped.
"""

from __future__ import annotations

import numpy as np

from sdlab.discovery.simulate import levels_array

ALIKE = 0.9           # |correlation| of two stocks' changes that counts as moving alike
TIE = 1e-6            # smallest / largest singular value of the standardised levels (and 1) that counts as a tie


def counts(L: np.ndarray) -> bool:
    x = L[np.isfinite(L)]
    return bool(x.size) and np.abs(x - np.round(x)).max() < 1e-9 and np.abs(np.diff(L, axis=1)).max() > 0


def alike(L: np.ndarray) -> bool:
    S = L.shape[0]
    if S < 2 or L.shape[1] < 4:
        return False
    d = np.diff(L, axis=1)
    sd = d.std(axis=1)
    live = sd > 0
    if live.sum() >= 2:
        z = (d[live] - d[live].mean(axis=1, keepdims=True)) / sd[live, None]
        c = (z @ z.T) / z.shape[1]
        np.fill_diagonal(c, 0.0)
        if np.abs(c).max() >= ALIKE:
            return True
    lv = L.std(axis=1)
    keep = lv > 0
    if keep.sum() >= 2:
        Z = (L[keep] - L[keep].mean(axis=1, keepdims=True)) / lv[keep, None]
        s = np.linalg.svd(np.vstack([Z, np.ones(Z.shape[1])]), compute_uv=False)
        if s[-1] <= TIE * s[0]:
            return True
    return False


def skip(stocks: list[dict], run: dict, opts: dict) -> dict[str, str]:
    """{specialist: why} for the specialists these data rule out."""
    ids = [s["id"] for s in stocks]
    L = levels_array(run["levels"], ids)
    out = {}
    if not alike(L):
        out["common_cause"] = "no two stocks move alike"
    if counts(L):
        out["odefit"] = "counts (odefit is for smooth measured levels)"
    return out


EXACT = 1.0           # log10 of the residuals' rms over the data's rounding below which a model is exact


def pieced(f: dict, eras: bool) -> bool:
    """A found inflow in more than one value, or found era segments (byTime without announced eras)."""
    if len({round(float(g.get("value") or 0), 9) for g in f.get("inflow") or []}) > 1:
        return True
    return not eras and len(f.get("byTime") or []) > 1


def plain_exact(flows: list[dict], data, eras: bool) -> bool:
    """A model with no found inflow pieces (and no found eras) that is exact to the levels' rounding
    on data without counting noise: nothing is left for odefit or the structures search to explain
    (each of their wins on the ladder is on counts, on a base with pieces, or on a base that misses
    by over 100x the rounding)."""
    from ._vendored.combined import judge as J

    if not flows or data.counts:
        return False
    if any(pieced(f, eras) for f in flows):
        return False
    try:
        return J.misfit(flows, data) < EXACT
    except Exception:                                     # noqa: BLE001
        return False
