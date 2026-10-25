# (port-matrix_v2, 2026-10-22) copied from kalman_lna/tracker.py at 9d3ca8e (strategies are isolated, CLAUDE.md rule 11);
# docs/research/fixes/port-matrix_v2.md. Changes to this copy are marked 'matrix_v2'.
"""A stock that tracks a target read off another stock (a controller; kubernetes 308, 2026-10-21).

docs/research/fixes/308-kalman_lna.md. A controller (an autoscaler, a thermostat with a dead band, a
reorder rule) moves a counted stock S towards a target set by another measured stock or input X: the
target is a whole number of units, T = ceil(X / a), held between a floor and a cap. On each of S's
outside sides (an inflow from outside rises towards the target, an outflow to outside falls towards
it) the controller acts in one of two ways:
- the gap:  rise max(0, min(H, T) - S), fall max(0, S - max(L, T)) (all at once);
- a step:   rise d x (S < min(H, T)),   fall d x (S > max(L, T))     (d a step while it is off).
A linear row can only draw a proxy for this (a drift of S, or links to whatever X moves with), so the
rest of the model compensates and the flows' amounts are wrong.

`revise` runs after the strategy's answer. For every measured, non-final stock with an outside side
(where a boundary is declared: only its estimated sides), the outside net flow is read off the data
(S's one-step change, less announced injections and the answer's flows between S and other measured
stocks). Each side's form (gap or step), reader X (every other measured non-final stock, every measured
input) and threshold a are searched exactly: the predicted amounts change only where a crosses some
X_t / m (m a whole number near S_t), so every interval between those breakpoints is tried and the
middle of the best one is kept; the cap H and floor L are tried at the extreme levels S reached, and
kept only when they pay for themselves. The tracker replaces S's outside flows only where it explains
EXPLAINED of the outside net's squares (a rule, not a trend) and beats
them by Gaussian BIC with a margin of PRICE x log T. The same rule for every case; nothing reads the
case or its truth.

To adopt it in another strategy: copy this file into the package and call
`result = tracker.revise(result, stocks, run, opts)` on the strategy's final answer (after any MIN or
other expression is written back). It needs nothing else from the package.
"""

from __future__ import annotations

import copy
import math
import time

import numpy as np

PRICE = 6.0            # the margin the tracker must win by, in log T (as capmin's)
RESOLUTION = 1e-8      # a residual variance below this share of the mean squared change is rounding
CHUNK = 256            # thresholds tried at once
MOST = 6000            # at most this many breakpoints per reader (thinned evenly beyond)
MIN_FIRES = 3          # a side must act on at least this many steps to be read as a controller
TIME = 20.0            # seconds for the whole search (the stocks with the worst-fitted outside nets first)
EXPLAINED = 0.9        # a controller acts by a rule: it must explain this share of the outside net's squares


def _rate_value(rate: dict, state: dict) -> float | None:
    form = (rate or {}).get("form")
    if form == "proportional":
        return float(rate.get("k") or 0.0) * state.get(rate.get("stock"), 0.0)
    if form == "linear":
        return float(rate.get("c") or 0.0) + sum(float(t.get("k") or 0.0) * state.get(t.get("stock"), 0.0)
                                                 for t in rate.get("terms") or [])
    if form == "constant":                                   # (matrix_v2) the matrix writes a constant as "value"
        return float(rate.get("value", rate.get("c", rate.get("k", 0.0))) or 0.0)
    if form == "expr":
        try:
            return float(eval(rate["expr"], {"__builtins__": {}}, {"min": min, "max": max, "ceil": math.ceil,
                                                                 "abs": abs, **state}))
        except Exception:                                  # noqa: BLE001 (an expression this reader cannot run)
            return None
    return None


def _amounts(f: dict, states: list[dict]) -> np.ndarray | None:
    if f.get("byTime") or f.get("effects") or f.get("uses"):
        return None
    out = np.zeros(len(states))
    for i, s in enumerate(states):
        v = _rate_value(f.get("rate") or {}, s)
        if v is None:
            return None
        out[i] = max(0.0, v)
    return out


