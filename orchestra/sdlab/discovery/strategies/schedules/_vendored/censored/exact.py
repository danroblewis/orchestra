"""Exact rows: a stock whose change the levels and measured inputs explain to the levels' rounding.

A stock with noise-free flows among counted ones (a controller's integral I, fed by the setpoint and
drained at the measured level: dI = r - Y on every step) changes by an exact linear combination of
the columns, while every other row carries counting noise. The main line weighs such a row like the
others and can write its input as a constant at the input's mean or as pieces (216, from 214, 202,
207, 203, 209). Here the row's change, less what its moves between measured stocks bring, is
regressed on every level, every measured input and a constant; if that fit is exact (its residual at
the rounding floor), the columns that are not needed are dropped one at a time while it stays exact,
and the row's flows to and from outside are rewritten as one flow per column (positive: an inflow on
it; negative: a drain of the row's own level or an outflow reading the other column). Exactness is
read from the data alone: nothing says which stocks are noise-free.
"""

from __future__ import annotations

import numpy as np

EXACT = 4.0          # an exact row's residual sum of squares is at most this many times the rounding floor


def _rss(A: np.ndarray, y: np.ndarray) -> tuple[float, np.ndarray]:
    b, *_ = np.linalg.lstsq(A, y, rcond=None)
    r = y - A @ b
    return float(r @ r), b


def fit(y: np.ndarray, X: np.ndarray, floor_rss: float) -> dict | None:
    """{cols, k, c, rss} of the sparsest exact fit of y on X's rows (and a constant), or None when the
    full fit is not exact. Column index len(X) is the constant."""
    T = len(y)
    if T < 20 or float(y @ y) <= floor_rss * EXACT:
        return None
    full = [j for j in range(len(X)) if np.ptp(X[j]) > 0] + [len(X)]
    cols_of = lambda cs: np.vstack([X[j] if j < len(X) else np.ones(T) for j in cs]).T  # noqa: E731
    limit = EXACT * floor_rss
    rss, _ = _rss(cols_of(full), y)
    if rss > limit:
        return None
    cur = list(full)
    while len(cur) > 1:
        best = None
        for j in cur:
            rest = [m for m in cur if m != j]
            r, _ = _rss(cols_of(rest), y)
            if r <= limit and (best is None or r < best[0]):
                best = (r, rest)
        if best is None:
            break
        cur = best[1]
    rss, b = _rss(cols_of(cur), y)
    k = {j: float(v) for j, v in zip(cur, b) if j < len(X)}
    c = float(next((v for j, v in zip(cur, b) if j == len(X)), 0.0))
    return {"k": k, "c": c, "rss": rss}


def _r(v: float) -> float:
    a = abs(v)
    return round(float(v), 2 if a >= 100 else 4 if a >= 1 else 6)


def _flow(src, dst, rate: dict, **extra) -> dict:
    return {"from": src, "to": dst, "ratio": 1, "rate": rate, "rates": [rate], "nearly": [], "bothWays": False, **extra}


def as_flows(f: dict, row: str, names: list[str], inputs: list[str] = ()) -> list[dict]:
    """The exact row as flows to and from outside, one per column."""
    out = []
    for j, k in sorted(f["k"].items()):
        nm = names[j]
        mark = {"input": nm} if nm in inputs else {}
        if k > 0:
            out.append(_flow(None, row, {"form": "linear", "c": 0, "terms": [{"stock": nm, "k": _r(k)}]}, **mark))
        elif nm == row:
            out.append(_flow(row, None, {"form": "proportional", "stock": row, "k": _r(-k)}))
        else:
            out.append(_flow(row, None, {"form": "linear", "c": 0, "terms": [{"stock": nm, "k": _r(-k)}]}, **mark))
    if f["c"] > 1e-9:
        out.append(_flow(None, row, {"form": "constant", "value": _r(f["c"])}))
    elif f["c"] < -1e-9:
        out.append(_flow(row, None, {"form": "constant", "value": _r(-f["c"])}))
    return out
