"""Floored outside flows: a stock's outside side refitted as max(0, c + w . Z) (docs/research/fixes/309-combined2.md,
2026-10-21).

The engine floors every flow at 0, so a linear rate that is negative on some steps is a gap that closes:
`max(0, desired - pending - ready)` (pods created for a deficit), `max(0, ready - desired)` (surplus pods
deleted). Fitted as an ordinary linear rate over every step, such a flow is smeared into a small drift
(0.003 x ready) or a constant, because on most steps it is exactly 0. Here, for each measured, non-final
stock X, each outside side the model has (none is added) is refitted on X's row (its one-step change less the model's flows between X and
other stocks, less its other side) as a floored linear rate on at most MAX_COLS measured stocks or inputs,
with or without a constant, and at its floor on at least MIN_OFF of the steps: the steps where the rate is positive are found by an active-set least squares
(fit on the active steps, recompute which steps are active, repeat), started from several thresholds. The
column set is chosen by BIC on X's row (fewest numbers among fits the data cannot tell apart); the new side
replaces the old one only where X's row's BIC falls by more than GAIN x log n. Reads only the levels.

Adopting it: copy this file into the strategy's package (identical copy) and call `apply(result, stocks,
run, opts)` on the answer; `refit_row` refits one stock's row (switch.py uses it for the stocks a dropped
move touched).
"""

from __future__ import annotations

import copy
import itertools
import math

import numpy as np

MAX_COLS = 3          # columns a floored rate may read
GAIN = 2.0            # BIC fall (in units of log n) a refit side must bring
FLOOR_REL = 1e-9      # SSE floor relative to the row's scale (exact data tie at it; parsimony decides)
MIN_OFF = 0.1         # a floored rate must be at its floor (rate <= 0) on at least this share of the steps:
                      # one that is positive throughout is an ordinary linear rate, not this mechanism's to refit
INITS = (1e-6, 0.25, 0.5)
ITERS = 40


def _linear(rate: dict) -> tuple[float, dict] | None:
    if not rate:
        return None
    f = rate.get("form")
    if f == "proportional":
        return 0.0, {rate.get("stock"): float(rate.get("k") or 0.0)}
    if f == "linear":
        return float(rate.get("c") or 0.0), {t.get("stock"): float(t.get("k") or 0.0) for t in rate.get("terms") or []}
    if f in ("constant", "const"):
        return float(rate.get("k", rate.get("c", rate.get("value", 0.0))) or 0.0), {}
    return None


def amount(f: dict, cols: dict, n: int) -> np.ndarray | None:
    """A linear flow's amount per step on the record's states (floored at 0 as the engine does); None when
    this cannot evaluate it."""
    if f.get("byTime") or f.get("uses") or f.get("two_way") or f.get("via"):
        return None
    lf = _linear(f.get("rate") or {})
    if lf is None:
        # (2026-10-22, k8s-311) an expression of arithmetic and MIN / MAX on measured columns (a capacity
        # limit written back by capmin.restore) is evaluated too; one with a comparison (a switch) is not
        r = expr_amount((f.get("rate") or {}).get("expr"), cols, n) if (f.get("rate") or {}).get("form") == "expr" else None
        if r is None:
            return None
    elif any(j not in cols for j in lf[1]):
        return None
    else:
        c, ks = lf
        r = np.full(n, c, dtype=float)
        for j, k in ks.items():
            r = r + k * cols[j][:n]
    r = np.maximum(0.0, r)
    for e in f.get("effects") or []:              # (2026-10-21, k8s-310) a table effect on a measured column
        pts = sorted((float(a), float(b)) for a, b in (e.get("points") or []))
        if e.get("shape") != "table" or not pts or e.get("stock") not in cols:
            return None
        r = r * np.maximum(0.0, np.interp(cols[e["stock"]][:n], [p[0] for p in pts], [p[1] for p in pts]))
    return r


def hfit(Z: np.ndarray, y: np.ndarray) -> tuple[float, np.ndarray] | None:
    """min_b sum (max(0, Z b) - y)^2 by active-set least squares from several starts: (sse, b)."""
    n, m = Z.shape
    top = float(np.max(y)) if y.size else 0.0
    if top <= 0:
        return None
    best = None
    for t in INITS:
        A = y > t * top
        b = None
        for _ in range(ITERS):
            if A.sum() < m + 1:
                break
            b, *_ = np.linalg.lstsq(Z[A], y[A], rcond=None)
            A2 = (Z @ b) > 0
            if np.array_equal(A2, A):
                break
            A = A2
        if b is None:
            continue
        sse = float(np.sum((np.maximum(0.0, Z @ b) - y) ** 2))
        if best is None or sse < best[0]:
            best = (sse, b)
    return best


def _bic(sse: float, k: int, n: int, floor: float) -> float:
    return n * math.log(max(sse, floor) / n) + k * math.log(n)


