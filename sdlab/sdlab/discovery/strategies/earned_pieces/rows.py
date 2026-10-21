"""Each row's levels and outside-inflow form chosen together, every change paying its full price.

The matrix chooses a row's levels in the presence of fine, cheap pieces (so that the levels are not
biased by unexplained changes) and only at the end asks whether the pieces pay. When they do not,
the row keeps the levels chosen beside them: often too few (a level the pieces stood in for), so
that the pieces then pay after all, for the levels' sake. Here the matrix's row is one candidate;
the others are the levels chosen afresh by backward elimination from every level the row may read
(and, with numbers per configuration, every level's number per configuration), with no outside
inflow, a constant one, or the matrix's pieces. All are compared by BIC with each change in the
outside inflow priced as a value and a place (2 parameters).
"""

from __future__ import annotations

import math

import numpy as np

from scipy.stats import chi2

from ...regression import fit_subset, row_sums

ALPHA = 0.01        # the whiteness test's level


def _bic(T: int, rss: float, p: float, floor: float = 0.0) -> float:
    return T * math.log(max(rss, floor, 1e-12) / T) + p * math.log(T)


def resolution(levels: np.ndarray) -> float:
    """The data's quantum: the largest power of ten (1 down to 1e-8) every level is a whole multiple
    of (1 for counts; 1e-4 for levels rounded to four decimals), 0 when there is none."""
    a = np.abs(np.asarray(levels, dtype=float).ravel())
    a = a[np.isfinite(a)]
    for e in range(0, 9):
        q = 10.0 ** -e
        if np.all(np.abs(a / q - np.round(a / q)) < 1e-6):
            return q
    return 0.0


def rss_floor(levels: np.ndarray, T: int) -> float:
    """Below this a row's residual sum of squares says nothing: each step's change carries two
    roundings of the levels (variance q^2 / 12 each)."""
    q = resolution(levels)
    return T * q * q / 6


def inflow_params(cuts: list[int] | None, per_change: float = 2) -> float:
    """A constant is one parameter; every change adds a value and a place."""
    return 0 if not cuts else 1 + per_change * (len(cuts) - 2)


def columns(s: int, ids: list[str], prev: np.ndarray, cfg: np.ndarray, L: int, allowed: list[int]) -> tuple[np.ndarray, list[tuple[int, int]]]:
    """The row's columns: each allowed level, and with configurations its number's departure in
    every configuration but the first (col: (stock index, configuration or -1 for shared))."""
    X, col = [], []
    for j in allowed:
        X.append(prev[j])
        col.append((j, -1))
        for c in range(1, L):
            m = cfg == c
            if m.any() and not m.all():
                X.append(np.where(m, prev[j], 0.0))
                col.append((j, c))
    return np.array(X) if X else np.zeros((0, prev.shape[1])), col


def backward(y: np.ndarray, X: np.ndarray, cuts: list[int] | None, start: list[int], extra_p: float, floor: float = 0.0) -> tuple[list[int], float, float]:
    """Backward elimination by BIC from start (then re-adding any column that pays): the chosen
    columns, rss and BIC."""
    T = y.shape[0]
    sums = row_sums(y, X, cuts)
    chosen = list(start)

    def sc(cols):
        f = fit_subset(sums, cols)
        return _bic(T, f.rss, len(cols) + extra_p, floor), f.rss

    cur, rss = sc(chosen)
    while True:
        best = None
        for j in range(X.shape[0]):
            trial = [q for q in chosen if q != j] if j in chosen else chosen + [j]
            s, r = sc(trial)
            if s < cur - 1e-9 and (best is None or s < best[1]):
                best = (trial, s, r)
        if best is None:
            return chosen, rss, cur
        chosen, cur, rss = best


