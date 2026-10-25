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


def _touches(f: dict, stocks: set) -> bool:
    return bool(stocks) and (f.get("from") in stocks or f.get("to") in stocks)


def _own_chain(flows: list[dict], x: str, measured: set) -> set:
    """The unmeasured stocks (a found model's hidden stages) linked, through unmeasured stocks only, to the
    measured stock x and to no other measured stock: x's own hidden chain, which a switch on x replaces."""
    nbr: dict = {}
    for f in flows:
        a, b = f.get("from"), f.get("to")
        if a and b:
            nbr.setdefault(a, set()).add(b)
            nbr.setdefault(b, set()).add(a)
    out = set()
    for h0 in [h for h in nbr.get(x, ()) if h not in measured]:
        comp, todo, hits = set(), [h0], set()
        while todo:
            h = todo.pop()
            if h in comp:
                continue
            comp.add(h)
            for g in nbr.get(h, ()):
                if g in measured:
                    hits.add(g)
                elif g not in comp:
                    todo.append(g)
        if hits == {x}:
            out |= comp
    return out


def apply(result: dict, stocks: list[dict], run: dict, opts: dict | None = None, readable=None) -> dict:
    """The answer with each discrete actuator's outside flows written as switches (see the docstring).
    readable(name): whether a switch may read that measured input (default: every one); an input it may
    not read is still used to evaluate the model's other flows."""
    if not isinstance(result, dict) or not result.get("flows"):
        return result
    from . import hinge

    # each step reads the levels at its start (announced injections added, and taken off its change:
    # hinge.columns, 2026-10-22 k8s-311) and an input's value during the step (the engine's convention)
    levels, cols, n = hinge.columns(run, opts)
    if not levels:
        return result
    T = n + 1
    if n < 10:
        return result
    finals = {s["id"] for s in stocks if s.get("final")}
    boundary = run.get("boundary") if run.get("boundary_declared") else None
    out = copy.deepcopy(result)
    flows = out["flows"]
    notes = []
    for x in levels:
        if x in finals:
            continue
        got = None
        for drop in (False, True):                        # X's moves with other measured stocks as found, then dropped
            got = _try(x, flows, levels, cols, n, T, finals, boundary, readable, drop)
            if got is not None:
                break
        if got is None:
            continue
        flows[:], note = got
        for h in note.get("dropped") or []:
            (out.get("inferred_levels") or {}).pop(h, None)
        notes.append(note)
    if notes:
        out["switch"] = notes
    return out