def fit_side(y: np.ndarray, cols: dict, n: int, floor: float, base: np.ndarray | None = None) -> dict | None:
    """The best floored linear rate for y (the side's amount per step, n): the column set (at most
    MAX_COLS, with or without a constant) with the lowest BIC of (y - fit) + base residual... base: the
    rest of the row's error that this side cannot change (added to the SSE). Returns {"c", "w", "sse", "k"}."""
    names = [k for k, v in cols.items() if np.std(v[:n]) > 0]
    best = None
    for size in range(1, MAX_COLS + 1):
        for s in itertools.combinations(names, size):
            M = np.column_stack([cols[k][:n] for k in s])
            for const in (False, True):
                Z = np.column_stack([M, np.ones(n)]) if const else M
                got = hfit(Z, y)
                if got is None:
                    continue
                sse, b = got
                if np.mean(Z @ b <= 0) < MIN_OFF:
                    continue
                k = Z.shape[1]
                bic = _bic(sse, k, n, floor)
                if best is None or bic < best["bic"] - 1e-9:
                    best = {"bic": bic, "sse": sse, "k": k, "c": float(b[-1]) if const else 0.0,
                            "w": {nm: float(v) for nm, v in zip(s, b[:len(s)])}}
    return best


def _rate(side: dict) -> dict:
    return {"form": "linear", "c": side["c"], "terms": [{"stock": k, "k": v} for k, v in side["w"].items()]}


class Levels(dict):
    """The measured levels, with each stock's announced injections per step (`inj`: added before the step's
    flows, as the engine does), so a row is the change the flows made: delta()."""
    inj: dict = {}


def delta(levels: dict, x: str, n: int) -> np.ndarray:
    """X's one-step changes less its announced injections."""
    d = np.diff(levels[x][:n + 1])
    j = getattr(levels, "inj", {}).get(x)
    return d - j[:n] if j is not None else d


def columns(run: dict, opts: dict | None, readable=None) -> tuple[dict, dict, int]:
    """(levels, cols, n): cols read at each step's start (an input during the step, the engine's convention).
    (2026-10-22, k8s-311) An announced injection is added to the level its step's rates read, and taken off
    that step's change (levels.inj, delta()): before, a node failure's 3 pods moved ready -> pending were
    read as flow."""
    levels = Levels({k: np.asarray(v, dtype=float) for k, v in (run.get("levels") or {}).items()})
    if not levels:
        return levels, {}, 0
    T = min(len(v) for v in levels.values())
    n = T - 1
    cols = {k: v[:n].copy() for k, v in levels.items()}
    t = np.asarray(run.get("t") or [], dtype=float)
    inj = {}
    if len(t) >= T:
        at = {float(x): k for k, x in enumerate(t[1:T])}
        for j in (opts or {}).get("injections") or []:
            k, x = at.get(float(j.get("t", -1e300))), j.get("stock")
            if k is not None and x in levels:
                inj.setdefault(x, np.zeros(n))[k] += float(j["amount"])
                cols[x][k] = max(0.0, cols[x][k] + float(j["amount"]))
    levels.inj = inj
    for k, v in ((opts or {}).get("inputs") or {}).items():
        a = np.asarray(v, dtype=float)
        if k not in cols and len(a) >= T and (readable is None or readable(k)):
            cols[k] = a[1:T]
    return levels, cols, n


_EXPR_FN = {"min": np.minimum, "max": np.maximum}


def expr_amount(expr, cols: dict, n: int) -> np.ndarray | None:
    """An expression rate's value per step on the columns (numbers, names, + - * /, unary minus, min, max of
    two or more), not yet floored; None for anything else (a comparison, ceil, a name not measured)."""
    import ast

    if not isinstance(expr, str):
        return None
    try:
        tree = ast.parse(expr, mode="eval").body
    except SyntaxError:
        return None

    def ev(e):
        if isinstance(e, ast.Constant) and isinstance(e.value, (int, float)):
            return np.full(n, float(e.value))
        if isinstance(e, ast.Name):
            if e.id not in cols:
                raise KeyError(e.id)
            return np.asarray(cols[e.id][:n], dtype=float)
        if isinstance(e, ast.UnaryOp) and isinstance(e.op, ast.USub):
            return -ev(e.operand)
        if isinstance(e, ast.BinOp) and isinstance(e.op, (ast.Add, ast.Sub, ast.Mult, ast.Div)):
            a, b = ev(e.left), ev(e.right)
            if isinstance(e.op, ast.Add):
                return a + b
            if isinstance(e.op, ast.Sub):
                return a - b
            if isinstance(e.op, ast.Mult):
                return a * b
            return a / np.where(b == 0, np.inf, b)
        if isinstance(e, ast.Call) and isinstance(e.func, ast.Name) and e.func.id in _EXPR_FN and len(e.args) >= 2 \
                and not e.keywords:
            out = ev(e.args[0])
            for a in e.args[1:]:
                out = _EXPR_FN[e.func.id](out, ev(a))
            return out
        raise ValueError(type(e).__name__)

    try:
        return ev(tree)
    except (KeyError, ValueError):
        return None


