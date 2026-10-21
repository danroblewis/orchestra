"""A discrete actuator: a stock moved in whole steps by a switch on the levels (docs/research/fixes/308-combined2.md,
2026-10-21).

A controller that adds or removes whole units (pods, nodes, machines) when a reading crosses a threshold
changes its stock by a fixed step on some steps and by nothing on the rest. A linear rate cannot write that:
the fit smears it into a small drift (0.06 + 0.005 x inflight a step for a stock that jumps by 1 on 7% of
the steps), and the rest of the model is right. Here, for each measured stock X whose one-step changes left
after the model's flows between X and other stocks are exactly 0 on most steps and +s or -s on the others
(one step size per side), each side is fitted as a switch,

    s x ((c + w_X x X + w_Y x Y) > 0)

on X and at most one other measured stock or input Y: the steps that moved that way against the steps that
did not are separated by a line in (X, Y), found by an L1 support-vector linear program on standardised
columns (fewest misclassified steps, then fewest columns, then the widest margin; the threshold sits in the
middle of the margin). A side is written as a switch only where the separation is clean (at most MISS of its
steps misclassified) and leaves at most RESIDUAL of the outside flows' squared error on X's row; the outside
flows it replaces are removed (one flow per side). The rule reads only the levels: nothing reads the case.

A controller's own law (`max(0, min(16, ceil(cpu / 192.5)) - ready)`, `ready > max(3, ceil(cpu / 157.5))`)
is, on whole-unit levels and moves of one unit, the half-plane `cpu > 192.5 ready` (`cpu <= 157.5 (ready -
1)`), which is what this finds; the ceilings and floors that never bind in the record are not written.

Adopting it: copy this file into the strategy's package (identical copies) and call `apply(result, stocks,
run, opts)` on the strategy's final answer (after any write-back of offered series such as capmin's).
"""

from __future__ import annotations

import copy

import numpy as np

MIN_EVENTS = 3        # steps a side must move on to be fitted as a switch
MAX_SHARE = 0.5       # a stock that moves on more than this share of the steps is not switched
STEP_REL = 1e-6       # every move on a side equals its step within this (relative)
MISS = 0.02           # misclassified steps allowed, as a share of the steps
RESIDUAL = 0.25       # the switch's squared error on X's row at most this share of the outside flows'
C_SLACK = 1e4         # the soft LP's price on a step on the wrong side against the weights' L1 norm


def _linear(rate: dict) -> tuple[float, dict] | None:
    """A rate as (constant, {column: k}), None when it is not linear."""
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


def _amount(f: dict, cols: dict, n: int) -> np.ndarray | None:
    """A linear flow's amount per step on the record's states (floored at 0 as the engine does)."""
    if f.get("byTime") or f.get("effects") or f.get("uses") or f.get("two_way") or f.get("via"):
        return None
    lf = _linear(f.get("rate") or {})
    if lf is None or any(j not in cols for j in lf[1]):
        return None
    c, ks = lf
    r = np.full(n, c, dtype=float)
    for j, k in ks.items():
        r = r + k * cols[j][:n]
    return np.maximum(0.0, r)


