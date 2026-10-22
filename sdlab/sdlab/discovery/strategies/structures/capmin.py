"""A capacity limit: a flow out of X at MIN(a x X, b x Y) (docs/research/k8s-306-s1.md, 2026-10-21).

A rate that is the lesser of a demand on X and a capacity read off Y (another measured stock that is
not a counter, or a measured input) is not linear in the levels, so a linear row fit replaces it by a
proxy and the rest of the model compensates. Here it is offered to the strategy's own fit as one more
measured series, the regime-clipped source `m = MIN(X, theta x Y)`, so `a x m` is an ordinary linear
term that the strategy fits, prices and keeps or drops jointly with the rest of its model
(theta = b / a, the regime threshold). Afterwards every term reading m is written back as
`MIN(a x X, a theta x Y)` (an expression flow), so the answer reads only measured stocks and inputs.

`offer` finds (X, Y, theta) from the data alone. For each non-final measured stock X, its one-step
changes are regressed on a constant, every measured level and every input, with and without m; theta
is chosen over quantiles of X / Y and refined by golden section. The best pair is then refined on X's
row together with the other row m explains best (where the flow goes), by the profile likelihood of
both rows. m is offered only where it wins decisively on X's row: Gaussian BIC better by more than
PRICE x log T, with each regime holding on at least MIN_SHARE of the steps and MIN_STEPS steps (a limit that never binds,
or always does, is a linear rate). The same rule for every case; nothing reads the case or its truth.

This file is copied into each strategy that uses it (strategies are isolated, CLAUDE.md rule 11); the
copies are identical when written.
"""

from __future__ import annotations

import copy
import math

import numpy as np

PRICE = 6.0            # the extra numbers' price (theta and the arm), in log T, plus a margin
MIN_SHARE = 0.01       # each regime holds on at least this share of the steps ...
MIN_STEPS = 5          # ... and on at least this many (k8s 312, docs/research/fixes/312-structures.md: with the
                       # autoscaler adding nodes, the pods' capacity binds only after a node failure, on 7 of 299
                       # steps; at 5% the grid stopped at theta 61 for 66.7 and the base lost the dispatch move)
GRID = 24              # theta candidates (quantiles of X / Y)
NAME = "capmin__"      # the offered series' name prefix
TOP_POOL = 3           # (k8s 316) fixed-pool pairs (X, Z) refined after the coarse screen
RESOLUTION = 1e-8      # a residual variance below this share of the mean squared change is rounding


def level_series(name) -> bool:
    """Is this input the offered series? It is a function of measured levels, not something from
    outside, so a row reads it wherever it may read the levels (a declared boundary's rule for
    measured inputs does not apply to it)."""
    return str(name).startswith(NAME)


def offered(opts: dict | None) -> dict:
    """{series name: (X, its receiver or None)} for the series offer() added to opts."""
    return {k: (v["source"], v.get("to")) for k, v in ((opts or {}).get("capmin") or {}).items()}


def readers(name, opts: dict | None) -> tuple | None:
    """The stocks whose rows may read the offered series `name`: the flow it limits leaves X and enters
    its receiver (only X when it leaves for outside); None when `name` is not an offered series."""
    got = offered(opts).get(name)
    return None if got is None else tuple(x for x in got if x is not None)


def excluded(stock: str, names: list[str], inputs, inputs_ok: bool, opts: dict | None) -> list[int]:
    """The input columns (indices into names) a row of `stock` may not read: a measured input where the
    boundary has no measured side for it (not inputs_ok), and an offered series outside the rows of
    the flow it limits."""
    out = []
    for j in inputs:
        r = readers(names[j], opts)
        if (r is None and not inputs_ok) or (r is not None and stock not in r):
            out.append(j)
    return out