def row_error(x: str, flows: list[dict], levels: dict, cols: dict, n: int) -> tuple[np.ndarray, dict] | None:
    """X's row: (residual after its inner flows, {"in": amounts, "out": amounts} of its outside flows), None
    where a flow touching X cannot be evaluated."""
    r = delta(levels, x, n)
    sides = {"in": np.zeros(n), "out": np.zeros(n)}
    for f in flows:
        a, b = f.get("from"), f.get("to")
        if x not in (a, b):
            continue
        amt = amount(f, cols, n)
        if amt is None:
            return None
        if a and b:
            r = r - (-amt * float(f.get("ratio") or 1) if a == x else amt)
        elif b == x:
            sides["in"] += amt
        else:
            sides["out"] += amt
    return r, sides


def refit_row(x: str, flows: list[dict], levels: dict, cols: dict, n: int, allowed: set, force: bool = False) -> tuple[list[dict], dict] | None:
    """X's flows with one outside side (of `allowed`) refitted as a floored linear rate where that lowers X's
    row's BIC by more than GAIN log n (force: whenever it lowers it at all). (new flows, note) or None."""
    got = row_error(x, flows, levels, cols, n)
    if got is None:
        return None
    r, sides = got
    scale = max(1e-12, float(np.abs(delta(levels, x, n)).max()))
    floor = n * (FLOOR_REL * scale) ** 2
    k_old = {s: sum(_k(f) for f in flows if _side(f, x) == s) for s in ("in", "out")}
    sse_old = float(np.sum((r - sides["in"] + sides["out"]) ** 2))
    bic_old = _bic(sse_old, k_old["in"] + k_old["out"], n, floor)
    best = None
    for s, sign in (("in", 1.0), ("out", -1.0)):
        if s not in allowed:
            continue
        other = sides["out"] if s == "in" else sides["in"]
        y = sign * (r + (other if s == "in" else -other))          # what this side must carry
        fit = fit_side(y, cols, n, floor)
        if fit is None:
            continue
        k = fit["k"] + k_old["out" if s == "in" else "in"]
        bic = _bic(fit["sse"], k, n, floor)
        if best is None or bic < best[0]:
            best = (bic, s, fit)
    if best is None:
        return None
    bic, s, fit = best
    if not (bic < bic_old - (0.0 if force else GAIN * math.log(n))):
        return None
    keep = [f for f in flows if _side(f, x) != s]
    fl = {"from": None, "to": x} if s == "in" else {"from": x, "to": None}
    new = {**fl, "id": f"floored_{x}_{s}", "ratio": 1, "rate": _rate(fit)}
    return keep + [new], {"stock": x, "side": s, "sse_before": sse_old, "sse_after": fit["sse"], "bic_before": bic_old, "bic_after": bic}


def _side(f: dict, x: str) -> str | None:
    if f.get("from") and f.get("to"):
        return None
    if f.get("to") == x and not f.get("from"):
        return "in"
    if f.get("from") == x and not f.get("to"):
        return "out"
    return None


def _k(f: dict) -> int:
    lf = _linear(f.get("rate") or {})
    if lf is None:
        return 2
    return len(lf[1]) + (1 if lf[0] else 0)


def allowed_sides(x: str, run: dict, flows: list[dict]) -> set:
    """The sides X may have: its declared ones where a boundary is declared, else those it already has."""
    if run.get("boundary_declared"):
        b = (run.get("boundary") or {}).get(x) or {}
        # (2026-10-22, k8s-310 r2) a side declared only "input" is exactly 1 x the input (boundary.enforce_sides):
        # never refitted here (310 none-short: queue's inflow had become 0.89 x traffic - 0.56 x queue)
        return {s for s in ("in", "out") if b.get(s) and any(k != "input" for k in b.get(s))}
    return {s for f in flows for s in [_side(f, x)] if s}


def apply(result: dict, stocks: list[dict], run: dict, opts: dict | None = None, readable=None) -> dict:
    """The answer with each stock's outside sides refitted as floored linear rates where X's row says so."""
    if not isinstance(result, dict) or not result.get("flows"):
        return result
    levels, cols, n = columns(run, opts, readable)
    if n < 10:
        return result
    finals = {s["id"] for s in stocks if s.get("final")}
    out = copy.deepcopy(result)
    flows = out["flows"]
    notes = []
    for x in levels:
        if x in finals or any(f.get("switch") and x in (f.get("from"), f.get("to")) for f in flows):
            continue
        if any(x in (f.get("from"), f.get("to")) and (f.get("from") not in levels and f.get("from")) for f in flows) or \
           any(x in (f.get("from"), f.get("to")) and (f.get("to") not in levels and f.get("to")) for f in flows):
            continue                                       # X's hidden stocks: what they carry is not known here
        have = {s for f in flows for s in [_side(f, x)] if s}      # a side refitted, never one invented
        got = refit_row(x, flows, levels, cols, n, allowed_sides(x, run, flows) & have)
        if got is None:
            continue
        flows[:], note = got
        notes.append(note)
    if notes:
        out["floored"] = notes
    return out
