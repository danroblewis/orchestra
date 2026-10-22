"""A move limited by the room a capacity leaves (k8s 311, docs/research/fixes/311-structures.md).

A flow out of X can be capped by what a capacity has left: pods start only into the room the nodes leave,
`min(a X, max(0, b Y - d Z))` (Y the capacity, in any unit; Z what already occupies it, in X's unit). It is not
linear in the levels, and the base's rows replace it by proxies (311 none-short: no `pending -> ready` at all;
`ready -> outside` bent to 1.09 ready - 1.10 desired to stand in for it). Offering the room series to the base
as one more input (as capmin.py offers MIN(X, theta Y)) does not work: the shared matrix lets every row read an
offered input, and its forward stepwise then breaks rows the series has nothing to do with (inflight read
`nodes` and `oom_kills_total`). So the room limit is searched here, after the base, on the rows the answer
leaves unexplained:

- candidates: a move X -> B between measured stocks of one unit (neither a counter, both rows above GATE x the
  data's quantum, no move X -> B yet), its rate k x MIN(X, theta max(0, c Y - Z)) for Y any other measured
  stock or input and Z a stock of X's unit;
- each (X, B, Y, Z) is ranked on the two rows' residuals over a coarse grid of (c, theta) (k by least
  squares), and the best few are refined by golden section on the rows' BIC with every plain flow on the
  touched rows refitted with the move (repair.py's active-set fit under the engine's floor);
- each fit is trimmed: the steps where the two rows are left far off by another flow the answer lacks yet
  (311: the OOM kills move pods ready -> pending on a few steps, against the room move's direction, and an
  untrimmed fit bends the room to take them: 4.96 nodes - 1.26 ready for 4 nodes - ready) are left out of the
  numbers' fit, by the rows' residuals against TRIM x their robust spread (median absolute deviation), twice;
- the best is kept when the touched rows' BIC falls by more than PRICE x log n (c and theta are two numbers
  more than a plain move), and written as `min(k X, max(0, k theta c Y - k theta Z))`.
"""

from __future__ import annotations

import math

import numpy as np

from . import steps
from ._vendored.combined import judge as J
from .capmin import _min_text
from .hidden import _amount
from .repair import _bic, _fit, _free, _numbers, _sign

TRIM = 5.0

GATE = 100.0
PRICE = 6.0
GRID = 10
TOP = 3
SERIES = "room__"
ITERS = 16         # golden-section steps (polish() refits the numbers exactly at the end)


def _golden(f, grid: np.ndarray, iters: int = ITERS) -> tuple[float, float]:
    """The minimum of f over grid, refined by a few golden-section steps between the best point's neighbours."""
    vals = [f(th) for th in grid]
    j = int(np.argmin(vals))
    lo, hi = float(grid[max(0, j - 1)]), float(grid[min(len(grid) - 1, j + 1)])
    th, best = float(grid[j]), vals[j]
    for _ in range(iters):
        a, b = hi - 0.618 * (hi - lo), lo + 0.618 * (hi - lo)
        fa, fb = f(a), f(b)
        if fa < fb:
            hi = b
            if fa < best:
                th, best = float(a), fa
        else:
            lo = a
            if fb < best:
                th, best = float(b), fb
    return th, best


def apply(result: dict, stocks: list[dict], run: dict, opts: dict | None) -> dict:
    if not isinstance(result, dict) or not result.get("flows") or (opts or {}).get("eras"):
        return result
    try:
        return _apply(result, stocks, run, opts or {})
    except Exception as e:                            # noqa: BLE001  (the answer stands as it was)
        return {**result, "room": {"error": f"{type(e).__name__}: {e}"[:300]}}