def _separate(Z: np.ndarray, y: np.ndarray) -> tuple[int, float, np.ndarray, float] | None:
    """A linear separator of y (+1 / -1) by the columns of Z (steps x m, standardised): (misclassified
    steps, margin, w, c) with w.z + c > 0 for the +1 class. First the widest margin with |w|_1 <= 1 (a
    linear program); where no line separates the classes, an L1 soft margin that prices each step on the
    wrong side at C_SLACK. None when the LP fails."""
    from scipy.optimize import linprog

    n, m = Z.shape
    # hard margin: variables w+ (m), w- (m), c (free), t; maximise t s.t. y (w.z + c) >= t, sum(w+ + w-) <= 1
    A = np.zeros((n + 1, 2 * m + 2))
    A[:n, :m] = -y[:, None] * Z
    A[:n, m:2 * m] = y[:, None] * Z
    A[:n, 2 * m] = -y
    A[:n, 2 * m + 1] = 1.0
    A[n, :2 * m] = 1.0
    b = np.concatenate([np.zeros(n), [1.0]])
    cost = np.zeros(2 * m + 2)
    cost[-1] = -1.0
    try:
        res = linprog(cost, A_ub=A, b_ub=b, bounds=[(0, None)] * (2 * m) + [(None, None), (None, 1.0)], method="highs")
    except Exception:                                    # noqa: BLE001
        return None
    if res.status == 0 and res.x[-1] > 1e-9:
        x = res.x
        return 0, float(x[-1]), x[:m] - x[m:2 * m], float(x[2 * m])
    # soft margin: variables w+ (m), w- (m), c+, c-, xi (n); minimise sum(w+ + w-) + C sum(xi)
    cost = np.concatenate([np.ones(2 * m), [0.0, 0.0], C_SLACK * np.ones(n)])
    A = np.zeros((n, 2 * m + 2 + n))
    A[:, :m] = -y[:, None] * Z
    A[:, m:2 * m] = y[:, None] * Z
    A[:, 2 * m] = -y
    A[:, 2 * m + 1] = y
    A[np.arange(n), 2 * m + 2 + np.arange(n)] = -1.0
    try:
        res = linprog(cost, A_ub=A, b_ub=-np.ones(n), bounds=[(0, None)] * (2 * m + 2 + n), method="highs")
    except Exception:                                    # noqa: BLE001
        return None
    if res.status != 0:
        return None
    x = res.x
    w = x[:m] - x[m:2 * m]
    c = float(x[2 * m] - x[2 * m + 1])
    s = Z @ w + c
    miss = int(np.sum(np.where(y > 0, s <= 0, s > 0)))
    return miss, 0.0, w, c


def _half_plane(moved: np.ndarray, x: str, cols: dict, rows: np.ndarray) -> tuple | None:
    """The best half-plane for the steps `moved` among `rows` (bool masks): (misses, columns, -margin,
    {col: w}, c) in raw units, on X alone, one other column alone, or X and one other column."""
    y = np.where(moved[rows], 1.0, -1.0)
    names = [k for k in cols if k != x]
    sets = [[x]] + [[k] for k in names] + [[x, k] for k in names]
    best = None
    for s in sets:
        Xr = np.column_stack([cols[k][rows] for k in s])
        mu, sd = Xr.mean(axis=0), Xr.std(axis=0)
        if np.any(sd <= 0):
            continue
        got = _separate((Xr - mu) / sd, y)
        if got is None:
            continue
        miss, margin, w, c = got
        wr = w / sd
        cr = c - float(np.sum(w * mu / sd))
        key = (miss, len(s), -margin)
        if best is None or key < best[:3]:
            best = (miss, len(s), -margin, {k: float(v) for k, v in zip(s, wr) if v != 0}, cr)
    return best


def _fit_side(moved: np.ndarray, x: str, cols: dict, n: int) -> dict | None:
    """The best switch for the steps `moved` (bool, n): a half-plane, alone or within the range of X's
    own level the moves happened in (an actuator's ceiling or floor: no move this way above the highest
    level it moved from, or below the lowest; the bound halfway to the next level seen). Returns
    {"misses", "w", "c", "lo", "hi"} (lo / hi None where no bound is written)."""
    X = cols[x][:n]
    every = np.ones(n, dtype=bool)
    plain = _half_plane(moved, x, cols, every)
    out = None if plain is None else {"misses": plain[0], "w": plain[3], "c": plain[4], "lo": None, "hi": None}
    if out is None or out["misses"] == 0:
        return out
    top, bot = float(X[moved].max()), float(X[moved].min())
    above, below = X[X > top], X[X < bot]
    hi = 0.5 * (top + float(above.min())) if above.size else None
    lo = 0.5 * (bot + float(below.max())) if below.size else None
    if hi is None and lo is None:
        return out
    rows = every & (X < (hi if hi is not None else np.inf)) & (X > (lo if lo is not None else -np.inf))
    if rows.sum() < 2 or rows.all():
        return out
    got = _half_plane(moved, x, cols, rows)
    if got is None or got[0] >= out["misses"]:
        return out
    return {"misses": got[0], "w": got[3], "c": got[4],
            "lo": lo if lo is not None and (X <= lo).any() else None, "hi": hi if hi is not None and (X >= hi).any() else None}


def _on(sw: dict, x: str, cols: dict, n: int) -> np.ndarray:
    """Where the switch is on, step by step."""
    lin = sw["c"] + sum(v * cols[k][:n] for k, v in sw["w"].items())
    on = lin > 0
    if sw.get("hi") is not None:
        on &= cols[x][:n] < sw["hi"]
    if sw.get("lo") is not None:
        on &= cols[x][:n] > sw["lo"]
    return on