def _data(stocks: list[dict], run: dict, opts: dict):
    ids = [s["id"] for s in stocks]
    final = {s["id"] for s in stocks if s.get("final")}
    t = np.asarray(run["t"], dtype=float)
    L = np.array([np.asarray(run["levels"].get(i, []), dtype=float) for i in ids])
    if L.ndim != 2 or L.shape[1] < 20 or not np.isfinite(L).all() or np.any(np.diff(t) != 1):
        return None
    dy = L[:, 1:] - L[:, :-1]
    read = L[:, :-1].copy()
    T = dy.shape[1]
    at = {float(x): k for k, x in enumerate(t[1:])}
    index = {s: i for i, s in enumerate(ids)}
    for j in opts.get("injections") or []:
        k, i = at.get(float(j["t"])), index.get(j.get("stock"))
        if k is not None and i is not None:
            dy[i, k] -= float(j["amount"])
            read[i, k] = read[i, k] + float(j["amount"])
    inputs = {}
    for name, v in (opts.get("inputs") or {}).items():
        if name in index or str(name).startswith("capmin__"):
            continue
        u = np.nan_to_num(np.asarray(v, dtype=float))
        if len(u) >= T + 1:
            inputs[name] = u[1:T + 1]                       # an input is read at the step's end
    states = [{**{ids[i]: float(read[i, k]) for i in range(len(ids))}, **{n: float(u[k]) for n, u in inputs.items()}}
              for k in range(T)]
    return ids, final, dy, read, inputs, states


def _predict(side: str, form: str, S: np.ndarray, target: np.ndarray, d: float) -> np.ndarray:
    """Amounts per step (rows: thresholds) of one side's form, given the clamped target."""
    if side == "in":
        return np.maximum(0.0, target - S) if form == "gap" else d * (S < target)
    return np.maximum(0.0, S - target) if form == "gap" else d * (S > target)