def _apply(result: dict, stocks: list[dict], run: dict, opts: dict) -> dict:
    ids = [s["id"] for s in stocks if s["id"] in (run.get("levels") or {})]
    L = {k: np.asarray(run["levels"][k], dtype=float) for k in ids}
    T = min(len(v) for v in L.values())
    if T < 30:
        return result
    n = T - 1
    X = {k: v[:n] for k, v in L.items()}
    for k, v in (opts.get("inputs") or {}).items():
        if k not in X and len(v) >= T:
            X[k] = np.asarray(v, dtype=float)[1:T]
    dy = {k: np.diff(v[:T]) for k, v in L.items()}
    steps.adjust(X, dy, run, opts, n)
    q = J.quantum(np.vstack([v[:T] for v in L.values()]))
    floor = n * q * q / 12.0
    unit = {s["id"]: s.get("unit") for s in stocks}
    finals = {s["id"] for s in stocks if s.get("final")}
    declared = bool(run.get("boundary_declared"))
    bound = run.get("boundary") or {}
    flows = list(result["flows"])
    measured = set(ids)

    def resid(fl, s):
        on = [f for f in fl if s in (f.get("from"), f.get("to"))]
        amts = [_amount(f, X, n) for f in on]
        if any(a is None for a in amts):
            return None
        return dy[s] - sum((_sign(f, s) * a for f, a in zip(on, amts)), np.zeros(n))

    res = {s: resid(flows, s) for s in ids if s not in finals}
    bad = [s for s, r in res.items() if r is not None and float(np.sqrt(np.mean(r * r))) > GATE * q]
    if len(bad) < 2:
        return result
    have = {(f.get("from"), f.get("to")) for f in flows}
    caps = [k for k in X if k not in finals and np.ptp(X[k]) > 0]

    def rows_of(fl, a, b):
        rows = {a, b}
        for f in fl:
            if (f.get("from") in rows or f.get("to") in rows) and _free(f, X, bound, declared):
                rows |= {x for x in (f.get("from"), f.get("to")) if x in measured}
        return sorted(rows)

    def evaluate(fl, a, b):
        rows = rows_of(fl, a, b)
        if any(resid(fl, s) is None for s in rows):
            return None
        free = [i for i, f in enumerate(fl) if (f.get("from") in rows or f.get("to") in rows) and _free(f, X, bound, declared)]
        keep = np.ones(n, dtype=bool)
        got = None
        for _ in range(3):
            got = _fit(fl, free, rows, X, dy, n, keep)
            if got is None:
                return None
            r = np.vstack([resid(got[0], s) for s in rows])
            dev = np.abs(r).max(axis=0)
            mad = 1.4826 * float(np.median(dev))
            new = dev <= max(TRIM * mad, GATE * q)
            if np.array_equal(new, keep) or new.sum() < 0.5 * n:
                break
            keep = new
        sse_all = {s: float(resid(got[0], s) @ resid(got[0], s)) for s in rows}
        sse_kept = {s: float(resid(got[0], s)[keep] @ resid(got[0], s)[keep]) for s in rows}
        k = _numbers(got[0], free)
        return _bic(sse_all, k, n, floor), got[0], rows, free, _bic(sse_kept, k, int(keep.sum()), floor * keep.mean())

    coarse = []
    for a in bad:
        for b in bad:
            if a == b or (a, b) in have or unit.get(a) != unit.get(b) or unit.get(a) is None:
                continue
            ra, rb = res[a], res[b]
            yy = float(ra @ ra + rb @ rb)
            for z in ids:
                if z in finals or z == a or unit.get(z) != unit.get(a) or np.ptp(X[z]) <= 0:
                    continue
                for y in caps:
                    if y in (a, z):
                        continue
                    Y, Z, A = X[y], X[z], X[a]
                    pos = Y > 0
                    if pos.sum() < 10:
                        continue
                    for c in np.unique(np.quantile(Z[pos] / Y[pos], np.linspace(0.5, 1.0, GRID))):
                        R = np.maximum(0.0, c * Y - Z)
                        if (R > 0).sum() < 10:
                            continue
                        for th in np.unique(np.quantile(A[R > 0] / R[R > 0], np.linspace(0.05, 0.95, GRID))):
                            m = np.minimum(A, th * R)
                            # the move takes k m from a and gives it to b: k by least squares on both residuals
                            g = float(-ra @ m + rb @ m)
                            mm = 2.0 * float(m @ m)
                            if mm <= 0 or g <= 0:
                                continue
                            coarse.append((yy - g * g / mm, a, b, y, z, float(c)))
    if not coarse:
        return result
    coarse.sort(key=lambda r: r[0])
    seen, top = set(), []
    for _, a, b, y, z, c in coarse:
        if (a, b, y, z) not in seen:
            seen.add((a, b, y, z))
            top.append((a, b, y, z, c))
        if len(top) >= TOP:
            break
    best = None
    for a, b, y, z, c0 in top:
        base = evaluate(flows, a, b)
        if base is None:
            continue
        A, Y, Z = X[a], X[y], X[z]

        def trial(c, th):
            X[SERIES] = np.minimum(A, th * np.maximum(0.0, c * Y - Z))
            mv = {"id": f"room_{a}_{b}", "from": a, "to": b, "ratio": 1, "rate": {"form": "proportional", "stock": SERIES, "k": 0.1}}
            return evaluate(flows + [mv], a, b)

        def by_theta(c):
            R = np.maximum(0.0, c * Y - Z)
            if (R > 0).sum() < 10:
                return math.inf, 1.0
            grid = np.unique(np.quantile(A[R > 0] / R[R > 0], np.linspace(0.05, 0.95, GRID)))
            th, v = _golden(lambda th: (trial(c, th) or (math.inf,) * 5)[4], grid)
            return v, th
        c, _ = _golden(lambda c: by_theta(c)[0], np.linspace(0.8 * c0, 1.2 * c0, 5))
        th = by_theta(c)[1]
        got = trial(c, th)
        X.pop(SERIES, None)
        if got is None:
            continue
        gain = base[0] - got[0]
        if gain > PRICE * math.log(n) and (best is None or gain > best[0]):
            best = (gain, got[1], {"source": a, "to": b, "cap": y, "occupant": z, "c": float(c), "theta": float(th),
                                   "bic": [round(base[0], 1), round(got[0], 1)]})
    if best is None:
        return {**result, "room": {"bad": bad, "kept": False}}
    gain, fl, info = best
    out = []
    for f in fl:
        r = f.get("rate") or {}
        if r.get("form") == "proportional" and r.get("stock") == SERIES:
            k = float(r.get("k") or 0.0)
            if k <= 0:
                return {**result, "room": {"bad": bad, "kept": False, "why": "the move's number is not positive"}}
            rate = {"form": "expr", "expr": _min_text(k, {**info, "room": True})}
            f = {**f, "rate": rate, "rates": [rate]}
            info["k"] = k
        out.append(f)
    # a free flow the refit leaves moving nothing goes
    X[SERIES] = np.zeros(n)
    out = [f for f in out if not (_free(f, X, bound, declared) and f.get("rate", {}).get("form") != "expr"
                                  and (_amount(f, X, n) is not None and float(np.max(_amount(f, X, n))) <= 0.0))]
    X.pop(SERIES, None)
    return {**result, "flows": out, "room": {**info, "kept": True}}


