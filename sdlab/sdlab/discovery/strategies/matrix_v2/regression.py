"""One stock's regression: its change in a step on the levels at the start of the step.

Copied from sdlab/discovery/regression.py at commit aad5c7b (last changed there in cb97c26); changed
here only: bic and stepwise take a floor under the rss (opts "rss_floor": below the data's rounding a
row's rss says nothing) and stepwise a gain per column (a product of two levels pays more to join);
and (opts "exact", common_cause's exact-data fix, from common_cause/exact.py at commit 19de233, made a
proper copy instead of patching the shared functions) row_sums carries a floor at float precision
that fit_subset never goes below, and stepwise, when its fit is exact, walks along exact ties to the
plainest exact set.

The outside inflow in pieces is removed by taking out each piece's mean (so only the levels' columns
remain), and every candidate set of levels is then fitted from precomputed sums.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np


@dataclass
class Sums:
    G: np.ndarray
    b: np.ndarray
    yy: float
    T: int
    pieces: int
    floor: float = 0.0          # (exact) no fit's rss is below this: the data's float precision


@dataclass
class Fit:
    beta: np.ndarray
    rss: float
    se: np.ndarray


def demean(a: np.ndarray, cuts: list[int]) -> np.ndarray:
    """a (columns x steps, or steps) with each piece's mean taken out."""
    starts = np.asarray(cuts[:-1])
    lens = np.diff(cuts)
    seg = np.repeat(np.arange(len(lens)), lens)
    means = np.add.reduceat(a, starts, axis=-1) / lens
    return a - means[..., seg]


def row_sums(y: np.ndarray, X: np.ndarray, cuts: list[int] | None, exact: float = 0.0) -> Sums:
    """exact: the floor on a fit's mean square residual (REL x the mean square of the changes), 0 for none."""
    yc, Xc = (demean(y, cuts), demean(X, cuts)) if cuts else (y, X)
    return Sums(G=Xc @ Xc.T, b=Xc @ yc, yy=float(yc @ yc), T=y.shape[0], pieces=len(cuts) - 1 if cuts else 0, floor=exact * y.shape[0])


def fit_subset(sums: Sums, cols: list[int]) -> Fit:
    if not cols:
        return Fit(beta=np.zeros(0), rss=max(sums.yy, sums.floor), se=np.zeros(0))
    idx = np.asarray(cols)
    G = sums.G[np.ix_(idx, idx)].copy()
    G[np.diag_indices_from(G)] += 1e-9 * (np.abs(np.diag(G)) + 1)
    b = sums.b[idx]
    try:
        inv = np.linalg.inv(G)
    except np.linalg.LinAlgError:
        inv = np.linalg.pinv(G)
    x = inv @ b
    rss = max(sums.yy - float(x @ b), 1e-12, sums.floor)
    s2 = rss / max(1, sums.T - len(cols) - sums.pieces)
    return Fit(beta=x, rss=rss, se=np.sqrt(np.maximum(0, np.diag(inv)) * s2))


def bic(T: int, rss: float, p: int, floor: float = 0.0) -> float:
    return T * math.log(max(rss, floor, 1e-12) / T) + p * math.log(T)


REL_TIE = 1.0 + 1e-9          # a fit within this factor of the precision floor is exact


def plainest(sums: Sums, chosen: list[int], allowed: list[int], key) -> list[int]:
    """(exact) An exact fit moved, by drops and exchanges that keep it exact, to the plainest exact
    set (the smallest key): with an exact collinearity among the levels several sets fit exactly and
    only the plainest is the truth, which the greedy path does not reach (common_cause, 032)."""
    exact = lambda c: fit_subset(sums, c).rss <= REL_TIE * sums.floor  # noqa: E731
    if not sums.floor or not chosen or not exact(chosen):
        return chosen

    def drops(t):
        changed = True
        while changed:
            changed = False
            for j in list(t):
                tt = [q for q in t if q != j]
                if exact(tt):
                    t, changed = tt, True
                    break
        return t

    best = drops(list(chosen))
    improved = True
    while improved:
        improved = False
        trials = [[q for q in best if q != j] + [i] for j in best for i in allowed if i not in best]
        for t in trials:
            if not exact(t):
                continue
            t = drops(t)
            if key(t) < key(best):
                best, improved = t, True
                break
    return best


def stepwise(sums: Sums, start: list[int], allowed: list[int], add_gain: float, max_steps: int, floor: float = 0.0,
             gain: dict | None = None, key=None) -> list[int]:
    """Add the level that improves BIC most (by more than add_gain, or gain[j] for column j), or drop
    one whose removal improves it by more than 2, until nothing does."""
    gain = gain or {}
    chosen = list(start)
    score = bic(sums.T, fit_subset(sums, chosen).rss, len(chosen) + sums.pieces, floor)
    for _ in range(max_steps):
        best = None
        for j in allowed:
            if j in chosen:
                continue
            sc = bic(sums.T, fit_subset(sums, chosen + [j]).rss, len(chosen) + 1 + sums.pieces, floor)
            if sc < score - gain.get(j, add_gain) and (best is None or sc < best[1]):
                best = (chosen + [j], sc)
        for j in chosen:
            ns = [x for x in chosen if x != j]
            sc = bic(sums.T, fit_subset(sums, ns).rss, len(ns) + sums.pieces, floor)
            if sc < score - 2 and (best is None or sc < best[1]):
                best = (ns, sc)
        if best is None:
            break
        chosen, score = best
    if sums.floor:
        chosen = plainest(sums, chosen, allowed, key or len)
    return chosen


def piece_values(y: np.ndarray, X: np.ndarray, cols: list[int], beta: np.ndarray, cuts: list[int]) -> list[dict]:
    """Each piece's level of the outside inflow, with the levels' part taken out."""
    res = y - (beta @ X[cols] if cols else 0)
    return [{"a": a, "b": b, "w": b - a, "v": float(res[a:b].mean())} for a, b in zip(cuts[:-1], cuts[1:])]
