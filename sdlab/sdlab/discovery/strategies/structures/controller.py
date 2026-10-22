"""A stock that a discrete controller sets (k8s 308, 2026-10-21, docs/research/fixes/308-structures.md).

A stock whose level is a whole number at every step and moves by whole numbers (pods, replicas, nodes) is
set by a rule, not by a rate: an autoscaler or a reconciler compares it with a target read from another
measured series and closes the gap. Linear rates fit such a stock badly (a drift of 0.003 x inflight in
place of jumps to a target). This module offers one family of controller forms for every such stock,
whatever it stands for, and keeps one only when it reproduces every step's change exactly:

- the target: T = ceil(x / a), x any other measured stock or input (a link: it may cross units),
  a > 0, optionally clamped to a ceiling H (the inflow) or a floor L (the outflow);
- the inflow: the whole gap, max(0, min(H, T) - s), or one unit, 1 * (s < min(H, T));
- the outflow: the whole gap, max(0, s - max(L, T)), or one unit, 1 * (s > max(L, T)).

Each step is a constraint on T (T = m, T >= m or T <= m, whole numbers), so a's consistent values are
one interval: a >= x / m for T <= m, a < x / (m - 1) for T >= m. A form is kept when the interval is not
empty over every step. Order of preference (fewer numbers first, then the whole gap, the canonical SD
goal gap with a one-step time, before one unit): no clamp before a clamp; among drivers, the narrowest
interval (the series that pins the target best). The clamp, where one is needed, is the most extreme
level the data reached (H: the highest level an inflow reached, L: the lowest an outflow reached).
a is written as the number with fewest significant digits inside its interval.

The stock's fitted outside flows are replaced only when both its sides are explained (a side with no
movement is explained by no flow); a declared boundary (run["boundary"]) must have the side the form uses.
Since 2026-10-22 (k8s 310) its moves with other stocks go too: the form reproduces the stock's whole change
alone, so a move on it is spurious.
"""

from __future__ import annotations

import math

import numpy as np

TOL = 1e-9


MOVE_EVIDENCE = 10   # steps of change a stock with moves needs before its controller form replaces them


def _whole(v: np.ndarray) -> bool:
    return bool(np.all(np.isfinite(v))) and bool(np.all(np.abs(v - np.round(v)) <= TOL * np.maximum(1.0, np.abs(v))))


def _interval(x: np.ndarray, eq: np.ndarray, ge: np.ndarray, le: np.ndarray) -> tuple[float, float] | None:
    """a's interval [lo, hi) such that ceil(x / a) = eq where eq is set, >= ge where set, <= le where set
    (NaN: no constraint of that kind on that step). None when empty or x is not positive where it is read."""
    lo, hi = 0.0, math.inf
    for m, kind in ((eq, "eq"), (ge, "ge"), (le, "le")):
        sel = ~np.isnan(m)
        if not sel.any():
            continue
        xs, ms = x[sel], m[sel]
        if np.any(xs <= 0):
            return None
        if kind in ("eq", "le"):                           # T <= m  <=>  a >= x / m  (m >= 1)
            if np.any(ms < 1):
                return None
            lo = max(lo, float(np.max(xs / ms)))
        if kind in ("eq", "ge"):                           # T >= m  <=>  a < x / (m - 1)  (always when m <= 1)
            big = ms > 1
            if big.any():
                hi = min(hi, float(np.min(xs[big] / (ms[big] - 1))))
    if not lo < hi * (1 - 1e-12) or not math.isfinite(lo) or lo <= 0:
        return None
    return lo, hi


def _simple(lo: float, hi: float) -> float:
    """The number with fewest significant digits in [lo, hi) (nearest the middle among those)."""
    if not math.isfinite(hi):
        hi = 2 * lo
    mid = 0.5 * (lo + hi)
    for digits in range(1, 16):
        q = 10 ** (math.floor(math.log10(mid)) - digits + 1)
        c = [float(f"{k * q:.{digits}g}") for k in range(math.ceil(lo / q), math.floor(hi / q) + 1)]
        c = [v for v in c if lo <= v < hi]
        if c:
            return min(c, key=lambda v: abs(v - mid))
    return mid


def _constraints(form: str, side: str, s: np.ndarray, amt: np.ndarray, clamp: float | None):
    """(eq, ge, le) on T for each step, or None when a step cannot be met whatever a is."""
    n = len(s)
    eq, ge, le = (np.full(n, np.nan) for _ in range(3))
    if side == "in":
        H = math.inf if clamp is None else clamp
        for i in range(n):
            u, si = amt[i], s[i]
            if form == "gap":
                if u > 0:
                    if si + u < H:
                        eq[i] = si + u
                    elif si + u == H:
                        ge[i] = H
                    else:
                        return None
                elif si < H:
                    le[i] = si
            else:
                if u > 1:
                    return None
                if u == 1:
                    if not si < H:
                        return None
                    ge[i] = si + 1
                elif si < H:
                    le[i] = si
    else:
        L = -math.inf if clamp is None else clamp
        for i in range(n):
            d, si = amt[i], s[i]
            if form == "gap":
                if d > 0:
                    if si - d > L:
                        eq[i] = si - d
                    elif si - d == L:
                        le[i] = L
                    else:
                        return None
                elif L < si:
                    ge[i] = si
            else:
                if d > 1:
                    return None
                if d == 1:
                    if not L < si:
                        return None
                    le[i] = si - 1
                elif L < si:
                    ge[i] = si
    return eq, ge, le