def _expr(step: float, sw: dict, x: str) -> dict:
    lin = " + ".join([repr(sw["c"])] + [f"{v!r} * {k}" for k, v in sw["w"].items()])
    conds = [f"(({lin}) > 0)"]
    if sw.get("hi") is not None:
        conds.append(f"({x} < {sw['hi']!r})")
    if sw.get("lo") is not None:
        conds.append(f"({x} > {sw['lo']!r})")
    return {"form": "expr", "expr": f"{step!r} * " + " * ".join(conds)}


def apply(result: dict, stocks: list[dict], run: dict, opts: dict | None = None) -> dict:
    """The answer with each discrete actuator's outside flows written as switches (see the docstring)."""
    if not isinstance(result, dict) or not result.get("flows"):
        return result
    levels = {k: np.asarray(v, dtype=float) for k, v in (run.get("levels") or {}).items()}
    if not levels:
        return result
    T = min(len(v) for v in levels.values())
    n = T - 1
    if n < 10:
        return result
    cols = {k: v[:n] for k, v in levels.items()}             # each step reads the levels at its start
    for k, v in ((opts or {}).get("inputs") or {}).items():
        a = np.asarray(v, dtype=float)
        if k not in cols and len(a) >= T:
            cols[k] = a[1:T]                                  # and an input's value during the step (the engine's convention)
    finals = {s["id"] for s in stocks if s.get("final")}
    boundary = run.get("boundary") if run.get("boundary_declared") else None
    out = copy.deepcopy(result)
    flows = out["flows"]
    notes = []
    for x in levels:
        if x in finals:
            continue
        d = np.diff(levels[x][:T])
        inner = [f for f in flows if f.get("from") and f.get("to") and x in (f["from"], f["to"])]
        rest = np.zeros(n)
        ok = True
        for f in inner:
            a = _amount(f, cols, n)
            if a is None:
                ok = False
                break
            rest += (a if f["to"] == x else -a * float(f.get("ratio") or 1))
        if not ok:
            continue
        r = d - rest
        scale = max(1e-12, float(np.abs(r).max()))
        moved = np.abs(r) > STEP_REL * scale
        if moved.sum() < MIN_EVENTS or moved.mean() > MAX_SHARE:
            continue
        outer = [f for f in flows if bool(f.get("from")) != bool(f.get("to")) and x in (f.get("from"), f.get("to"))]
        old = np.zeros(n)
        for f in outer:
            a = _amount(f, cols, n)
            if a is None:
                ok = False
                break
            old += a if f.get("to") == x else -a
        if not ok:
            continue
        new_flows, new = [], np.zeros(n)
        sides = []
        for side, sign in (("in", 1.0), ("out", -1.0)):
            ev = moved & (sign * r > 0)
            if boundary is not None and not (boundary.get(x) or {}).get(side):
                if ev.any():
                    sides = None
                    break
                continue
            if ev.sum() < MIN_EVENTS:
                if ev.any():
                    sides = None
                    break
                continue
            step = float(np.median(sign * r[ev]))
            if np.max(np.abs(sign * r[ev] - step)) > STEP_REL * max(1.0, abs(step)):
                sides = None
                break
            got = _fit_side(ev, x, cols, n)
            if got is None or got["misses"] > MISS * n:
                sides = None
                break
            new += sign * step * _on(got, x, cols, n)
            sides.append(side)
            fl = {"from": None, "to": x} if side == "in" else {"from": x, "to": None}
            new_flows.append({**fl, "id": f"switch_{x}_{side}", "ratio": 1, "rate": _expr(step, got, x),
                              "switch": {"step": step, **got}})
        if not sides:
            continue
        err_new = float(np.sum((r - new) ** 2))
        err_old = float(np.sum((r - old) ** 2))
        if err_new > RESIDUAL * err_old:
            continue
        keep = [f for f in flows if not (f in outer and (("in" if f.get("to") == x else "out") in sides))]
        flows[:] = keep + new_flows
        notes.append({"stock": x, "sides": sides, "sse_before": err_old, "sse_after": err_new})
    if notes:
        out["switch"] = notes
    return out