def _steps(stocks: list[dict], run: dict, opts: dict):
    """Each measured stock's one-step change less announced injections, the levels its rates read
    (injections added), and each measured input at the step's end (the engine's convention)."""
    ids = [s["id"] for s in stocks]
    final = {s["id"] for s in stocks if s.get("final")}
    t = np.asarray(run["t"], dtype=float)
    L = np.nan_to_num(np.array([np.asarray(run["levels"].get(i, []), dtype=float) for i in ids]))
    if L.ndim != 2 or L.shape[1] < 20:
        return None
    dy = L[:, 1:] - L[:, :-1]
    read = L[:, :-1].copy()
    at = {float(x): k for k, x in enumerate(t[1:])}
    index = {s: i for i, s in enumerate(ids)}
    for j in opts.get("injections") or []:
        k, i = at.get(float(j["t"])), index.get(j.get("stock"))
        if k is not None and i is not None:
            dy[i, k] -= float(j["amount"])
            read[i, k] = max(0.0, read[i, k] + float(j["amount"]))
    T = dy.shape[1]
    inputs = {}
    for name, v in (opts.get("inputs") or {}).items():
        if name in index:
            continue
        u = np.nan_to_num(np.asarray(v, dtype=float))
        if len(u) >= T + 1:
            inputs[name] = u[1:T + 1]
    return ids, final, dy, read, inputs


def _rss(B: np.ndarray, y: np.ndarray) -> float:
    coef, *_ = np.linalg.lstsq(B, y, rcond=None)
    r = y - B @ coef
    return float(r @ r)


def _golden(f, grid: np.ndarray) -> tuple[float, float]:
    """The minimum of f over grid, refined by golden section between the best point's neighbours."""
    vals = [f(th) for th in grid]
    j = int(np.argmin(vals))
    lo, hi = grid[max(0, j - 1)], grid[min(len(grid) - 1, j + 1)]
    th, best = float(grid[j]), vals[j]
    for _ in range(40):
        if hi - lo <= 1e-9 * max(1.0, abs(hi)):
            break
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


def _design(ids, read, inputs, opts, t, T):
    """The linear rows' columns (a constant, every measured level, every input; per announced era when
    there are eras), and the same with every product of two of the levels and inputs (a smooth
    second-order surface: what a MIN has to beat to be a kink rather than a curve)."""
    cols = [np.ones(T)] + [read[i] for i in range(len(ids))] + list(inputs.values())
    starts = sorted(float(e["start"]) for e in (opts.get("eras") or []) if e and e.get("start") is not None)
    if len(starts) > 1:
        era = np.searchsorted(np.array(starts), t[1:T + 1], side="right") - 1
        cols = [c * (era == e) for e in sorted(set(era.tolist())) for c in cols]
    vals = [read[i] for i in range(len(ids))] + list(inputs.values())
    prods = [vals[i] * vals[j] for i in range(len(vals)) for j in range(i, len(vals))]
    B = np.column_stack(cols)
    Q = np.column_stack(cols + prods)
    return B, Q


def _gain(B: np.ndarray, m: np.ndarray, y: np.ndarray, floor: float) -> tuple[float, float]:
    """(T log of how much m lowers the row's residual on top of B, m's coefficient)."""
    coef, *_ = np.linalg.lstsq(np.column_stack([B, m]), y, rcond=None)
    r1 = y - np.column_stack([B, m]) @ coef
    return len(y) * math.log((_rss(B, y) + floor) / (float(r1 @ r1) + floor)), float(coef[-1])


