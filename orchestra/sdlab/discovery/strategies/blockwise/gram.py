"""One-step regressions for many rows at once, from sums computed once.

Every row's regression (a stock's change in a step on the levels and inputs at its start) uses the
same columns X, so the cross products X X', X dy' and each change's own sum of squares are computed
once for the whole model (columns scaled to unit spread, so that levels of 10 and of 80,000 sit in
one well-conditioned matrix). An outside inflow in pieces (a constant per piece) is taken out of a
row by subtracting each piece's means, which for the sums is a correction from the pieces' sums
(cumulative sums of X and dy, computed once): no row ever touches the T-long series again.

Stepwise selection then works on the small matrices only, with every candidate column's gain from
one matrix product (the Schur complement), so a row costs about columns x chosen^2, not columns x T.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np


@dataclass
class Sums:
    G: np.ndarray            # N x N, scaled columns
    b: np.ndarray            # N, scaled columns x y
    yy: float
    T: int
    pieces: int


class Design:
    """The columns (levels at the start of each step, then the measured inputs) and the changes."""

    def __init__(self, X: np.ndarray, dy: np.ndarray):
        self.N, self.T = X.shape
        self.S = dy.shape[0]
        sd = X.std(axis=1)
        mx = np.abs(X).max(axis=1)
        self.scale = np.where(sd > 1e-12, sd, np.where(mx > 0, mx, 1.0))
        Xs = X / self.scale[:, None]
        self.G = Xs @ Xs.T
        self.B = Xs @ dy.T                                        # N x S
        self.yy = (dy * dy).sum(axis=1)
        self.cx = np.concatenate([np.zeros((self.N, 1)), np.cumsum(Xs, axis=1)], axis=1)   # N x (T + 1)
        self.cy = np.concatenate([np.zeros((self.S, 1)), np.cumsum(dy, axis=1)], axis=1)
        self.dy = dy

    def sums(self, s: int, cuts: list[int] | None) -> Sums:
        """Row s's sums with each piece's mean taken out (cuts None: no outside inflow at all)."""
        if not cuts:
            return Sums(self.G, self.B[:, s], float(self.yy[s]), self.T, 0)
        c = np.asarray(cuts)
        lens = np.diff(c).astype(float)
        px = self.cx[:, c[1:]] - self.cx[:, c[:-1]]               # N x pieces
        py = self.cy[s, c[1:]] - self.cy[s, c[:-1]]
        w = px / lens
        return Sums(self.G - w @ px.T, self.B[:, s] - w @ py, float(self.yy[s] - (py * py / lens).sum()), self.T, len(lens))


def bic(T: int, rss: float, p: int) -> float:
    return T * math.log(max(rss, 1e-12) / T) + p * math.log(T)


def solve(sm: Sums, cols: list[int]) -> tuple[np.ndarray, float, np.ndarray]:
    """(beta in scaled units, rss, inverse of the chosen block)."""
    if not cols:
        return np.zeros(0), max(sm.yy, 1e-12), np.zeros((0, 0))
    idx = np.asarray(cols)
    G = sm.G[np.ix_(idx, idx)].copy()
    G[np.diag_indices_from(G)] += 1e-9 * (np.abs(np.diag(G)) + 1)
    try:
        inv = np.linalg.inv(G)
    except np.linalg.LinAlgError:
        inv = np.linalg.pinv(G)
    beta = inv @ sm.b[idx]
    return beta, max(sm.yy - float(beta @ sm.b[idx]), 1e-12), inv


def best_add(sm: Sums, chosen: list[int], allowed: np.ndarray) -> tuple[int, float] | None:
    """The column whose addition lowers the rss most, and the rss with it."""
    beta, rss, inv = solve(sm, chosen)
    cand = np.flatnonzero(allowed)
    if chosen:
        cand = cand[~np.isin(cand, chosen)]
    if not len(cand):
        return None
    if chosen:
        idx = np.asarray(chosen)
        V = sm.G[np.ix_(idx, cand)]                                # k x m
        Q = inv @ V
        den = sm.G[cand, cand] - (V * Q).sum(axis=0)
        num = sm.b[cand] - V.T @ beta
    else:
        den, num = sm.G[cand, cand].copy(), sm.b[cand].copy()
    ok = den > 1e-9 * (np.abs(sm.G[cand, cand]) + 1e-12)
    gain = np.where(ok, num * num / np.where(ok, den, 1.0), 0.0)
    q = int(np.argmax(gain))
    return int(cand[q]), max(rss - float(gain[q]), 1e-12)


def stepwise(sm: Sums, start: list[int], allowed: np.ndarray, add_gain: float, max_steps: int, most: int | None = None,
             partner: int | None = None) -> list[int]:
    """Add the column that improves BIC most (by more than add_gain), or drop one whose removal
    improves it by more than 2, until nothing does (at most `most` columns). With a `partner` (the
    row's own level): while it is out, the partner and the best column beside it are also tried as
    a pair (by more than 2 x add_gain), since a stock's change can follow the gap between two nearly
    equal columns (an input and the level it feeds) while neither alone explains it."""
    chosen = [j for j in start if allowed[j]]
    T, lt = sm.T, math.log(sm.T)
    for _ in range(max_steps):
        beta, rss, inv = solve(sm, chosen)
        p = len(chosen) + sm.pieces
        score = bic(T, rss, p)
        best = None
        if most is None or len(chosen) < most:
            a = best_add(sm, chosen, allowed)
            if a is not None:
                new = bic(T, a[1], p + 1)
                if new < score - add_gain:
                    best = (chosen + [a[0]], new)
            if partner is not None and allowed[partner] and partner not in chosen and (most is None or len(chosen) + 2 <= most):
                a2 = best_add(sm, chosen + [partner], allowed)
                if a2 is not None:
                    new = bic(T, a2[1], p + 2)
                    if new < score - 2 * add_gain and (best is None or new < best[1]):
                        best = (chosen + [partner, a2[0]], new)
        if chosen:
            dg = np.diag(inv)
            inc = beta * beta / np.maximum(dg, 1e-300)
            new = T * np.log(np.maximum(rss + inc, 1e-12) / T) + (p - 1) * lt
            q = int(np.argmin(new))
            if new[q] < score - 2 and (best is None or new[q] < best[1]):
                best = ([c for i, c in enumerate(chosen) if i != q], float(new[q]))
        if best is None:
            break
        chosen = best[0]
    return chosen