def _try(x: str, flows: list[dict], levels: dict, cols: dict, n: int, T: int, finals: set, boundary, readable, drop: bool):
    """X's outside sides as switches: (new flows, note) or None. drop: X's moves with other measured stocks are
    left out of X's row (a stock that holds exactly still on most steps cannot carry a smooth move: what the
    fit wrote as one is the actuator's smear), removed with X's outside flows, and each partner stock's row is
    repaired by a floored refit of its outside sides (hinge.refit_row); kept only where the partners' rows
    end no worse than before."""
    from . import hinge

    d = hinge.delta(levels, x, T - 1)
    chain = _own_chain(flows, x, set(levels))
    inner = [f for f in flows if f.get("from") and f.get("to") and x in (f["from"], f["to"]) and not _touches(f, chain)]
    dropped = []
    if drop:
        dropped = [f for f in inner if (f["to"] if f["from"] == x else f["from"]) in levels]
        if not dropped:
            return None
        inner = [f for f in inner if f not in dropped]
    rest = np.zeros(n)
    for f in inner:
        a = _amount(f, cols, n)
        if a is None:
            return None
        rest += (a if f["to"] == x else -a * float(f.get("ratio") or 1))
    r = d - rest
    scale = max(1e-12, float(np.abs(r).max()))
    moved = np.abs(r) > STEP_REL * scale
    if moved.sum() < MIN_EVENTS or moved.mean() > MAX_SHARE:
        return None
    outer = [f for f in flows if bool(f.get("from")) != bool(f.get("to")) and x in (f.get("from"), f.get("to"))]
    if any(f.get("switch") for f in outer):
        return None                                      # already switched
    old = np.zeros(n)
    ok = True
    for f in outer:
        a = _amount(f, cols, n)
        if a is None:                                    # a rate this cannot run (an effect, a piece): compared with no flow
            ok = False
            break
        old += a if f.get("to") == x else -a
    if not ok or chain:                                  # (or X's own hidden stocks: what they carry is not known here)
        old = np.zeros(n)
    if drop:                                             # X's row before: with the moves it drops
        for f in dropped:
            a = _amount(f, cols, n)
            if a is None:
                return None
            old += (a if f["to"] == x else -a * float(f.get("ratio") or 1))
    new_flows, new = [], np.zeros(n)
    sides = []
    for side, sign in (("in", 1.0), ("out", -1.0)):
        ev = moved & (sign * r > 0)
        if boundary is not None and not (boundary.get(x) or {}).get(side):
            if ev.any():
                return None
            continue
        if ev.sum() < MIN_EVENTS:
            if ev.any():
                return None
            continue
        step = float(np.median(sign * r[ev]))
        if np.max(np.abs(sign * r[ev] - step)) > STEP_REL * max(1.0, abs(step)):
            return None
        got = _fit_side(ev, x, {k: v for k, v in cols.items() if k in levels or readable is None or readable(k)}, n)
        if got is None or got["misses"] > MISS * n:
            return None
        new += sign * step * _on(got, x, cols, n)
        sides.append(side)
        fl = {"from": None, "to": x} if side == "in" else {"from": x, "to": None}
        new_flows.append({**fl, "id": f"switch_{x}_{side}", "ratio": 1, "rate": _expr(step, got, x),
                          "switch": {"step": step, **got}})
    if not sides:
        return None
    reached = {side for f in flows if _touches(f, chain) for side in (["in"] if not f.get("from") else []) + (["out"] if not f.get("to") else [])}
    if reached - set(sides):                             # a side X's hidden stocks carry that no switch replaces
        return None
    err_new = float(np.sum((r - new) ** 2))
    err_old = float(np.sum((d - rest - old) ** 2)) if drop else float(np.sum((r - old) ** 2))
    if err_new > RESIDUAL * err_old:
        return None
    keep = [f for f in flows if not (f in outer and (("in" if f.get("to") == x else "out") in sides)) and not _touches(f, chain)
            and f not in dropped]
    keep = keep + new_flows
    note = {"stock": x, "sides": sides, "sse_before": err_old, "sse_after": err_new, **({"dropped": sorted(chain)} if chain else {})}
    if drop:
        partners = sorted({f["to"] if f["from"] == x else f["from"] for f in dropped})
        lv = copy.copy(levels)
        repaired = []
        for y in partners:
            # (2026-10-22, k8s-312 round 2) a final counter is a partner like any other: its declared inflow is refitted
            # (a picked model wrote desired -> oom_kills_total = -0.007 retries + 0.028 nodes, and the actuator never switched)
            before = _row_sse(y, flows, lv, cols, n)
            allowed = hinge.allowed_sides(y, {"boundary": boundary, "boundary_declared": boundary is not None}, keep)
            got = hinge.refit_row(y, keep, lv, cols, n, allowed, force=True)
            after_flows = got[0] if got else keep
            after = _row_sse(y, after_flows, lv, cols, n)
            if before is None or after is None or after > before:
                return None
            keep = after_flows
            repaired.append({"stock": y, "sse_before": before, "sse_after": after})
        note.update(moves_dropped=[f"{f['from']}->{f['to']}" for f in dropped], repaired=repaired)
    return keep, note


def _row_sse(y: str, flows: list[dict], levels: dict, cols: dict, n: int) -> float | None:
    """Y's row error under these flows (switches evaluated as written), None where a flow cannot be run."""
    from . import hinge

    d = hinge.delta(levels, y, n)
    m = np.zeros(n)
    for f in flows:
        a, b = f.get("from"), f.get("to")
        if y not in (a, b):
            continue
        if f.get("switch"):
            amt = f["switch"]["step"] * _on(f["switch"], y, cols, n)
        else:
            amt = hinge.amount(f, cols, n)
        if amt is None:
            return None
        m += (-amt * float(f.get("ratio") or 1)) if a == y else amt
    return float(np.sum((d - m) ** 2))