def offer(stocks: list[dict], run: dict, opts: dict | None) -> tuple[dict, dict | None]:
    """opts with the regime-clipped series added as a measured input where a capacity limit wins, and
    what restore() needs (None where none is offered).

    For each non-final stock X and capacity Y: theta on X's row (a grid of X / Y quantiles, then golden
    section); m must take from X (a negative coefficient in X's row). Its receiver is the row where m
    enters with a positive coefficient and lowers the residual most (none: an outflow to outside), and
    theta is refined on X's row and the receiver's together. The evidence is the kink: what m adds to
    each of those rows on top of every product of two levels or inputs (a smooth curve is not a limit),
    summed over the two rows; it must exceed PRICE x log T, and so must m's gain on the linear rows."""
    opts = dict(opts or {})
    if any(str(k).startswith(NAME) for k in (opts.get("inputs") or {})):
        return opts, None                                  # already offered (a strategy calling itself)
    got = _steps(stocks, run, opts)
    if got is None:
        return opts, None
    ids, final, dy, read, inputs = got
    T = dy.shape[1]
    B, Q = _design(ids, read, inputs, opts, np.asarray(run["t"], dtype=float), T)
    caps = [(ids[i], read[i]) for i in range(len(ids)) if ids[i] not in final] + list(inputs.items())
    floor = [RESOLUTION * float(np.mean(dy[i] ** 2)) * T + 1e-300 for i in range(len(ids))]   # the data's resolution
    price = PRICE * math.log(T)
    best = None
    for xi, x in enumerate(ids):
        X = read[xi]
        if x in final or np.ptp(X) <= 0:
            continue
        for name, Y in caps:
            if name == x or np.ptp(Y) <= 0 or (Y > 0).sum() < 10:
                continue
            ratio = X[Y > 0] / Y[Y > 0]
            lo = max(MIN_SHARE, MIN_STEPS / len(ratio))
            grid = np.unique(np.quantile(ratio, np.linspace(lo, 1 - lo, GRID)))
            th, _ = _golden(lambda th: _rss(np.column_stack([B, np.minimum(X, th * Y)]), dy[xi]), grid)
            m = np.minimum(X, th * Y)
            gx, cx = _gain(B, m, dy[xi], floor[xi])
            if cx >= 0 or gx <= 0:                         # a limited outflow of X takes from X
                continue
            to = None
            for z in range(len(ids)):
                if z != xi:
                    gz, cz = _gain(B, m, dy[z], floor[z])
                    if cz > 0 and gz > price and (to is None or gz > to[0]):
                        to = (gz, z)
            rows = [xi] + ([to[1]] if to else [])
            th, _ = _golden(lambda th: sum(math.log(_rss(np.column_stack([B, np.minimum(X, th * Y)]), dy[r]) + floor[r])
                                           for r in rows), grid)
            share = float(np.mean(X <= th * Y))
            held = int(np.sum(X <= th * Y))
            if not (MIN_SHARE <= share <= 1 - MIN_SHARE) or min(held, T - held) < MIN_STEPS:
                continue
            m = np.minimum(X, th * Y)
            gain = sum(_gain(B, m, dy[r], floor[r])[0] for r in rows)
            kink = sum(_gain(Q, m, dy[r], floor[r])[0] for r in rows)
            if gain > price and kink > price and (best is None or kink > best["kink"]):
                best = {"source": x, "cap": name, "theta": th, "gain": gain, "kink": kink, "share": share}
                if to:
                    best["to"] = ids[to[1]]
    pool = _pool(ids, final, dy, read, B, Q, floor, price, T)
    if pool is not None and (best is None or pool["kink"] > best["kink"] + math.log(T)):
        best = pool
    if best is None:
        return opts, None
    m = _series(best, read, ids, inputs)
    name = f"{NAME}{best['source']}__{best.get('cap') or 'pool'}"
    series = np.concatenate([[m[0]], m])     # input i is read by step i - 1 (m[0]: the first level's own)
    inp = dict(opts.get("inputs") or {})
    inp[name] = [float(v) for v in series]
    opts["inputs"] = inp
    best["name"] = name
    opts["capmin"] = {**(opts.get("capmin") or {}), name: {"source": best["source"], "to": best.get("to")}}
    return opts, best


def _series(cap: dict, read: np.ndarray, ids: list[str], inputs: dict) -> np.ndarray:
    """The offered series MIN(X, theta Y), or MIN(X, max(0, a - b Z)) for a fixed pool (_pool)."""
    X = read[ids.index(cap["source"])]
    if cap.get("cap") is None:
        return np.minimum(X, np.maximum(0.0, cap["a"] - cap["b"] * read[ids.index(cap["occupant"])]))
    Y = read[ids.index(cap["cap"])] if cap["cap"] in ids else inputs[cap["cap"]]
    return np.minimum(X, cap["theta"] * Y)