def white(e: np.ndarray, alpha: float = ALPHA) -> bool:
    """Ljung-Box: no autocorrelation in e up to lag ceil(sqrt(T)) at level alpha (a row that leaves
    a slow pattern in its residuals is missing something: here, an outside inflow that changes)."""
    e = np.asarray(e, dtype=float) - float(np.mean(e))
    n = e.shape[0]
    v = float(e @ e)
    if n < 10 or v <= 0:
        return True
    m = min(n - 2, int(math.ceil(math.sqrt(n))))
    r = np.array([float(e[k:] @ e[:-k]) / v for k in range(1, m + 1)])
    q = n * (n + 2) * float(np.sum(r * r / (n - np.arange(1, m + 1))))
    return bool(chi2.sf(q, m) > alpha)


def reselect(row: dict, s: int, ids: list[str], stocks: list[dict], prev: np.ndarray, dy: np.ndarray, cfg: np.ndarray, L: int,
             per_change: float = 2, alpha: float = ALPHA, floor: float = 0.0, levels: str = "both", inputs: list[int] = (),
             pieces_ok: bool = True, exclude: tuple = ()) -> dict:
    """The row as the matrix fitted it, or levels chosen again with no outside inflow or a constant
    one. A row with pieces is replaced only by one whose residuals are white (nothing left for
    pieces to explain) and whose BIC, every change priced as a value and a place, is lower; a row
    without pieces by one with a lower BIC.

    levels: where the levels of a row with pieces are chosen again: "afresh" (without pieces, for
    each form), "beside" (beside the pieces, so that a change in the inflow cannot hide in a level
    that happens to follow it, then the pieces are dropped) or "both" (each set is tried).

    inputs: the rows of prev after the stocks' that are measured inputs' values (indices into prev);
    every row may read them, as the matrix's rows may.

    The declared boundary (boundary.py, a copy of matrix's): pieces_ok: whether the row may have an
    outside term at all (a constant or pieces); exclude: rows of prev it may not read. A matrix row that
    breaks either is no incumbent: the best row inside them replaces it, white or not."""
    T = dy.shape[1]
    y = dy[s]
    group = {x["id"]: x.get("group") for x in stocks}
    final = {x["id"] for x in stocks if x.get("final")}
    allowed = [j for j in range(len(ids)) if not (ids[s] in final and j == s)
               and (j == s or not group.get(ids[j]) or not group.get(ids[s]) or group[ids[j]] == group[ids[s]])] + list(inputs)
    allowed = [j for j in allowed if j not in exclude]
    pieces = bool(row["cuts"]) and len(row["cuts"]) > 2
    inside = (pieces_ok or not row["cuts"]) and not any(row["col"][q][0] in exclude for q in row["set"])
    best = {"row": row, "bic": _bic(T, row["rss"], len(row["set"]) + inflow_params(row["cuts"], per_change), floor) if inside else math.inf,
            "name": "matrix"}
    X, col = columns(s, ids, prev, cfg, L, allowed)
    if not len(col):
        if inside:
            return best
        return {"row": {**row, "X": np.zeros((0, T)), "col": [], "set": [], "cuts": None, "rss": float(y @ y), "p": 0},
                "bic": _bic(T, float(y @ y), 0, floor), "name": "none"}
    everything = list(range(len(col)))
    beside = backward(y, X, row["cuts"], everything, inflow_params(row["cuts"], per_change), floor)[0] if pieces and levels != "afresh" else None
    for name, cuts in (("none", None), ("constant", [0, T])) if pieces_ok else (("none", None),):
        sets = []
        if not pieces or levels != "beside":
            sets.append(backward(y, X, cuts, everything, inflow_params(cuts, per_change), floor)[0])
        if beside is not None:
            sets.append(beside)
        for chosen in sets:
            f = fit_subset(row_sums(y, X, cuts), chosen)
            b = _bic(T, f.rss, len(chosen) + inflow_params(cuts, per_change), floor)
            if b >= best["bic"] - 1e-9:
                continue
            if pieces and inside:
                e = y - (f.beta @ X[chosen] if chosen else 0.0)
                if not white(e - (e.mean() if cuts else 0.0), alpha):
                    continue
            best = {"row": {**row, "X": X, "col": col, "set": list(chosen), "cuts": cuts, "rss": f.rss,
                            "p": len(chosen) + (len(cuts) - 1 if cuts else 0)}, "bic": b, "name": name}
    return best