def _breakpoints(X: np.ndarray, S: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Every threshold a at which ceil(X_t / a) crosses a whole number near S_t."""
    top = float(np.max(y)) if len(y) else 0.0
    if not np.isfinite(top) or top > MOST:
        return np.zeros(0)                                   # (matrix_v2) no whole-number controller moves this much a
                                                             # step (309 none-long: a runaway answer's net, an arange error)
    top = int(np.ceil(top)) + 2
    ms = np.arange(-2, top + 1)
    m = np.round(S)[:, None] + ms[None, :]
    with np.errstate(divide="ignore", invalid="ignore"):
        b = (X[:, None] / m).ravel()
    b = np.unique(b[np.isfinite(b) & (b > 0)])
    if len(b) > MOST:
        b = b[np.linspace(0, len(b) - 1, MOST).astype(int)]
    return b


def _fit_side(side: str, form: str, X: np.ndarray, S: np.ndarray, y: np.ndarray, clamp: float | None):
    """(sse, a, d) of the best threshold for this side, form, reader and clamp; None where none acts."""
    br = _breakpoints(X, S, y)
    if len(br) < 2:
        return None
    mids = np.sqrt(br[:-1] * br[1:])
    fired = y > 0
    d = float(np.median(y[fired])) if fired.any() else 0.0
    if d <= 0:
        return None
    sse = np.empty(len(mids))
    for lo in range(0, len(mids), CHUNK):
        a = mids[lo:lo + CHUNK]
        target = np.ceil(X[None, :] / a[:, None])
        if clamp is not None:
            target = np.minimum(clamp, target) if side == "in" else np.maximum(clamp, target)
        p = _predict(side, form, S[None, :], target, d)
        sse[lo:lo + CHUNK] = ((p - y[None, :]) ** 2).sum(axis=1)
    j = int(np.argmin(sse))
    best = sse[j]
    tie = 1e-9 * max(1.0, float(y @ y))
    i0 = j
    while i0 > 0 and sse[i0 - 1] <= best + tie:
        i0 -= 1
    i1 = j
    while i1 < len(sse) - 1 and sse[i1 + 1] <= best + tie:
        i1 += 1
    a = math.sqrt(br[i0] * br[i1 + 1])                       # the middle of the best interval
    if form == "step":                                       # d refitted on the steps it acts at a
        target = np.ceil(X / a)
        if clamp is not None:
            target = np.minimum(clamp, target) if side == "in" else np.maximum(clamp, target)
        on = _predict(side, "step", S, target, 1.0) > 0
        d = float(np.mean(y[on])) if on.any() else d
    return float(best), a, d


def _side(side: str, S: np.ndarray, y: np.ndarray, readers: list[tuple[str, np.ndarray]], floor: float,
          deadline: float = math.inf):
    """The best controller for one side: {form, reader, a, d, clamp, sse, numbers}; None where the side
    acts on fewer than MIN_FIRES steps."""
    if int((y > 0).sum()) < MIN_FIRES:
        return None
    if int((y <= 1e-9 * float(np.max(y))).sum()) < MIN_FIRES:
        return None                                          # (matrix_v2) a side that never rests is a flow, not a rule
                                                             # (004 none-long: A's constant inflow 20 as 20 x (A < ceil(B / a)))
    T = len(y)
    logT = math.log(T)
    clamps = [None, float(np.max(S + y)) if side == "in" else float(np.min(S - y))]
    best = None
    for name, X in readers:
        if np.ptp(X) <= 0 or np.any(X < 0) or time.monotonic() > deadline:
            continue
        for form in ("gap", "step"):
            for clamp in clamps:
                got = _fit_side(side, form, X, S, y, clamp)
                if got is None:
                    continue
                sse, a, d = got
                k = 1 + (form == "step") + (clamp is not None)
                score = T * math.log(sse + floor) + k * logT
                if best is None or score < best["score"] - 1e-9:
                    best = {"form": form, "reader": name, "a": a, "d": d, "clamp": clamp, "sse": sse, "numbers": k,
                            "score": score}
    return best


def _expr(side: str, c: dict, S: str) -> str:
    T = f"ceil({c['reader']} / {c['a']!r})"
    if c["clamp"] is not None:
        T = f"min({c['clamp']!r}, {T})" if side == "in" else f"max({c['clamp']!r}, {T})"
    if side == "in":
        return f"max(0, {T} - {S})" if c["form"] == "gap" else f"{c['d']!r} * ({S} < {T})"
    return f"max(0, {S} - {T})" if c["form"] == "gap" else f"{c['d']!r} * ({S} > {T})"


def _numbers(f: dict) -> int:
    r = f.get("rate") or {}
    if r.get("form") == "linear":
        return len(r.get("terms") or []) + (1 if r.get("c") else 0)
    if r.get("form") == "expr":
        return max(1, r.get("expr", "").count("."))
    return 1


def revise(result: dict, stocks: list[dict], run: dict, opts: dict | None) -> dict:
    """The answer with each counted stock's outside flows replaced by a tracker where one wins."""
    if not isinstance(result, dict) or not result.get("flows"):
        return result
    if result.get("lag") or result.get("scales") or (result.get("kalman") or {}).get("reading"):
        return result                                        # the answer reads the data in another frame
    opts = opts or {}
    got = _data(stocks, run, opts)
    if got is None:
        return result
    ids, final, dy, read, inputs, states = got
    T = dy.shape[1]
    logT = math.log(T)
    flows = list(result["flows"])
    # (matrix_v2) a stage the answer feeds S through (a found hidden stock H whose every flow is outside <-> H or
    # H <-> S, rows.py's delayed inflow) is part of S's outside side: H's levels (inferred_levels) are read like a
    # stock's, its flow into S counts as an outside flow, and replacing it removes the whole stage (308/309 none: the
    # rows drew the controller's stock as a delayed inflow and the controller came beside it, two inflows on one side)
    lv = result.get("inferred_levels") or {}
    stages: dict = {}
    for H, h in lv.items():
        if H in ids or len(h) < T:
            continue
        touching = [n for n, f in enumerate(flows) if H in (f.get("from"), f.get("to"))]
        ends = {e for n in touching for e in (flows[n].get("from"), flows[n].get("to"))} - {None, H}
        if len(ends) == 1 and next(iter(ends)) in ids:
            stages[H] = touching
            for k in range(T):
                states[k][H] = float(h[k])
    declared = bool(run.get("boundary_declared"))
    bd = run.get("boundary") or {}
    deadline = time.monotonic() + TIME
    todo = []
    for si, S in enumerate(ids):
        got = _stock(si, S, ids, final, dy, read, states, flows, declared, bd, stages)
        if got is not None:
            # (matrix_v2; fix ledger type 4, combined2 switch.py _try(drop=True) at 2a1db63) a stock that holds exactly
            # still on most steps cannot carry a smooth move: the same search with its moves to other measured stocks
            # left out of the inside flows (they join what the tracker replaces); the rows (rows.py) repair the
            # partners after (311 none-short: the matrix's desired -> pending at 0.0057 desired kept beside the
            # controller; pending's rebuilt row then had two flows on its one declared inflow)
            alt = _stock(si, S, ids, final, dy, read, states, flows, declared, bd, stages, drop_moves=True) \
                if _still(dy[si]) else None
            todo.append((got, alt) if alt is not None and alt["moved"] else (got,))
    todo.sort(key=lambda gs: -gs[0]["misfit"])              # the worst-fitted outside nets first
    changed, drop, added = [], set(), []
    for gs in todo:
        best = None
        for g in gs:
            got = _try(g, ids, final, read, inputs, states, flows, T, logT, deadline)
            # the moves are left out only where the tracker then fits S at most half as badly: what the partners
            # lose is not counted here, so a move goes only where S's rule shows it was not there
            if got is not None and (best is None or got[4] < 0.5 * best[4]):
                best = got
        if best is None:
            continue
        _, g, fits, sse_base, sse_new = best
        S, outside = g["S"], g["outside"]
        drop |= {n for s in fits for n in outside[s]} | set(g.get("moved") or [])
        drop |= {m for H, ns in stages.items() if any(n in drop for n in ns) for m in ns}   # (matrix_v2) the whole stage
        for s, c in fits.items():
            rate = {"form": "expr", "expr": _expr(s, c, S)}
            added.append({"from": None if s == "in" else S, "to": S if s == "in" else None, "ratio": 1,
                          "rate": rate, "rates": [dict(rate)], "id": f"tracker_{s}_{S}"})
        changed.append({"stock": S, **{s: dict(c) for s, c in fits.items()}, "sse": [sse_base, sse_new],
                        **({"moves_dropped": len(g["moved"])} if g.get("moved") else {})})
    if not changed:
        return result
    out = copy.copy(result)
    out["flows"] = [f for n, f in enumerate(flows) if n not in drop] + added
    gone = {H for H, ns in stages.items() if any(n in drop for n in ns)}
    if gone:                                                 # (matrix_v2) a removed stage's levels go with it
        out["inferred_levels"] = {H: v for H, v in lv.items() if H not in gone}
    out["tracker"] = changed
    return out


def _try(g, ids, final, read, inputs, states, flows, T, logT, deadline):
    """(bic_new - bic_base, g, fits, sse_base, sse_new) where a tracker on g's stock wins; None where none does
    (kalman_lna's loop body at 9d3ca8e, as a function so a stock's variants can be compared: matrix_v2)."""
    si, S, sides, outside, net, base, k_base, floor = (g[k] for k in ("si", "S", "sides", "outside", "net", "base",
                                                                       "k_base", "floor"))
    readers = [(ids[j], read[j]) for j in range(len(ids)) if j != si and ids[j] not in final] + list(inputs.items())
    Sv = read[si]
    fits = {}
    for s in sides:
        y = np.maximum(net, 0.0) if s == "in" else np.maximum(-net, 0.0)
        fits[s] = _side(s, Sv, y, readers, floor, deadline)
    fits = {s: c for s, c in fits.items() if c is not None}
    if not fits:
        return None
    pred = np.zeros(T)
    for s, c in fits.items():
        target = np.ceil(dict(readers)[c["reader"]] / c["a"])
        if c["clamp"] is not None:
            target = np.minimum(c["clamp"], target) if s == "in" else np.maximum(c["clamp"], target)
        p = _predict(s, c["form"], Sv, target, c["d"])
        pred += p if s == "in" else -p
    k_new = sum(c["numbers"] for c in fits.values())
    for s in sides:                                          # a side the tracker leaves keeps its flows
        if s not in fits:
            for n in outside[s]:
                amt = _amounts(flows[n], states)
                pred += amt if s == "in" else -amt
                k_new += _numbers(flows[n])
    bic = lambda sse, k: T * math.log((sse + floor) / T) + k * logT  # noqa: E731
    sse_new = float(((net - pred) ** 2).sum())
    sse_base = float(((net - base) ** 2).sum())
    if sse_new > (1 - EXPLAINED) * float(net @ net) or not bic(sse_new, k_new) + PRICE * logT < bic(sse_base, k_base):
        return None
    return bic(sse_new, k_new) - bic(sse_base, k_base), g, fits, sse_base, sse_new


STILL = 0.5            # (matrix_v2) a stock still (no change beyond rounding) on at least this share of the steps


def _still(d: np.ndarray) -> bool:
    """(matrix_v2) S holds exactly still on most steps (a counted stock a controller moves now and then)."""
    scale = float(np.max(np.abs(d))) if len(d) else 0.0
    return scale > 0 and float(np.mean(np.abs(d) <= 1e-6 * scale)) >= STILL


def _stock(si, S, ids, final, dy, read, states, flows, declared, bd, stages=None, drop_moves=False) -> dict | None:
    """S's outside net flow (its change less the answer's flows between it and other measured stocks), the
    answer's outside flows on the sides a tracker may take, and how badly they fit; None where S is not a
    candidate (final, constant, no estimated side, a flow this reader cannot run, or fitted to resolution)."""
    if S in final or np.ptp(read[si]) <= 0:
        return None
    T = dy.shape[1]
    sides = [side for side in ("in", "out") if not declared or "estimate" in ((bd.get(S) or {}).get(side) or [])]
    if not sides:
        return None
    inside = np.zeros(T)
    outside = {"in": [], "out": []}
    moved, extra, k_extra = [], np.zeros(T), 0
    for n, f in enumerate(flows):
        a, b = f.get("from"), f.get("to")
        if S not in (a, b):
            continue
        if a is None or b is None or a in (stages or {}) or b in (stages or {}):
            outside["in" if b == S else "out"].append(n)     # (matrix_v2) a stage's flow into S is an outside one
            continue
        amt = _amounts(f, states)
        if amt is None:
            return None
        if drop_moves:                                       # (matrix_v2) S's moves join what the tracker replaces
            moved.append(n)
            extra += amt if b == S else -float(f.get("ratio") or 1) * amt
            k_extra += _numbers(f)
            continue
        inside += amt if b == S else -float(f.get("ratio") or 1) * amt
    if any(outside[s] for s in ("in", "out") if s not in sides):
        return None                                          # an outside flow the tracker may not replace
    net = dy[si] - inside
    base = np.zeros(T)
    k_base = 0
    for s in sides:
        for n in outside[s]:
            amt = _amounts(flows[n], states)
            if amt is None:
                return None
            base += amt if s == "in" else -amt
            k_base += _numbers(flows[n])
    base, k_base = base + extra, k_base + k_extra
    floor = RESOLUTION * float(np.mean(dy[si] ** 2)) * T + 1e-300
    sse_base = float(((net - base) ** 2).sum())
    if sse_base <= floor:
        return None                                          # the answer already fits S to the data's resolution
    return {"si": si, "S": S, "sides": sides, "outside": outside, "net": net, "base": base, "k_base": k_base,
            "floor": floor, "misfit": sse_base / (float(net @ net) + floor), "moved": moved}
