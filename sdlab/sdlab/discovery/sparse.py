"""One stock's row by sparse regression (PySINDy's STLSQ), with its outside inflow in pieces.

change of s at t = u_s(t) + sum over library terms f of xi[s][f] x f(t-1)

The terms are chosen by sequentially thresholded least squares over a path of thresholds, the
threshold whose support has the lowest BIC winning (Mangan et al. 2017). The outside inflow u_s is
found as in the matrix method: pieces of constant mean in what the terms leave unexplained (PELT),
taken out of the regression by removing each piece's mean. Each STLSQ run is fed the Cholesky
factor of the (demeaned) Gram matrix instead of the steps: the same least-squares problem with one
row per term, so a path over 36k steps costs no more than one over 100.
"""

from __future__ import annotations

import math
import warnings

import numpy as np
import pysindy as ps

from .changes import pelt
from .regression import fit_subset, piece_values, row_sums

THRESHOLDS = np.geomspace(3e-4, 0.5, 18)


def _bic(T: int, rss: float, p: int) -> float:
    return T * math.log(max(rss, 1e-12) / T) + p * math.log(T)


def _ebic(T: int, rss: float, p: int, k: int, P: int, gamma: float) -> float:
    """BIC plus the price of having picked k of P candidate terms (extended BIC, Chen & Chen 2008):
    a large library offers many chances for a term to fit noise or an unexplained input."""
    return _bic(T, rss, p) + 2 * gamma * (math.lgamma(P + 1) - math.lgamma(k + 1) - math.lgamma(P - k + 1))


def select(y: np.ndarray, X: np.ndarray, cuts: list[int] | None, opt_ssr: bool = True, gamma: float = 0.0, refine: bool = True,
           simpler: dict[int, list[int]] | None = None) -> list[int]:
    """The columns of X (terms x steps) on the BIC-best support of an STLSQ threshold path and an
    SSR elimination path. simpler: for a product's column, its factors' level columns - a product
    is kept only if it beats each of them (and leaving it out) by more than log T, so that a
    product does not stand in for a level it barely differs from (A x C where C hardly moves)."""
    sums = row_sums(y, X, cuts)
    T = y.shape[0]
    pieces = sums.pieces
    d = np.sqrt(np.maximum(np.diag(sums.G), 1e-300))
    ok = d > 1e-12 * (d.max() + 1e-300)
    sy = math.sqrt(max(sums.yy, 1e-300))
    G = sums.G / np.outer(d, d)
    G[np.diag_indices_from(G)] += 1e-10
    G = G[np.ix_(ok, ok)]
    b = (sums.b / d / sy)[ok]
    idx = np.flatnonzero(ok)
    try:
        R = np.linalg.cholesky(G).T
    except np.linalg.LinAlgError:
        w, V = np.linalg.eigh(G)
        R = (V * np.sqrt(np.maximum(w, 0))).T
    z = np.linalg.lstsq(R.T, b, rcond=None)[0]
    seen: dict[tuple, float] = {}
    best = (tuple(), _bic(T, sums.yy, pieces))
    P = len(idx)
    supports = []
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        for th in THRESHOLDS:                          # sequentially thresholded least squares
            opt = ps.STLSQ(threshold=th, alpha=1e-9, max_iter=25, unbias=True)
            opt.fit(R, z)
            supports.append(np.flatnonzero(np.abs(opt.coef_[0]) > 0))
        if len(idx) > 1 and opt_ssr:                   # stepwise sparse regression: drop the term whose loss costs least
            opt = ps.SSR(alpha=1e-9, max_iter=len(idx) - 1, criteria="model_residual")
            opt.fit(R, z)
            supports += [np.flatnonzero(np.abs(np.asarray(h)[0]) > 0) for h in opt.history_]
    def score(supp):
        if supp not in seen:
            seen[supp] = _ebic(T, fit_subset(sums, list(supp)).rss, len(supp) + pieces, len(supp), P, gamma)
        return seen[supp]

    for sq in supports:
        supp = tuple(sorted(int(idx[q]) for q in sq))
        if score(supp) < best[1]:
            best = (supp, score(supp))
    # the paths can pass by the best support (one collinear term standing in for another): polish
    # the winner by single additions, removals and swaps while the score falls
    for _ in range(P if refine else 0):
        cur = set(best[0])
        moves = [cur - {i} for i in cur] + [cur | {j} for j in idx if j not in cur] + [(cur - {i}) | {j} for i in cur for j in idx if j not in cur]
        cand = min((tuple(sorted(m)) for m in moves), key=score, default=None)
        if cand is None or score(cand) >= best[1] - 1e-9:
            break
        best = (cand, score(cand))
    changed = bool(simpler)
    while changed:
        changed = False
        for i in best[0]:
            if i not in (simpler or {}):
                continue
            cur = set(best[0]) - {i}
            for alt in [cur | {j} for j in simpler[i] if j not in cur] + [cur]:
                alt = tuple(sorted(alt))
                if score(alt) < best[1] + math.log(T):
                    best, changed = (alt, score(alt)), True
                    break
            if changed:
                break
    return list(best[0])