_NUM = r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?"


def polish(result: dict, stocks: list[dict], run: dict, opts: dict | None) -> dict:
    """The room move's three numbers refitted last, with every other flow of the answer held (the counted kill
    move, the hidden drive and the floors are in by then, so its two rows are explained but for it): least
    squares on both rows. Kept when the rows' misfit falls."""
    if not isinstance(result, dict) or not result.get("flows") or (opts or {}).get("eras"):
        return result
    try:
        return _polish(result, stocks, run, opts or {})
    except Exception as e:                            # noqa: BLE001  (the answer stands as it was)
        return {**result, "room_polish": {"error": f"{type(e).__name__}: {e}"[:300]}}


def _polish(result: dict, stocks: list[dict], run: dict, opts: dict) -> dict:
    import re

    from scipy.optimize import least_squares

    flows = list(result["flows"])
    pat = re.compile(rf"min\(({_NUM}) \* (\w+), max\(0, ({_NUM}) \* (\w+) - ({_NUM}) \* (\w+)\)\)")
    idx = [i for i, f in enumerate(flows) if str(f.get("id", "")).startswith("room_") and pat.fullmatch((f.get("rate") or {}).get("expr") or "")]
    if len(idx) != 1:
        return result
    i = idx[0]
    f = flows[i]
    m = pat.fullmatch(f["rate"]["expr"])
    a0, x, b0, y, d0, z = float(m.group(1)), m.group(2), float(m.group(3)), m.group(4), float(m.group(5)), m.group(6)
    ids = [s["id"] for s in stocks if s["id"] in (run.get("levels") or {})]
    L = {k: np.asarray(run["levels"][k], dtype=float) for k in ids}
    T = min(len(v) for v in L.values())
    n = T - 1
    X = {k: v[:n] for k, v in L.items()}
    for k, v in (opts.get("inputs") or {}).items():
        if k not in X and len(v) >= T:
            X[k] = np.asarray(v, dtype=float)[1:T]
    dy = {k: np.diff(v[:T]) for k, v in L.items()}
    steps.adjust(X, dy, run, opts, n)
    if any(k not in X for k in (x, y, z)):
        return result
    rows = [s for s in (f.get("from"), f.get("to")) if s in dy]
    bound = run.get("boundary") or {}
    declared = bool(run.get("boundary_declared"))

    def sse_of(fl):
        tot = 0.0
        for s in rows:
            on = [g for g in fl if s in (g.get("from"), g.get("to"))]
            amts = [_amount(g, X, n) for g in on]
            if any(v is None for v in amts):
                return None
            r = dy[s] - sum((_sign(g, s) * v for g, v in zip(on, amts)), np.zeros(n))
            tot += float(r @ r)
        return tot

    sse0 = sse_of(flows)
    if sse0 is None:
        return result
    cur, nums = flows, (a0, b0, d0)
    for _ in range(3):
        # the room move's numbers with every other flow held ...
        held = {}
        for s in rows:
            on = [g for j, g in enumerate(cur) if j != i and s in (g.get("from"), g.get("to"))]
            held[s] = dy[s] - sum((_sign(g, s) * _amount(g, X, n) for g in on), np.zeros(n))

        def res(p):
            a, b, d = p
            amt = np.maximum(0.0, np.minimum(a * X[x], np.maximum(0.0, b * X[y] - d * X[z])))
            return np.concatenate([held[s] - _sign(f, s) * amt for s in rows])
        fit = least_squares(res, list(nums), method="trf", x_scale="jac", max_nfev=200)
        if min(fit.x) <= 0:
            break
        nums = tuple(float(v) for v in fit.x)
        rate = {"form": "expr", "expr": f"min({nums[0]!r} * {x}, max(0, {nums[1]!r} * {y} - {nums[2]!r} * {z}))"}
        cur = cur[:i] + [{**cur[i], "rate": rate, "rates": [rate]}] + cur[i + 1:]
        # ... then the plain flows on its rows with it held (repair.py's active-set fit)
        free = [j for j, g in enumerate(cur) if j != i and (g.get("from") in rows or g.get("to") in rows) and _free(g, X, bound, declared)]
        if free:
            touched = sorted({v for j in free for v in (cur[j].get("from"), cur[j].get("to")) if v in dy} | set(rows))
            got = _fit(cur, free, touched, X, dy, n)
            if got is not None and (sse_of(got[0]) or math.inf) < (sse_of(cur) or math.inf):
                cur = got[0]
    sse1 = sse_of(cur)
    if sse1 is None or not sse1 < sse0:
        return result
    out = cur
    a, b, d = nums
    return {**result, "flows": out, "room_polish": {"sse": [round(sse0, 6), round(sse1, 6)], "numbers": [a, b, d]}}
