"""Ratios of levels in a row: a term k x A / M, read as a flow k x A with an effect of M (a table
of 1 / M over the levels M takes).

SD rates are linear in levels times effects of single levels, so a quantity per unit of another
(memory per request per pod: requests / pods; CPU requested over the nodes: pods / nodes) is a
level with a 1 / x effect of the other. After a row is chosen, ratio columns A / M are offered to
it, for A among the levels and inputs it uses and M among the levels it uses that stay positive;
they join (and the row's own columns may leave) by stepwise BIC like any column, a ratio only by
more than 2 log T. The search runs on the row's few columns only (their cross products once).
"""

from __future__ import annotations

import math

import numpy as np

from ...regression import demean
from .gram import Sums, solve, stepwise


def table(m: np.ndarray, n: int = 24) -> list[list[float]]:
    """Points of 1 / x over the range a level takes (ends held beyond them)."""
    lo, hi = float(np.min(m)), float(np.max(m))
    xs = np.unique(np.round(np.geomspace(max(lo, 1e-6), max(hi, lo * 1.001 + 1e-6), n), 6))
    return [[float(x), round(1.0 / x, 8)] for x in xs]


def ratio_row(X: np.ndarray, y: np.ndarray, own: int, cols: list[int], level_cols: set, cuts, add_gain: float) -> dict | None:
    """The row with ratio columns offered, all over one level M (tried in turn): {"cols": [j or
    (a, m)], "beta": raw numbers, "rss"} or None when no ratio joins. A ratio only adds (an inflow
    k > 0), never reads the row's own level, and joins by more than `add_gain`. `cuts`: the row's
    outside inflow's pieces ([0, T] a constant, None none)."""
    T = len(y)
    ms = [m for m in cols if m in level_cols and m != own and X[m].min() > 0.5]
    base = list(cols)
    K = len(base)
    yc = demean(y, cuts) if cuts else y
    best = None
    for m in ms:
        cand = [(a, m) for a in cols if a not in (m, own)]
        if not cand:
            continue
        Z = np.vstack([X[base]] + [X[a] / X[m] for a, _ in cand])
        if cuts:
            Z = demean(Z, cuts)
        sc = Z.std(axis=1)
        sc[sc < 1e-12] = 1.0
        Zs = Z / sc[:, None]
        sm = Sums(Zs @ Zs.T, Zs @ yc, float(yc @ yc), T, len(cuts) - 1 if cuts else 0)
        allowed = np.ones(len(Z), bool)
        _, rss0, _ = solve(sm, list(range(K)))
        chosen = list(range(K))
        for _ in range(4):
            chosen = stepwise(sm, chosen, allowed, add_gain, 3 * len(Z))
            beta, rss, _ = solve(sm, chosen)
            neg = [q for q, b in zip(chosen, beta) if q >= K and b < 0]
            if not neg:
                break
            allowed[neg] = False
            chosen = [q for q in chosen if q not in neg]
        beta, rss, _ = solve(sm, chosen)
        if not any(q >= K for q in chosen) or any(q >= K and b < 0 for q, b in zip(chosen, beta)):
            continue
        p = len(chosen)
        score = T * math.log(max(rss, 1e-12) / T) + p * math.log(T)
        if best is None or score < best[0]:
            best = (score, {"cols": [base[q] if q < K else cand[q - K] for q in chosen], "beta": beta / sc[chosen], "rss": rss, "rss0": rss0})
    return best[1] if best else None
