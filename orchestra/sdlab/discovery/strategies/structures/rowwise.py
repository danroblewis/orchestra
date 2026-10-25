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


def select_row(M: np.ndarray, y: np.ndarray, w: np.ndarray, counts: bool, eps: float, allowed: list[int], groups: dict | None = None,
               plain: list[int] | None = None) -> dict[int, float]:
    """One stock's regression: forward selection by BIC with a backward pass after each step, checked against
    the best small subset (best_subset; plain: the columns triples are drawn from, None for none).
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
    # (k8s 315, docs/research/fixes/315-structures.md) the greedy path checked against the best small subset: where
    # other stocks' levels nearly span this row's own (a caller's level is a callee queue's change plus its drain),
    # the first greedy step picks a proxy and the row ends at 24 collinear columns with the exact 2 never tried
    sub = best_subset(M, y, w, counts, eps, allowed, groups, plain)
    if sub is not None:
        _, r_now = _ols(M, y, w, idx)
        if sub[0] < _crit(r_now, w, counts, eps, len(idx), log_t) - 1e-9:
            idx, b = sub[1], sub[2]
    return {j: float(v) for j, v in zip(idx, b)}


SUBSET_PAIRS = 400       # every pair of columns is tried up to this many columns (all of them, products included)
SUBSET_TRIPLES = 40      # every triple of plain (non-product) columns up to this many
SUBSET_TOP = 4           # the best few of each size by the batched normal equations, refitted by least squares


def best_subset(M: np.ndarray, y: np.ndarray, w: np.ndarray, counts: bool, eps: float, allowed: list[int],
                groups: dict | None = None, plain: list[int] | None = None) -> tuple[float, list[int], np.ndarray] | None:
    """The row's best subset of 1-3 columns on the same BIC as select_row: every single and pair of the
    allowed columns (a chain's start contents go with its feed, as in the forward pass) and every triple of
    the plain ones (no product, no chain), ranked at once by the scaled normal equations (fast, imprecise
    near exact) and the best SUBSET_TOP of each size refitted by least squares (exact). The same rule on every
    row: nothing reads the case. Copied in spirit from kalman_lna's subsets.py (6fd4778): batched Gram stack,
    refit of the few best."""
    import itertools

    groups = groups or {}
    log_t = math.log(max(2, len(y)))
    cols = [j for j in allowed if not groups.get(j)]           # a chain feed with its start contents: too wide
    if not cols:
        return None
    sw = np.sqrt(w)
    A = M[cols] * sw                                           # L x T
    nrm = np.linalg.norm(A, axis=1)
    keep = nrm > 0
    cols = [c for c, k in zip(cols, keep) if k]
    A = A[keep] / nrm[keep][:, None]
    yw = y * sw
    G = A @ A.T
    g = A @ yw
    yy = float(yw @ yw)
    L = len(cols)
    best = None

    def consider(combos: np.ndarray):
        nonlocal best
        if not len(combos):
            return
        k = combos.shape[1]
        Gs = G[combos[:, :, None], combos[:, None, :]] + 1e-12 * np.eye(k)[None]
        rs = g[combos]
        try:
            bs = np.linalg.solve(Gs, rs[:, :, None])[:, :, 0]
        except np.linalg.LinAlgError:
            return
        rss = yy - np.einsum("ni,ni->n", bs, rs)
        for i in np.argsort(rss)[:SUBSET_TOP]:
            idx = [cols[c] for c in combos[i]]
            bb, rr = _ols(M, y, w, idx)
            c = _crit(rr, w, counts, eps, len(idx), log_t)
            if best is None or c < best[0] - 1e-9:
                best = (c, idx, bb)

    consider(np.arange(L)[:, None])
    if L <= SUBSET_PAIRS:
        consider(np.array(list(itertools.combinations(range(L), 2)), dtype=int).reshape(-1, 2))
    tri = [i for i, c in enumerate(cols) if c in set(plain or ())]
    if 3 <= len(tri) <= SUBSET_TRIPLES:
        consider(np.array(list(itertools.combinations(tri, 3)), dtype=int).reshape(-1, 3))
    return best


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
    plain = [k for k, f in enumerate(feats) if f.chain is None and f.stage is None and len(f.x) < 2]
    for s in range(S):
        w = 1.0 / var[s]
        row = select_row(M, dy[s], w, counts, eps, allowed, groups, plain)
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


def starts(rows: Rows, dy: np.ndarray, var: np.ndarray, counts: bool, eps: float, S: int, m: int, unit: list[str], final: set[int],
           products: bool = True) -> list[list[Term]]:
    """The rows read twice: a product's loss and gain paired into a move only when they match (a
    predator's catch and its births differ), and paired at the smaller whatever they are (noise
    makes a true move's two rows differ). The search runs from both."""
    feats, B, _ = regress(rows, dy, var, counts, eps, S, m, products, None, final)
    a, b = translate(B, feats, S, unit, final), translate(B, feats, S, unit, final, whole=False)
    return [a] if a == b else [a, b]


def translate(B: list[dict[int, float]], feats: list[Feature], S: int, unit: list[str], final: set[int], whole: bool = True) -> list[Term]:
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
                if whole and len(f.x) == 2 and abs(pos[b] - neg[a]) > 0.05 * max(pos[b], neg[a]):
                    continue           # at a product only a whole move (fit.conventions; 127's predation and births)
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