class _Proj:
    """Fast residual sums of squares of a row on [B, m] for many m: B's QR once."""

    def __init__(self, B: np.ndarray, y: np.ndarray, floor: float):
        q, r = np.linalg.qr(B)
        keep = np.abs(np.diag(r)) > 1e-10 * max(1.0, float(np.abs(np.diag(r)).max()))
        self.q = q[:, keep]
        self.r = y - self.q @ (self.q.T @ y)
        self.rss0 = float(self.r @ self.r)
        self.floor = floor

    def rss(self, m: np.ndarray) -> float:
        u = m - self.q @ (self.q.T @ m)
        uu = float(u @ u)
        if uu <= 1e-12 * max(1.0, float(m @ m)):
            return self.rss0
        g = float(self.r @ u)
        return max(self.rss0 - g * g / uu, 0.0)


def _pool(ids, final, dy, read, B, Q, floor, price, T) -> dict | None:
    """(k8s 316, docs/research/fixes/316-structures.md) A fixed pool: the flow out of X limited by the room a
    fixed capacity leaves after what already holds it, MIN(X, max(0, a - b Z)) (a connection pool of a fixed
    size, Z the connections in use: no measured stock is the capacity, so MIN(X, theta Y) cannot say it). For
    each non-final X and each other non-final measured Z: b on a log grid around the two stocks' spreads, a over
    quantiles of X + b Z (where the two arms cross), both refined by golden section on X's row; the receiver and
    the guards as offer()'s (each regime on MIN_SHARE and MIN_STEPS steps, gain and kink above the price)."""
    # a coarse screen of every (X, Z) on X's row (a few b, a by golden section), then the TOP_POOL best refined
    screen = []
    projs = {}
    for xi, x in enumerate(ids):
        X = read[xi]
        if x in final or np.ptp(X) <= 0:
            continue
        px = _Proj(B, dy[xi], floor[xi])
        if px.rss0 <= floor[xi]:
            continue                                       # X's row is already linear to the data's resolution
        projs[xi] = px
        for zi, z in enumerate(ids):
            Z = read[zi]
            if zi == xi or z in final or np.ptp(Z) <= 0:
                continue
            scale = float(np.std(X)) / max(float(np.std(Z)), 1e-12)
            got = math.inf
            for b in scale * np.geomspace(0.02, 50.0, 8):
                S = X + b * Z
                grid = np.unique(np.quantile(S, np.linspace(0.05, 0.95, 12)))
                got = min(got, _golden(lambda a: px.rss(np.minimum(X, np.maximum(0.0, a - b * Z))), grid)[1])
            screen.append((math.log((got + px.floor) / (px.rss0 + px.floor)), xi, zi))
    screen.sort()
    best = None
    for _, xi, zi in screen[:TOP_POOL]:
        x, X, Z, px = ids[xi], read[xi], read[zi], projs[xi]
        z = ids[zi]
        scale = float(np.std(X)) / max(float(np.std(Z)), 1e-12)

        def at_b(b, f):
            S = X + b * Z
            lo = max(MIN_SHARE, MIN_STEPS / len(S))
            grid = np.unique(np.quantile(S, np.linspace(lo, 1 - lo, GRID)))
            return _golden(lambda a: f(np.minimum(X, np.maximum(0.0, a - b * Z))), grid)

        f1 = px.rss
        lbs = np.log(scale) + np.linspace(math.log(0.02), math.log(50.0), 12)
        lb, _ = _golden(lambda lb: at_b(math.exp(lb), f1)[1], lbs)
        b = math.exp(lb)
        a, _ = at_b(b, f1)
        m = np.minimum(X, np.maximum(0.0, a - b * Z))
        gx, cx = _gain(B, m, dy[xi], floor[xi])
        if cx >= 0 or gx <= price:
            continue
        to = None
        for r in range(len(ids)):
            if r != xi:
                gz, cz = _gain(B, m, dy[r], floor[r])
                if cz > 0 and gz > price and (to is None or gz > to[0]):
                    to = (gz, r)
        rows = [xi] + ([to[1]] if to else [])
        both = [px] + [_Proj(B, dy[r], floor[r]) for r in rows[1:]]

        def f2(m):
            return sum(math.log(p.rss(m) + p.floor) for p in both)
        for _ in range(2):                                 # a and b refined on both rows, in turn
            lb, _ = _golden(lambda lb: at_b(math.exp(lb), f2)[1], np.linspace(lb - 0.7, lb + 0.7, 7))
            b = math.exp(lb)
            a, _ = at_b(b, f2)
        m = np.minimum(X, np.maximum(0.0, a - b * Z))
        held = int(np.sum(m >= X))
        share = held / len(X)
        if not (MIN_SHARE <= share <= 1 - MIN_SHARE) or min(held, T - held) < MIN_STEPS or a <= 0:
            continue
        gain = sum(_gain(B, m, dy[r], floor[r])[0] for r in rows)
        kink = sum(_gain(Q, m, dy[r], floor[r])[0] for r in rows)
        if gain > price and kink > price and (best is None or kink > best["kink"]):
            best = {"source": x, "cap": None, "occupant": z, "a": float(a), "b": float(b), "theta": float(b),
                    "c": float(a / b), "gain": gain, "kink": kink, "share": share}
            if to:
                best["to"] = ids[to[1]]
    return best