def _side(side: str, s: np.ndarray, amt: np.ndarray, drivers: dict[str, np.ndarray]) -> dict | None:
    """The preferred controller form for one side of the stock, or None."""
    moved = amt > 0
    if side == "in":
        extreme = float(np.max((s + amt)[moved])) if moved.any() else None
    else:
        extreme = float(np.min((s - amt)[moved])) if moved.any() else None
    for clamp in (None, extreme):
        best = None
        for form in ("gap", "unit"):
            c = None
            if side == "out" and form == "unit" and clamp is not None:
                clamp_used = float(np.min((s - 1)[moved]))
            elif side == "in" and form == "unit" and clamp is not None:
                clamp_used = float(np.max((s + 1)[moved]))
            else:
                clamp_used = clamp
            c = _constraints(form, side, s, amt, clamp_used)
            if c is None:
                continue
            for name, x in drivers.items():
                iv = _interval(x, *c)
                if iv is None:
                    continue
                width = math.log(iv[1] / iv[0]) if math.isfinite(iv[1]) else math.inf
                if best is None or width < best["width"]:
                    best = {"form": form, "driver": name, "a": _simple(*iv), "clamp": clamp_used, "width": width}
            if best is not None:
                return best
    return None


def _expr(side: str, stock: str, f: dict) -> str:
    T = f"ceil({f['driver']} / {f['a']:.15g})"
    if side == "in":
        T = T if f["clamp"] is None else f"min({f['clamp']:g}, {T})"
        return f"max(0, {T} - {stock})" if f["form"] == "gap" else f"1 * ({stock} < {T})"
    T = T if f["clamp"] is None else f"max({f['clamp']:g}, {T})"
    return f"max(0, {stock} - {T})" if f["form"] == "gap" else f"1 * ({stock} > {T})"


def _amounts(side: str, s: np.ndarray, X: np.ndarray, f: dict) -> np.ndarray:
    T = np.ceil(X / f["a"])
    if side == "in":
        T = T if f["clamp"] is None else np.minimum(f["clamp"], T)
        return np.maximum(0, T - s) if f["form"] == "gap" else 1.0 * (s < T)
    T = T if f["clamp"] is None else np.maximum(f["clamp"], T)
    return np.maximum(0, s - T) if f["form"] == "gap" else 1.0 * (s > T)


def apply(result: dict, stocks: list[dict], run: dict, opts: dict | None) -> dict:
    """The answer with each controller-set stock's outside flows replaced by its controller form."""
    if not isinstance(result, dict) or not result.get("flows"):
        return result
    levels = {k: np.asarray(v, dtype=float) for k, v in (run.get("levels") or {}).items()}
    inputs = {k: np.asarray(v, dtype=float) for k, v in ((opts or {}).get("inputs") or {}).items()}
    # (k8s 311, docs/research/fixes/311-structures.md) announced injections: each stock's change less what was
    # injected, and every level read at the step's start with that step's injection in (the engine adds an
    # injection before the step's flows); before 311 any injection turned the module off for every stock
    t = np.asarray(run.get("t") or [], dtype=float)
    inj = {}
    for j in (opts or {}).get("injections") or []:
        k = np.nonzero(t == float(j["t"]))[0]
        if j.get("stock") in levels and len(k) and k[0] >= 1:
            inj.setdefault(j["stock"], np.zeros(len(t)))[k[0] - 1] += float(j["amount"])
    declared = bool(run.get("boundary_declared"))
    bound = run.get("boundary") or {}
    flows = list(result["flows"])
    notes = []
    for st in stocks:
        sid = st.get("id")
        L = levels.get(sid)
        if L is None or len(L) < 3 or not _whole(L):
            continue
        d = np.diff(L) - (inj[sid][: len(L) - 1] if sid in inj else 0.0)
        if not np.any(d != 0):
            continue
        s = L[:-1] + (inj[sid][: len(L) - 1] if sid in inj else 0.0)
        mine = [f for f in flows if sid in (f.get("from"), f.get("to"))]
        # (k8s 310, 2026-10-22) a move with another stock no longer rules the stock out: the form must reproduce
        # the stock's whole change on every step by itself, so where it does the moves are spurious (310
        # none-long: `desired -> ready` and `ready -> desired` beside the HPA) and go with its fitted flows;
        # the other stock's row is left to the repair after (repair.py). That takes MOVE_EVIDENCE steps of
        # change at least: on a few steps some form always fits
        if any(f.get("from") and f.get("to") for f in mine) and int(np.sum(d != 0)) < MOVE_EVIDENCE:
            continue
        drivers = {k: v[:-1] + (inj[k][: len(L) - 1] if k in inj else 0.0) for k, v in {**levels, **inputs}.items()
                   if k != sid and len(v) == len(L)}
        up, dn = np.maximum(d, 0), np.maximum(-d, 0)
        sides = {}
        ok = True
        for side, amt in (("in", up), ("out", dn)):
            if not np.any(amt > 0):
                continue
            if declared and not (bound.get(sid) or {}).get(side):
                ok = False
                break
            f = _side(side, s, amt, drivers)
            if f is None or not np.allclose(_amounts(side, s, drivers[f["driver"]], f), amt):
                ok = False
                break
            sides[side] = f
        if not ok or not sides:
            continue
        flows = [f for f in flows if f not in mine]
        for side, f in sides.items():
            rate = {"form": "expr", "expr": _expr(side, sid, f)}
            flows.append({"id": f"controller_{sid}_{side}", "from": None if side == "in" else sid, "to": sid if side == "in" else None,
                          "ratio": 1, "rate": rate, "rates": [rate], "controller": {k: f[k] for k in ("form", "driver", "a", "clamp")}})
        notes.append({"stock": sid, **{side: _expr(side, sid, f) for side, f in sides.items()}})
    if not notes:
        return result
    return {**result, "flows": flows, "controller": notes}
