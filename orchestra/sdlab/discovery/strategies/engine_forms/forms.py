"""The forms a stock's exchange with the outside is fitted in (engine_forms).

Each family fits the stock's one-step change left after the flows it keeps (target y) and returns
a Fit: the fitted change, how many numbers it used, and the flows that write it.

- linear: c + sum k_j z_j over the stock's own level, the inputs and the other stocks, with no
  floor (a rate that runs both ways). Kept only where the plain one-way flows would be floored on
  the run's states (an input that changes sign) or the stock goes below 0: elsewhere the base
  strategy already writes it.
- min: a drain at the lesser of two expressions, a x (the stock's own level) and c + sum b_j z_j
  (the capacity: other stocks or inputs), beside an inflow c0: MIN(capacity, level).
- table: m x T(z) beside a linear part over 1, the own level and the inputs, with T a piecewise
  linear table (heights at least 0) of a stock or an input z, and m 1 or an input: an inflow
  switched on by another stock (a dead zone), an own-level gate on a measured input (admission).
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field

import numpy as np
from scipy.optimize import least_squares

from . import fit as F
from .linear import ONE, needs_shift
from .linear import write as write_linear
from .steps import Steps


@dataclass
class Fit:
    family: str
    yhat: np.ndarray
    p: int
    flows: list[dict]
    detail: dict = field(default_factory=dict)


def _subsets(names: list[str], most: int):
    for k in range(0, min(most, len(names)) + 1):
        yield from itertools.combinations(names, k)


def best_linear(y: np.ndarray, st: Steps, readers: list[str], floor: float, most: int = 4) -> tuple[dict, np.ndarray, float]:
    """The subset of readers (a constant always allowed) fitted by least squares with the lowest
    BIC: (coefficients, fitted values, bic)."""
    best = None
    for sub in _subsets(readers, most):
        for const in (True, False):
            cols = ([ONE] if const else []) + list(sub)
            if not cols:
                continue
            X = np.column_stack([np.ones(st.n) if c == ONE else st.series(c) for c in cols])
            b = F.bounded(X * st.w[:, None], y * st.w, np.full(len(cols), -np.inf), np.full(len(cols), np.inf))
            yh = X @ b
            score = F.bic(((y - yh) * st.w)[st.w > 0], len(cols), floor)
            if best is None or score < best[2]:
                best = ({c: float(v) for c, v in zip(cols, b)}, yh, score)
    return best


def linear(x: str, y: np.ndarray, st: Steps, floor: float) -> Fit | None:
    readers = [x] + sorted(st.U) + [s for s in st.ids if s != x]
    coef, yh, _ = best_linear(y, st, readers, floor)
    signed = st.signed(x)
    if not signed and (needs_shift(coef, st) <= 0 or np.min(st.series(x)) < 0):
        return None                      # one-way flows write it (or the levels only dip below 0 by error)
    return Fit("linear", yh, len(coef), write_linear(x, coef, st, signed), {"coef": coef, "signed": signed})


# ---- MIN(capacity, level) ----

def _min_fit(y: np.ndarray, xs: np.ndarray, Z: np.ndarray, a0: float, w: np.ndarray) -> tuple[np.ndarray, np.ndarray] | None:
    """y ~ c0 - min(a xs, c + Z b) on the steps w reads: (params [c0, a, c, b...], fitted)."""

    def model(p):
        a, c, b = p[0], p[1], p[2:]
        drain = np.minimum(a * xs, c + Z @ b)
        c0 = float(np.sum((y + drain) * w) / max(1.0, np.sum(w)))
        return c0 - drain, c0

    def res(p):
        return (model(p)[0] - y) * w

    # the capacity's start: the drain read where the level is large (the capacity binds)
    big = (xs >= np.quantile(xs, 0.7)) & (w > 0)
    X = np.column_stack([np.ones(int(big.sum())), Z[big]])
    try:
        b0, *_ = np.linalg.lstsq(X, -y[big] + np.mean(y), rcond=None)
    except np.linalg.LinAlgError:
        return None
    p0 = np.concatenate([[a0], b0])
    try:
        r = least_squares(res, p0, method="trf", x_scale="jac", max_nfev=400)
    except (ValueError, np.linalg.LinAlgError):
        return None
    yh, c0 = model(r.x)
    return np.concatenate([[c0], r.x]), yh


def mins(x: str, y: np.ndarray, st: Steps, floor: float) -> Fit | None:
    xs = st.series(x)
    if np.min(xs) < 0 or np.ptp(xs) <= 0:
        return None
    others = [s for s in st.ids if s != x] + sorted(st.U)
    best = None
    for k in (1, 2):
        for sub in itertools.combinations(others, k):
            Z = np.column_stack([st.series(z) for z in sub])
            for a0 in (0.05, 0.2, 0.5, 1.0):
                got = _min_fit(y, xs, Z, a0, st.w)
                if got is None:
                    continue
                p, yh = got
                a, c, b = p[1], p[2], p[3:]
                if a <= 0:
                    continue
                own = a * xs < c + Z @ b
                share = float(own.mean())
                if share < 0.05 or share > 0.95:      # one branch only: not a MIN
                    continue
                score = F.bic(((y - yh) * st.w)[st.w > 0], len(p), floor)
                if best is None or score < best[0]:
                    best = (score, sub, p, yh, share)
    if best is None:
        return None
    _, sub, p, yh, share = best
    c0, a, c, b = p[0], p[1], p[2], p[3:]
    if c0 < -1e-6 * (1 + abs(float(np.mean(y)))):         # the inflow beside the MIN would be negative
        return None
    cap = " + ".join([f"{c:.6g}"] + [f"{bj:.6g} * {z}" for bj, z in zip(b, sub)]) if abs(c) > 0 else \
        " + ".join(f"{bj:.6g} * {z}" for bj, z in zip(b, sub))
    expr = f"min({a:.6g} * {x}, {cap})"
    flows = [{"from": x, "to": None, "ratio": 1, "rate": {"form": "expr", "expr": expr}, "engine_forms": True}]
    if c0 > 0:
        flows.append({"from": None, "to": x, "ratio": 1, "rate": {"form": "constant", "value": float(c0)}, "engine_forms": True})
    return Fit("min", yh, len(p), flows, {"expr": expr, "c0": c0, "own_share": share})


# ---- tables ----

KNOTS = 8
KS = (4, 6, 8)


def _knots(z: np.ndarray, k: int) -> np.ndarray:
    """Evenly over the range z covers (refine() moves them to where the table bends)."""
    return np.linspace(float(z.min()), float(z.max()), k)


def hats(z: np.ndarray, knots: np.ndarray) -> np.ndarray:
    """Columns: the piecewise linear basis on knots (held at the ends)."""
    out = np.zeros((len(z), len(knots)))
    for j in range(len(knots)):
        e = np.zeros(len(knots))
        e[j] = 1.0
        out[:, j] = np.interp(z, knots, e)
    return out


SHAPES = ("free", "up", "down")


def _shape(k: int, shape: str) -> np.ndarray:
    """Heights = C d with d >= 0: free (C = I), rising (cumulated from the left) or falling (from the right)."""
    if shape == "up":
        return np.tril(np.ones((k, k)))
    if shape == "down":
        return np.triu(np.ones((k, k)))
    return np.eye(k)


def _table_fit(y, st, x, z, mult, lin_names, knots, floor, shape="free"):
    C = _shape(len(knots), shape)
    H = hats(st.series(z), knots) @ C
    if mult is not None:
        H = H * st.series(mult)[:, None]
    L = np.column_stack([np.ones(st.n) if c == ONE else st.series(c) for c in lin_names]) if lin_names else np.zeros((st.n, 0))
    X = np.column_stack([H, L])
    lo = np.concatenate([np.zeros(H.shape[1]), np.full(L.shape[1], -np.inf)])
    hi = np.full(X.shape[1], np.inf)
    b = F.bounded(X * st.w[:, None], y * st.w, lo, hi)
    yh = X @ b
    heights = C @ b[: len(knots)]
    return heights, {c: float(v) for c, v in zip(lin_names, b[len(knots):])}, yh, F.bic(((y - yh) * st.w)[st.w > 0], len(b) + len(knots), floor)


def _refine(y, st, x, z, mult, lin_names, knots, floor, shape):
    """The knots moved to where the table bends (heights refitted at every move)."""
    lo_z, hi_z = float(knots[0]), float(knots[-1])
    inner = knots[1:-1]
    if len(inner) == 0:
        return knots

    def res(u):
        kn = np.concatenate([[lo_z], np.sort(np.clip(u, lo_z + 1e-9, hi_z - 1e-9)), [hi_z]])
        if np.any(np.diff(kn) <= 1e-9 * (hi_z - lo_z)):
            return np.full(st.n, 1e6)
        _, _, yh, _ = _table_fit(y, st, x, z, mult, lin_names, kn, floor, shape)
        return (yh - y) * st.w

    try:
        r = least_squares(res, inner, method="trf", diff_step=1e-3, max_nfev=60)
    except (ValueError, np.linalg.LinAlgError):
        return knots
    return np.concatenate([[lo_z], np.sort(r.x), [hi_z]])


def tables(x: str, y: np.ndarray, st: Steps, floor: float) -> Fit | None:
    """The table's reader, multiplier and linear part chosen with KNOTS free heights; then its
    shape (free, rising, falling) and number of knots (KS), knots refined, by BIC."""
    zs = [s for s in st.ids] + sorted(st.U)
    mults = [None] + sorted(st.U)
    best = None
    for z in zs:
        zv = st.series(z)
        if np.ptp(zv) <= 0:
            continue
        knots = _knots(zv, KNOTS)
        for mult in mults:
            if mult is not None and mult == z:
                continue
            lin_pool = [x] + [u for u in sorted(st.U) if u != mult]
            for sub in _subsets(lin_pool, 2):
                for const in ((True, False) if mult is not None else (False,)):   # a table holds its own constant
                    lin = ([ONE] if const else []) + list(sub)
                    shape = "down" if z == x and mult is None and x in lin else "free"
                    h, coef, yh, score = _table_fit(y, st, x, z, mult, lin, knots, floor, shape)
                    if best is None or score < best[0]:
                        best = (score, z, mult, lin)
    if best is None:
        return None
    _, z, mult, lin = best
    pick = None
    # a table of x's own level beside a drain of x: a rising table and the drain trade off along
    # a straight line in x (any k x added to both), so only a falling one is read
    shapes = ("down",) if z == x and mult is None and x in lin else SHAPES
    for k in KS:
        for shape in shapes:
            kn = _refine(y, st, x, z, mult, lin, _knots(st.series(z), k), floor, shape)
            h, coef, yh, score = _table_fit(y, st, x, z, mult, lin, kn, floor, shape)
            if pick is None or score < pick[0]:
                pick = (score, kn, h, coef, yh, shape)
    _, knots, h, coef, yh, shape = pick
    if float(np.max(h)) <= 0:
        return None
    pts = [[float(a), float(v)] for a, v in zip(knots, h)]
    rate = {"form": "constant", "value": 1.0} if mult is None else {"form": "proportional", "stock": mult, "k": 1.0}
    flows = [{"from": None, "to": x, "ratio": 1, "rate": rate, "effects": [{"stock": z, "shape": "table", "points": pts}],
              "engine_forms": True}]
    flows += write_linear(x, coef, st, signed=False)
    return Fit("table", yh, 2 * len(knots) + len(coef), flows, {"z": z, "mult": mult, "shape": shape, "points": pts, "linear": coef})


FAMILIES = {"linear": linear, "min": mins, "table": tables}
