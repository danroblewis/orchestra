"""A starting model from each stock's own regression.

The joint stepwise search (fit.py) is myopic where a structure needs two terms at once: a move
S -> E at S x I fits S's change only when E's onset is there to take what it adds to E. Each stock's
change alone has no such coupling, so each is first regressed by itself (signs free, forward and
backward selection by BIC) on the features its rate may read: 1, every stock, every input, every
product of two stocks, and, for a hidden chain of order n and delay tau, those filtered through the
chain plus the chain's start-of-run contents. The rows' numbers are then read as terms: a feature's
loss in the row of a stock it reads paired with gains in other stocks' rows is a move (at the
smaller of the two numbers), the rest of a loss an outflow, the rest of a gain a link; a loss in the
row of a stock the feature does not read is a gap when that stock has an outside inflow, else a
drain.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from .terms import Rows, Term, erlang, init_response


@dataclass(frozen=True)
class Feature:
    x: tuple = ()
    chain: tuple | None = None        # filtered through an (n, tau) chain
    stage: int | None = None          # the chain's start contents in this stage (x unused)


def features(rows: Rows, S: int, m: int, products: bool, chain: tuple | None, final=()) -> tuple[list[Feature], np.ndarray]:
    """final stocks are not read: a stock nothing leaves accumulates another's outflow, so its level
    is close to that stock's running sum, and reading it makes exact aliases of the stock's own
    dynamics (a chain fed by the running sum stands in for one fed by the stock)."""
    feats = [Feature(())] + [Feature((j,)) for j in range(S + m) if j not in final]
    if products:
        feats += [Feature((i, j)) for i in range(S) for j in range(i, S) if i not in final and j not in final]
    if chain:
        feats += [Feature(f.x, chain) for f in feats if len(f.x) < 2]
        feats += [Feature((), chain, s) for s in range(chain[0])]
    M = np.array([_col(rows, f) for f in feats])
    return feats, M


def _col(rows: Rows, f: Feature) -> np.ndarray:
    if f.stage is not None:
        return init_response(rows.T, f.chain[0], f.chain[1], f.stage)
    z = rows.z(f.x)
    return erlang(z, *f.chain) if f.chain else z


def _crit(r: np.ndarray, w: np.ndarray, counts: bool, eps: float, k: int, log_t: float) -> float:
    T = len(r)
    if counts:
        v = 0.5 * float((w * r * r).sum())
    else:
        v = 0.5 * T * math.log(max(float((r * r).mean()), eps))
    return v + 0.5 * log_t * k


def _ols(M: np.ndarray, y: np.ndarray, w: np.ndarray, idx: list[int]) -> tuple[np.ndarray, np.ndarray]:
    if not idx:
        return np.zeros(0), y.copy()
    sw = np.sqrt(w)
    A = (M[idx] * sw).T
    sc = np.linalg.norm(A, axis=0)
    sc = np.where(sc > 0, sc, 1.0)
    b = np.linalg.lstsq(A / sc, y * sw, rcond=None)[0] / sc
    return b, y - b @ M[idx]


def select_row(M: np.ndarray, y: np.ndarray, w: np.ndarray, counts: bool, eps: float, allowed: list[int], groups: dict | None = None) -> dict[int, float]:
    """One stock's regression: forward selection by BIC with a backward pass after each step.
    groups: {feature: [features added with it]} (a chain's start contents with its first feed)."""
    log_t = math.log(max(2, len(y)))
    groups = groups or {}
    idx: list[int] = []
    b, r = _ols(M, y, w, idx)
    cur = _crit(r, w, counts, eps, 0, log_t)
    for _ in range(25):
        best = None
        for j in allowed:
            if j in idx:
                continue
            trial = idx + [j] + [g for g in groups.get(j, []) if g not in idx]
            bb, rr = _ols(M, y, w, trial)
            c = _crit(rr, w, counts, eps, len(trial), log_t)
            if best is None or c < best[0]:
                best = (c, trial, bb)
        if best is None or best[0] >= cur - 1e-9:
            break
        cur, idx, b = best
        while len(idx) > 1:                        # backward
            drop = None
            for j in idx:
                trial = [i for i in idx if i != j]
                bb, rr = _ols(M, y, w, trial)
                c = _crit(rr, w, counts, eps, len(trial), log_t)
                if c < cur - 1e-9 and (drop is None or c < drop[0]):
                    drop = (c, trial, bb)
            if drop is None:
                break
            cur, idx, b = drop
    # features that help only together (a gap: target - R - E, each alone no better than nothing):
    # also backward from all of them, dropping the least significant while BIC falls
    full = [j for j in allowed]
    for j in allowed:
        full += [g for g in groups.get(j, []) if g not in full]
    if len(full) < len(y) / 3:
        bidx = list(full)
        bb, rr = _ols(M, y, w, bidx)
        bc = _crit(rr, w, counts, eps, len(bidx), log_t)
        while len(bidx) > 1:
            sw = np.sqrt(w)
            A = (M[bidx] * sw).T
            sig2 = max(float((rr * rr * w).mean()), 1e-300)
            try:
                cov = np.linalg.pinv(A.T @ A) * sig2
                tstat = np.abs(bb) / np.sqrt(np.maximum(np.diag(cov), 1e-300))
            except np.linalg.LinAlgError:
                break
            order = [bidx[i] for i in np.argsort(tstat)]
            moved = False
            for j in order[:3]:
                trial = [i for i in bidx if i != j and i not in groups.get(j, [])]
                b2, r2 = _ols(M, y, w, trial)
                c2 = _crit(r2, w, counts, eps, len(trial), log_t)
                if c2 < bc - 1e-9:
                    bidx, bb, rr, bc, moved = trial, b2, r2, c2, True
                    break
            if not moved:
                break
        if bc < cur - 1e-9:
            idx, b = bidx, bb
    return {j: float(v) for j, v in zip(idx, b)}


def regress(rows: Rows, dy: np.ndarray, var: np.ndarray, counts: bool, eps: float, S: int, m: int,
            products: bool = True, chain: tuple | None = None, final=()) -> tuple[list[Feature], list[dict[int, float]], float]:
    """(features, each row's numbers, the rows' summed BIC)."""
    feats, M = features(rows, S, m, products, chain, final)
    groups = {}
    if chain:
        st = [k for k, f in enumerate(feats) if f.stage is not None]
        groups = {k: st for k, f in enumerate(feats) if f.chain and f.stage is None}
    B, total = [], 0.0
    log_t = math.log(max(2, dy.shape[1]))
    allowed = [k for k, f in enumerate(feats) if f.stage is None]
    for s in range(S):
        w = 1.0 / var[s]
        row = select_row(M, dy[s], w, counts, eps, allowed, groups)
        idx = list(row)
        r = dy[s] - (np.array([row[i] for i in idx]) @ M[idx] if idx else 0.0)
        total += _crit(r, w, counts, eps, len(idx), log_t)
        B.append(row)
    return feats, B, total


def profile(rows: Rows, dy: np.ndarray, var: np.ndarray, counts: bool, eps: float, S: int, m: int, chain: tuple, final=()) -> float:
    """How well every feature at once (with the chain's) fits the rows: smooth in the chain's delay,
    with its minimum where a chain fits (the selected rows' BIC is sharp there, too sharp to find
    from a grid)."""
    feats, M = features(rows, S, m, True, chain, final)
    keep = [k for k, f in enumerate(feats) if f.chain or len(f.x) < 2 or S <= 4]
    T = dy.shape[1]
    total = 0.0
    for s in range(S):
        w = 1.0 / var[s]
        _, r = _ols(M, dy[s], w, keep)
        total += 0.5 * float((w * r * r).sum()) if counts else 0.5 * T * math.log(max(float((r * r).mean()), eps))
    return total


def start(rows: Rows, dy: np.ndarray, var: np.ndarray, counts: bool, eps: float, S: int, m: int, unit: list[str], final: set[int],
          products: bool = True, chain: tuple | None = None) -> list[Term]:
    feats, B, _ = regress(rows, dy, var, counts, eps, S, m, products, chain, final)
    return translate(B, feats, S, unit, final)


def translate(B: list[dict[int, float]], feats: list[Feature], S: int, unit: list[str], final: set[int]) -> list[Term]:
    """The rows' numbers read as terms (see the module's docstring)."""
    out: list[Term] = []
    pooled = {s for s in range(S) for k, v in B[s].items() if v > 0 and not feats[k].chain and (not feats[k].x or feats[k].x[0] >= S) and len(feats[k].x) < 2}
    # chain features first: a filtered x_a gained by b with a loss of x_a in a's row is a's loss
    # passing through the chain
    used = [dict(row) for row in B]
    for k, f in enumerate(feats):
        if f.chain is None:
            continue
        plain = next((i for i, g in enumerate(feats) if g.chain is None and g.x == f.x and g.stage is None), None)
        for b in range(S):
            v = used[b].get(k, 0.0)
            if f.stage is not None:
                continue
            if v > 0 and len(f.x) == 1 and f.x[0] < S:
                a = f.x[0]
                if a not in final and unit[a] == unit[b] and plain is not None and used[a].get(plain, 0.0) < 0:
                    out.append(Term("chain", src=a, dst=b, x=f.x, chain=f.chain))
                    used[a][plain] = min(0.0, used[a][plain] + v)
                    continue
            if v != 0:
                out.append(Term("chain", dst=b, x=f.x, chain=f.chain, sign=1.0 if v > 0 else -1.0))
    for k, f in enumerate(feats):
        if f.chain is not None:
            continue
        owners = set(f.x) if (f.x and all(i < S for i in f.x)) else set()
        neg = {s: -used[s][k] for s in range(S) if used[s].get(k, 0.0) < 0}
        pos = {s: used[s][k] for s in range(S) if used[s].get(k, 0.0) > 0}
        for a in sorted(neg, key=lambda s: -neg[s]):
            if a not in owners or a in final:
                continue
            for b in sorted(pos, key=lambda s: abs(pos[s] - neg[a])):
                if neg[a] <= 0:
                    break
                if b == a or unit[a] != unit[b] or pos[b] <= 0:
                    continue
                out.append(Term("move", src=a, dst=b, x=f.x))
                q = min(neg[a], pos[b])
                neg[a] -= q
                pos[b] -= q
        for a, v in neg.items():
            if v <= 1e-15:
                continue
            if a in owners and a not in final:
                out.append(Term("out", src=a, x=f.x))
            elif len(f.x) == 1:
                if f.x[0] < S and a in pooled:
                    out.append(Term("gap", dst=a, x=f.x))
                elif a not in final:
                    out.append(Term("drain", src=a, x=f.x))
        for b, v in pos.items():
            if v <= 1e-15:
                continue
            if not f.x:
                out.append(Term("in", dst=b))
            elif len(f.x) == 1:
                out.append(Term("link", dst=b, x=f.x))
            else:
                out.append(Term("plink", dst=b, x=f.x))
    return list(dict.fromkeys(out))