def _min_text(k: float, cap: dict) -> str:
    """k x a limit written out: MIN(k X, k theta Y); with a room (room.py, k8s 311) MIN(k X, max(0, k theta c Y - k theta Z))."""
    x, y, th = cap["source"], cap["cap"], cap["theta"]
    if y is None:                                          # a fixed pool (_pool): MIN(k X, max(0, k a - k b Z))
        z, a, b = cap["occupant"], cap["a"], cap["b"]
        if k >= 0:
            return f"min({k!r} * {x}, max(0, {k * a!r} - {k * b!r} * {z}))"
        return f"{k!r} * min({x}, max(0, {a!r} - {b!r} * {z}))"
    if cap.get("room"):
        z, c = cap["occupant"], cap["c"]
        if k >= 0:
            return f"min({k!r} * {x}, max(0, {k * th * c!r} * {y} - {k * th!r} * {z}))"
        return f"{k!r} * min({x}, max(0, {th * c!r} * {y} - {th!r} * {z}))"
    return f"min({k!r} * {x}, {k * th!r} * {y})" if k >= 0 else f"{k!r} * min({x}, {th!r} * {y})"


def _expr(rate: dict, cap: dict) -> dict:
    """A linear rate with a term reading the offered series, as an expression with the MIN written out."""
    name = cap["name"]
    form = rate.get("form")
    if form == "proportional":
        terms, c = [{"stock": rate.get("stock"), "k": rate.get("k", 0.0)}], 0.0
    elif form == "linear":
        terms, c = list(rate.get("terms") or []), float(rate.get("c") or 0.0)
    else:
        return rate
    if not any(t.get("stock") == name for t in terms):
        return rate
    parts = [repr(c)] if c else []
    for t in terms:
        k = float(t.get("k") or 0.0)
        if t.get("stock") == name:
            parts.append(_min_text(k, cap))
        else:
            parts.append(f"{k!r} * {t.get('stock')}")
    return {"form": "expr", "expr": " + ".join(parts) or "0"}


def restore(result: dict, cap: dict | None) -> dict:
    """The strategy's answer with every rate that reads the offered series written as its MIN."""
    if not cap or not isinstance(result, dict):
        return result
    out = copy.deepcopy(result)
    for n, f in enumerate(out.get("flows") or []):
        for g in f.get("byTime") or []:
            if g.get("rate"):
                g["rate"] = _expr(g["rate"], cap)
        if f.get("rate"):
            f["rate"] = _expr(f["rate"], cap)
        if f.get("rates"):
            f["rates"] = [_expr(r, cap) for r in f["rates"]]
        if f.get("input") == cap["name"]:
            f.pop("input", None)
        rates = [g.get("rate") or {} for g in f.get("byTime") or []] + [f.get("rate") or {}]
        if any(r.get("form") == "expr" for r in rates):
            f.setdefault("id", f"capmin{n}")             # an expression flow is named (the engine's compiler wants one)
    out["capmin"] = {k: cap[k] for k in ("source", "cap", "occupant", "a", "b", "to", "theta", "gain", "kink", "share") if k in cap}
    return out


def wrap(identify, stocks: list[dict], run: dict, opts: dict | None, *args, **kw) -> dict:
    """identify(stocks, run, opts) with a capacity limit offered where the data show one."""
    o, cap = offer(stocks, run, opts)
    return restore(identify(stocks, run, o, *args, **kw), cap)