def fit_row(y: np.ndarray, X: np.ndarray, allowed: list[int], inflow: str = "changing", min_piece: int = 5, simple: list[int] | None = None,
            gamma: float = 0.0, pelt_mult: float = 1.0, simpler: dict[int, list[int]] | None = None) -> dict:
    """y: one stock's change per step; X: library values (terms x steps); allowed: the terms this
    row may use; simple: those used in the first pass, before the inflow's pieces are known (so that
    products do not stand in for changes in the inflow). Returns the chosen terms, their numbers,
    and the outside inflow's pieces."""
    T = y.shape[0]
    Xa = X[allowed] if allowed else np.zeros((0, T))
    first = [q for q, f in enumerate(allowed) if f in set(simple)] if simple is not None else None
    at = {f: q for q, f in enumerate(allowed)}
    simp = {at[f]: [at[j] for j in js if j in at] for f, js in (simpler or {}).items() if f in at}
    P = len(allowed)

    def form(c, extra, chosen=None):
        chosen = select(y, Xa, c, gamma=gamma, simpler=simp) if chosen is None else chosen
        f = fit_subset(row_sums(y, Xa, c), chosen)
        return {"cuts": c, "chosen": chosen, "f": f, "sc": _ebic(T, f.rss, len(chosen) + extra, len(chosen), P, gamma)}

    # the outside inflow: none, constant, or changing - each with the terms chosen beside it (a
    # changing inflow only for a stock whose inflow is on average clearly one way, as in matrix.py)
    pick = form(None, 0)
    if inflow != "none":
        const = form([0, T], 1)
        pick = const if const["sc"] < pick["sc"] else pick
    if inflow == "changing":
        cuts = [0, T]
        for p in range(5):
            if p == 0 and first is not None:
                chosen = [first[q] for q in select(y, Xa[first], cuts, gamma=gamma)]
            else:
                chosen = select(y, Xa, cuts, gamma=gamma, simpler=simp)
            f = fit_subset(row_sums(y, Xa, cuts), chosen)
            nxt = pelt(y - (f.beta @ Xa[chosen] if chosen else 0), min_piece, 0.5 if p == 0 else pelt_mult)
            if nxt == cuts and p >= 2:
                break
            cuts = nxt
        if len(cuts) > 2:
            pcs = form(cuts, len(cuts) - 1)
            vals = piece_values(y, Xa, pcs["chosen"], pcs["f"].beta, cuts)
            W = sum(v["w"] for v in vals)
            mean = sum(v["v"] * v["w"] for v in vals) / W
            sd = math.sqrt(sum(v["w"] * (v["v"] - mean) ** 2 for v in vals) / W)
            if (pick is const or abs(mean) > 0.5 * sd) and pcs["sc"] < pick["sc"]:
                pick = pcs
    chosen, beta = pick["chosen"], pick["f"].beta
    pieces = piece_values(y, Xa, chosen, beta, pick["cuts"]) if pick["cuts"] else []
    return {"terms": [allowed[q] for q in chosen], "beta": [float(b) for b in beta], "pieces": pieces, "cuts": pick["cuts"],
            "rss": pick["f"].rss, "p": len(chosen) + (len(pick["cuts"]) - 1 if pick["cuts"] else 0)}


def inflow_series(row: dict, T: int) -> np.ndarray:
    u = np.zeros(T)
    for g in row["pieces"]:
        u[g["a"]:g["b"]] = g["v"]
    return u


def plain_sindy(prev: np.ndarray, dy: np.ndarray) -> list[dict]:
    """The reference point: PySINDy as it comes (levels and a constant, STLSQ with normalised
    columns, one threshold for every stock, chosen by the summed BIC over a path)."""
    S, T = prev.shape
    best = None
    for th in THRESHOLDS:
        model = ps.SINDy(optimizer=ps.STLSQ(threshold=th, normalize_columns=True), feature_library=ps.PolynomialLibrary(degree=1, include_bias=True))
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            model.fit(prev.T, t=1.0, x_dot=dy.T)
        coef = model.coefficients()
        res = dy.T - model.predict(prev.T)
        sc = sum(_bic(T, float((res[:, s] ** 2).sum()), int((coef[s] != 0).sum())) for s in range(S))
        if best is None or sc < best[0]:
            best = (sc, coef, res)
    _, coef, res = best
    rows = []
    for s in range(S):
        terms = [j for j in range(S) if coef[s, j + 1] != 0]
        c = float(coef[s, 0])
        rows.append({"terms": terms, "beta": [float(coef[s, j + 1]) for j in terms],
                     "pieces": [{"a": 0, "b": T, "w": T, "v": c}] if c else [], "cuts": [0, T] if c else None,
                     "rss": float((res[:, s] ** 2).sum()), "p": len(terms) + (1 if c else 0)})
    return rows
