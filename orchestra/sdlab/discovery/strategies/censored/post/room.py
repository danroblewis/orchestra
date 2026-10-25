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
- (k8s 312) c and theta are chosen on the untrimmed BIC (OBJ): on 312 none-long, with the kills not yet in, the
  trimmed one ran theta to 0.14 for 2 and a proxy capacity (queue) won; polish() refits the numbers last, with
  the kill move in, so the trimmed numbers are no longer needed there;
- the best is kept when the touched rows' BIC falls by more than PRICE x log n (c and theta are two numbers
  more than a plain move), and written as `min(k X, max(0, k theta c Y - k theta Z))`.
"""

from __future__ import annotations

import math
import os

import numpy as np

from . import steps
from . import judge as J
from .capmin import _min_text
from .hidden import _amount
from .repair import _bic, _fit, _free, _numbers, _sign

TRIM = 5.0
_DEBUG = bool(os.environ.get("SDLAB_ROOM_DEBUG"))

GATE = 100.0
MIN_STEPS = 5
OBJ = int(os.environ.get("SDLAB_ROOM_OBJ", "0"))   # (k8s 312) theta and c on the untrimmed BIC (4: the trimmed one)
PRICE = 6.0
GRID = 10
TOP = 3
SERIES = "room__"
ITERS = 16         # golden-section steps (polish() refits the numbers exactly at the end)


def _theta_q(m: int) -> np.ndarray:
    """The quantiles of X / room the theta grid takes: up to all but the top MIN_STEPS steps (k8s 312: with the
    autoscaler adding nodes the room binds on 92 of 1999 steps, beyond the 95% quantile the grid stopped at)."""
    return np.linspace(0.05, max(0.95, 1.0 - MIN_STEPS / max(m, 1)), GRID)


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
    # (k8s 312) a plain move X -> B already in the answer (the base's proportional stand-in for the limited
    # one: 312 none-short `pending -> ready = 0.15 pending`) is replaced by the candidate, not a reason to skip it
    plain_mv = {(f.get("from"), f.get("to")): f for f in flows if f.get("from") in measured and f.get("to") in measured
                and _free(f, X, bound, declared) and (f.get("rate") or {}).get("form") in ("proportional", "linear")}
    have = {(f.get("from"), f.get("to")) for f in flows} - set(plain_mv)
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
            if (a, b) in plain_mv:
                am = _amount(plain_mv[(a, b)], X, n)
                ra, rb = ra - am, rb + am
            # (k8s 312) ranked with the free flows of the two rows refitted beside it (linearly): the residual and
            # each candidate are projected off their columns. Ranked on the raw residuals, a fit whose floored sides
            # had absorbed the missing room (312 none-short) put capacities like retries ahead of the nodes.
            Q = _free_basis(flows, a, b, plain_mv.get((a, b)), X, n, bound, declared)
            r2 = np.concatenate([ra, rb])
            if Q is not None:
                r2 = r2 - Q @ (Q.T @ r2)
            ra, rb = r2[:n], r2[n:]
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
                        for th in np.unique(np.quantile(A[R > 0] / R[R > 0], _theta_q(int((R > 0).sum())))):
                            m = np.minimum(A, th * R)
                            # the move takes k m from a and gives it to b: k by least squares on both residuals
                            v = np.concatenate([-m, m])
                            if Q is not None:
                                v = v - Q @ (Q.T @ v)
                            g = float(np.concatenate([ra, rb]) @ v)
                            mm = float(v @ v)
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
    if _DEBUG:
        print("room top", top, "bad", bad)
    for a, b, y, z, c0 in top:
        base = evaluate(flows, a, b)
        others = [f for f in flows if f is not plain_mv.get((a, b))]
        if base is None:
            continue
        A, Y, Z = X[a], X[y], X[z]

        def trial(c, th):
            X[SERIES] = np.minimum(A, th * np.maximum(0.0, c * Y - Z))
            mv = {"id": f"room_{a}_{b}", "from": a, "to": b, "ratio": 1, "rate": {"form": "proportional", "stock": SERIES, "k": 0.1}}
            return evaluate(others + [mv], a, b)

        def by_theta(c):
            R = np.maximum(0.0, c * Y - Z)
            if (R > 0).sum() < 10:
                return math.inf, 1.0
            grid = np.unique(np.quantile(A[R > 0] / R[R > 0], _theta_q(int((R > 0).sum()))))
            th, v = _golden(lambda th: (trial(c, th) or (math.inf,) * 5)[OBJ], grid)
            return v, th
        c, _ = _golden(lambda c: by_theta(c)[0], np.linspace(0.8 * c0, 1.2 * c0, 5))
        th = by_theta(c)[1]
        got = trial(c, th)
        X.pop(SERIES, None)
        if got is None:
            if _DEBUG:
                print("room cand none", a, b, y, z, c, th)
            continue
        gain = base[0] - got[0]
        k_mv = next((float((f.get("rate") or {}).get("k") or 0.0) for f in got[1] if f.get("id") == f"room_{a}_{b}"), 0.0)
        if _DEBUG:
            print("room cand", a, b, y, z, "c", round(c, 4), "th", round(th, 4), "k", round(k_mv, 4), "gain", round(gain, 1))
        if k_mv <= 0:                                 # (k8s 312) a candidate whose move runs backwards is no room move
            continue
        if gain > PRICE * math.log(n) and (best is None or gain > best[0]):
            best = (gain, got[1], {"source": a, "to": b, "cap": y, "occupant": z, "c": float(c), "theta": float(th),
                                   "bic": [round(base[0], 1), round(got[0], 1)]})
    fam = _family(coarse, flows, plain_mv, X, dy, n, q, floor, bound, declared, measured, unit, caps, resid)
    if fam is not None and (best is None or fam[0] > best[0]):
        gain, fl, info = fam
        return {**result, "flows": fl, "room": {**info, "kept": True}}
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


FAMILY = 4          # (k8s 317) moves that may share one room
SEEDS = 3           # (k8s 317) the best single pairs a family is grown from
GROW = 1.05         # (k8s 317) a pair joins the family when the shared room's gain rises by this factor
FAM_SERIES = "roomf__"


def _family(coarse, flows, plain_mv, X, dy, n, q, floor, bound, declared, measured, unit, caps, resid):
    """(k8s 317, docs/research/fixes/317-structures.md) Moves that start into one shared room: several sources of
    one unit (pending pods of three services) whose moves into their receivers (ready pods) are limited together
    by what a capacity leaves after all the receivers hold, each taking its share by its own level,

        A_i -> B_i  at  min(k_i A_i, k_i theta max(0, c Y - (B_1 + ... + B_m)) A_i / max(1, A_1 + ... + A_m)).

    With one move this is the single room above (a share of A / max(1, A) = 1 for A >= 1). 317 shares one node pool
    among three services, and a single room took one service's pending into another's (catalog_pending ->
    cart_pending). The pairs come from the single rooms' coarse ranking (each source's best receiver); a family is
    grown from the best pair while one shared (Y, c, theta) explains the stacked rows better (least squares on a
    number k_i per move after the rows' free flows are projected off), then c and theta are refined by golden
    section on the touched rows' BIC with every plain flow refitted (as the single room), and the family is kept
    when the rows' BIC falls by more than PRICE x log n."""
    first: dict = {}
    for sc, a, b, y, z, c in coarse:
        if (a, b) not in first:
            first[(a, b)] = (sc, y)
    pairs = sorted(((sc, a, b, y) for (a, b), (sc, y) in first.items()), key=lambda r: r[0])
    if len(pairs) < 2:
        return None

    def rows_of_set(fl, ends):
        rows = set(ends)
        for f in fl:
            if (f.get("from") in rows or f.get("to") in rows) and _free(f, X, bound, declared):
                rows |= {x for x in (f.get("from"), f.get("to")) if x in measured}
        return sorted(rows)

    def series(fam, y, c, th):
        A = [X[a] for a, _ in fam]
        R = np.maximum(0.0, c * X[y] - sum(X[b] for _, b in fam))
        tot = np.maximum(1.0, sum(A))
        return [np.minimum(Ai, th * R * Ai / tot) for Ai in A]

    def coarse_gain(fam, y):
        others = [f for f in flows if not any(f is plain_mv.get(p) for p in fam)]
        rows = sorted({x for p in fam for x in p})
        r = []
        for s in rows:
            rs = resid(others, s)
            if rs is None:
                return -math.inf, None
            r.append(rs)
        r = np.concatenate(r)
        Q = _set_basis(others, rows, X, n, bound, declared)
        if Q is not None:
            r = r - Q @ (Q.T @ r)
        A_sum = sum(X[a] for a, _ in fam)
        Zs = sum(X[b] for _, b in fam)
        Y = X[y]
        pos = Y > 0
        if pos.sum() < 10:
            return -math.inf, None
        top = (-math.inf, None)
        for c in np.unique(np.quantile(Zs[pos] / Y[pos], np.linspace(0.5, 1.0, GRID))):
            R = np.maximum(0.0, c * Y - Zs)
            share = R / np.maximum(1.0, A_sum)
            on = share > 0
            if on.sum() < 10:
                continue
            # A_i binds when the sources' total passes theta x the room: theta over quantiles of max(1, total) / room
            for th in np.unique(np.quantile(1.0 / share[on], _theta_q(int(on.sum())))):
                ms = series(fam, y, c, th)
                cols = []
                for (a, b), m in zip(fam, ms):
                    v = np.zeros(len(rows) * n)
                    ia, ib = rows.index(a), rows.index(b)
                    v[ia * n:(ia + 1) * n] -= m
                    v[ib * n:(ib + 1) * n] += m
                    cols.append(v)
                V = np.column_stack(cols)
                if Q is not None:
                    V = V - Q @ (Q.T @ V)
                kk, *_ = np.linalg.lstsq(V, r, rcond=None)
                if np.any(kk <= 0):
                    continue
                g = float(r @ r) - float((r - V @ kk) @ (r - V @ kk))
                if g > top[0]:
                    top = (g, (float(c), float(th)))
        return top

    # grown greedily for each capacity the best single rooms read: from each of the best few pairs, the pair (of
    # stocks not yet in it, in its unit) that raises the shared room's gain most, while it rises by GROW
    best = None
    for y in list(dict.fromkeys(p[3] for p in pairs[:3])):
        for _, a0, b0, _y in pairs[:SEEDS]:
            fam = [(a0, b0)]
            g0, _ = coarse_gain(fam, y)
            while len(fam) < FAMILY:
                used = {x for p in fam for x in p}
                top = None
                for _, a, b, _y2 in pairs:
                    if a in used or b in used or unit.get(a) != unit.get(a0):
                        continue
                    g1, _ = coarse_gain(fam + [(a, b)], y)
                    if top is None or g1 > top[0]:
                        top = (g1, (a, b))
                if top is None or not top[0] > g0 * GROW:
                    break
                fam, g0 = fam + [top[1]], top[0]
            if len(fam) < 2:
                continue
            g, ct = coarse_gain(fam, y)
            if ct is not None and (best is None or g > best[0]):
                best = (g, fam, y, ct)
    if best is None:
        return None
    _, fam, y, (c0, th0) = best
    others = [f for f in flows if not any(f is plain_mv.get(p) for p in fam)]
    ends = sorted({x for p in fam for x in p})

    def evaluate(fl):
        rows = rows_of_set(fl, ends)
        if any(resid(fl, s) is None for s in rows):
            return None
        free = [i for i, f in enumerate(fl) if (f.get("from") in rows or f.get("to") in rows) and _free(f, X, bound, declared)]
        got = _fit(fl, free, rows, X, dy, n)
        if got is None:
            return None
        sse = {s: float(resid(got[0], s) @ resid(got[0], s)) for s in rows}
        return _bic(sse, _numbers(got[0], free), n, floor), got[0]

    def moves_for(c, th):
        ms = series(fam, y, c, th)
        mv = []
        for i, ((a, b), m) in enumerate(zip(fam, ms)):
            X[f"{FAM_SERIES}{i}"] = m
            mv.append({"id": f"room_{a}_{b}", "from": a, "to": b, "ratio": 1, "rate": {"form": "proportional", "stock": f"{FAM_SERIES}{i}", "k": 0.1}})
        return mv

    def trial(c, th):
        got = evaluate(others + moves_for(c, th))
        return math.inf if got is None else got[0]

    def clear():
        for i in range(len(fam)):
            X.pop(f"{FAM_SERIES}{i}", None)
    try:
        base = evaluate(flows)
        if base is None:
            return None
        c = _golden(lambda c: _golden(lambda th: trial(c, th), np.linspace(0.6 * th0, 1.6 * th0, 5), 8)[1],
                    np.linspace(0.8 * c0, 1.2 * c0, 5), 8)[0]
        th = _golden(lambda th: trial(c, th), np.linspace(0.6 * th0, 1.6 * th0, 5))[0]
        got = evaluate(others + moves_for(c, th))
        if got is None:
            return None
        gain = base[0] - got[0]
        if _DEBUG:
            print("room family", fam, y, "c", round(c, 4), "th", round(th, 4), "gain", round(gain, 1))
        if not gain > PRICE * math.log(n):
            return None
        occ = " + ".join(b for _, b in fam)
        tot = " + ".join(a for a, _ in fam)
        out = []
        for f in got[1]:
            r = f.get("rate") or {}
            if r.get("form") == "proportional" and str(r.get("stock", "")).startswith(FAM_SERIES):
                k = float(r.get("k") or 0.0)
                if k <= 0:
                    return None
                a = f["from"]
                expr = f"min({k!r} * {a}, max(0, {k * th * c!r} * {y} - {k * th!r} * ({occ})) * {a} / max(1, ({tot})))"
                rate = {"form": "expr", "expr": expr}
                f = {**f, "rate": rate, "rates": [rate]}
            out.append(f)
        X_ = {k: v for k, v in X.items() if not k.startswith(FAM_SERIES)}
        out = [f for f in out if not (_free(f, X_, bound, declared) and f.get("rate", {}).get("form") != "expr"
                                      and (_amount(f, X_, n) is not None and float(np.max(_amount(f, X_, n))) <= 0.0))]
        return gain, out, {"family": [f"{a} -> {b}" for a, b in fam], "cap": y, "c": float(c), "theta": float(th),
                           "bic": [round(base[0], 1), round(got[0], 1)]}
    finally:
        clear()


def _set_basis(flows: list[dict], rows: list[str], X: dict, n: int, bound: dict, declared: bool):
    """(k8s 317) _free_basis for any set of rows (stacked in the order given)."""
    from .repair import _linear

    cols = []
    for f in flows:
        if not any(s in (f.get("from"), f.get("to")) for s in rows) or not _free(f, X, bound, declared):
            continue
        c, ks = _linear(f.get("rate"))
        names = (["1"] if (c or not ks) else []) + list(ks)
        for nm in names:
            col = np.ones(n) if nm == "1" else X[nm]
            cols.append(np.concatenate([_sign(f, s) * col for s in rows]))
    if not cols:
        return None
    M = np.column_stack(cols)
    M = M[:, np.abs(M).max(axis=0) > 0]
    if M.shape[1] == 0:
        return None
    U, sv, _ = np.linalg.svd(M / np.abs(M).max(axis=0), full_matrices=False)
    return U[:, sv > 1e-10 * sv[0]]


def _free_basis(flows: list[dict], a: str, b: str, skip, X: dict, n: int, bound: dict, declared: bool):
    """An orthonormal basis of the columns the free flows touching rows a and b give those two rows (stacked
    a over b; None when there are none)."""
    from .repair import _linear

    cols = []
    for f in flows:
        if f is skip or not (a in (f.get("from"), f.get("to")) or b in (f.get("from"), f.get("to"))) or not _free(f, X, bound, declared):
            continue
        c, ks = _linear(f.get("rate"))
        names = (["1"] if (c or not ks) else []) + list(ks)
        for nm in names:
            col = np.ones(n) if nm == "1" else X[nm]
            cols.append(np.concatenate([_sign(f, a) * col, _sign(f, b) * col]))
    if not cols:
        return None
    M = np.column_stack(cols)
    M = M[:, np.abs(M).max(axis=0) > 0]
    if M.shape[1] == 0:
        return None
    U, sv, _ = np.linalg.svd(M / np.abs(M).max(axis=0), full_matrices=False)
    return U[:, sv > 1e-10 * sv[0]]


_NUM = r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?"


def polish(result: dict, stocks: list[dict], run: dict, opts: dict | None) -> dict:
    """The room move's three numbers refitted last, with every other flow of the answer held (the counted kill
    move, the hidden drive and the floors are in by then, so its two rows are explained but for it): least
    squares on both rows. Kept when the rows' misfit falls. (k8s 317) A family's numbers likewise (_polish_family)."""
    if not isinstance(result, dict) or not result.get("flows") or (opts or {}).get("eras"):
        return result
    try:
        if (result.get("room") or {}).get("family"):
            return _polish_family(result, stocks, run, opts or {})
        return _polish(result, stocks, run, opts or {})
    except Exception as e:                            # noqa: BLE001  (the answer stands as it was)
        return {**result, "room_polish": {"error": f"{type(e).__name__}: {e}"[:300]}}


def _polish_family(result: dict, stocks: list[dict], run: dict, opts: dict) -> dict:
    """(k8s 317) A shared room's numbers (each move's k_i, the shared theta and c) refitted by least squares on
    every row its moves touch, every other flow held; kept when the rows' misfit falls."""
    import re

    from scipy.optimize import least_squares

    flows = list(result["flows"])
    pat = re.compile(rf"min\(({_NUM}) \* (\w+), max\(0, ({_NUM}) \* (\w+) - ({_NUM}) \* \(([\w +]+)\)\) \* (\w+) / max\(1, \(([\w +]+)\)\)\)")
    idx, parts = [], []
    for i, f in enumerate(flows):
        m = pat.fullmatch((f.get("rate") or {}).get("expr") or "") if str(f.get("id", "")).startswith("room_") else None
        if m:
            idx.append(i)
            parts.append(m)
    if len(idx) < 2:
        return result
    y = parts[0].group(4)
    occ, tot = parts[0].group(6), parts[0].group(8)
    if any(m.group(4) != y or m.group(6) != occ or m.group(8) != tot for m in parts):
        return result
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
    names_o, names_t = [x.strip() for x in occ.split("+")], [x.strip() for x in tot.split("+")]
    if any(k not in X for k in names_o + names_t + [y]):
        return result
    Zs, As = sum(X[k] for k in names_o), np.maximum(1.0, sum(X[k] for k in names_t))
    srcs = [flows[i]["from"] for i in idx]
    rows = sorted({x for i in idx for x in (flows[i].get("from"), flows[i].get("to")) if x in dy})
    held = {}
    for s in rows:
        on = [g for j, g in enumerate(flows) if j not in idx and s in (g.get("from"), g.get("to"))]
        amts = [_amount(g, X, n) for g in on]
        if any(a is None for a in amts):
            return result
        held[s] = dy[s] - sum((_sign(g, s) * a for g, a in zip(on, amts)), np.zeros(n))

    def amounts(p):
        th, c = p[-2], p[-1]
        R = np.maximum(0.0, c * X[y] - Zs)
        return [np.maximum(0.0, np.minimum(k * X[a], k * th * R * X[a] / As)) for k, a in zip(p[:-2], srcs)]

    def res(p):
        am = amounts(p)
        out = []
        for s in rows:
            r = held[s].copy()
            for i, a in zip(idx, am):
                r -= _sign(flows[i], s) * a
            out.append(r)
        return np.concatenate(out)
    k0 = [float(m.group(1)) for m in parts]
    th0 = float(parts[0].group(5)) / k0[0]
    c0 = float(parts[0].group(3)) / (k0[0] * th0)
    p0 = np.array(k0 + [th0, c0])
    r0 = res(p0)
    fit = least_squares(res, p0, method="trf", x_scale="jac", max_nfev=300)
    if np.any(fit.x <= 0) or not float(fit.fun @ fit.fun) < float(r0 @ r0):
        return result
    p = fit.x
    th, c = float(p[-2]), float(p[-1])
    out = list(flows)
    for i, k, a in zip(idx, p[:-2], srcs):
        k = float(k)
        expr = f"min({k!r} * {a}, max(0, {k * th * c!r} * {y} - {k * th!r} * ({occ})) * {a} / max(1, ({tot})))"
        rate = {"form": "expr", "expr": expr}
        out[i] = {**out[i], "rate": rate, "rates": [rate]}
    return {**result, "flows": out, "room_polish": {"sse": [round(float(r0 @ r0), 6), round(float(fit.fun @ fit.fun), 6)],
                                                    "k": [float(v) for v in p[:-2]], "theta": th, "c": c}}


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


def earn(result: dict, stocks: list[dict], run: dict, opts: dict | None) -> dict:
    """(censored port, ledger type 17: a flow earns its place) A room-limited move fitted before the counted move
    and the hidden stock were in may have stood in for them (310: `min(0.5 pending, max(0, 0.006 inflight - 0.03
    desired))`, a room no capacity sets). Once every later stage has run, each room move is tried as its plain arm
    `a X` with the plain flows on its rows refitted (repair's active set); the plain move is kept unless the room
    beats it on the rows' BIC by PRICE x log n, the price room.apply charged it."""
    if not isinstance(result, dict) or not result.get("flows") or (opts or {}).get("eras"):
        return result
    try:
        return _earn(result, stocks, run, opts or {})
    except Exception as e:                            # noqa: BLE001  (the answer stands as it was)
        return {**result, "room_earn": {"error": f"{type(e).__name__}: {e}"[:300]}}


def _earn(result: dict, stocks: list[dict], run: dict, opts: dict) -> dict:
    import re

    pat = re.compile(rf"min\(({_NUM}) \* (\w+), max\(0, ({_NUM}) \* (\w+) - ({_NUM}) \* (\w+)\)\)")
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
    bound = run.get("boundary") or {}
    declared = bool(run.get("boundary_declared"))
    flows = list(result["flows"])
    notes = []
    for i, f in enumerate(list(flows)):
        m = pat.fullmatch((f.get("rate") or {}).get("expr") or "")
        if not m or f.get("from") not in dy or f.get("to") not in dy:
            continue
        a, x = float(m.group(1)), m.group(2)
        if x != f.get("from") or x not in X:
            continue
        rows = [f["from"], f["to"]]

        def sse_of(fl):
            out = {}
            for s in rows:
                on = [g for g in fl if s in (g.get("from"), g.get("to"))]
                amts = [_amount(g, X, n) for g in on]
                if any(v is None for v in amts):
                    return None
                r = dy[s] - sum((_sign(g, s) * v for g, v in zip(on, amts)), np.zeros(n))
                out[s] = float(r @ r)
            return out

        s0 = sse_of(flows)
        if s0 is None:
            continue
        rate = {"form": "proportional", "stock": x, "k": a}
        plain = flows[:i] + [{**f, "rate": rate, "rates": [rate]}] + flows[i + 1:]
        free = [j for j, g in enumerate(plain) if (g.get("from") in rows or g.get("to") in rows) and _free(g, X, bound, declared)]
        touched = sorted({v for j in free for v in (plain[j].get("from"), plain[j].get("to")) if v in dy} | set(rows))
        got = _fit(plain, free, touched, X, dy, n) if free else None
        if got is not None:
            plain = got[0]
        s1 = sse_of(plain)
        if s1 is None or float(plain[i]["rate"].get("k") or 0.0) <= 0:
            continue
        b0 = _bic(s0, 2, n, floor)          # the room's two extra numbers against the plain arm
        b1 = _bic(s1, 0, n, floor)
        if b0 < b1 - PRICE * math.log(n):
            continue
        flows = plain
        notes.append({"move": f"{rows[0]} -> {rows[1]}", "bic": [round(b0, 1), round(b1, 1)]})
    if not notes:
        return result
    return {**result, "flows": flows, "room_earn": notes}
