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
PRICE x log T, with each regime holding on at least MIN_SHARE of the steps (a limit that never binds,
or always does, is a linear rate). The same rule for every case; nothing reads the case or its truth.

This file is copied into each strategy that uses it (strategies are isolated, CLAUDE.md rule 11); the
copies are identical when written.
"""

from __future__ import annotations

import copy
import math

import numpy as np

PRICE = 6.0            # the extra numbers' price (theta and the arm), in log T, plus a margin
MIN_SHARE = 0.05       # (before 2026-10-22, k8s-312) each regime held on at least this share of the steps
MIN_STEPS = 6          # (2026-10-22, k8s-312, docs/research/fixes/312-combined2.md) each regime holds on at least this
                       # many steps: 312's limits bind on 1.4% (dispatch) and 4.6% (start) of none-long's steps, since the
                       # cluster autoscaler adds nodes; the kink and gain are the evidence, not the share


def _lo(T: int) -> float:
    """The smallest share of T steps a regime may hold."""
    return min(MIN_SHARE, MIN_STEPS / max(1, T))
GRID = 24              # theta candidates (quantiles of X / Y)
NAME = "capmin__"      # the offered series' name prefix
RESOLUTION = 1e-8      # a residual variance below this share of the mean squared change is rounding
MAX_LIMITS = 3         # limits offered, one round each (2026-10-22, k8s-311)
BETAS = 12             # pool-size candidates of a headroom limit (quantiles of Z / Y, and past the largest)


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


class _Proj:
    """Least squares on a fixed design B by projection: the residual sum of squares of y on B plus one more
    column m, without a refit (rss(B + m) = rss(B) - (e . m_perp)^2 / |m_perp|^2)."""

    def __init__(self, B: np.ndarray):
        U, sv, _ = np.linalg.svd(B, full_matrices=False)
        self.U = U[:, sv > sv[0] * 1e-12] if sv.size and sv[0] > 0 else U[:, :0]

    def perp(self, v: np.ndarray) -> np.ndarray:
        return v - self.U @ (self.U.T @ v)

    def rss(self, e: np.ndarray, m: np.ndarray) -> float:
        """e: y's residual on B (perp(y))."""
        mp = self.perp(m)
        mm = float(mp @ mp)
        ee = float(e @ e)
        return ee if mm <= 1e-12 * max(1.0, float(m @ m)) else max(0.0, ee - float(e @ mp) ** 2 / mm)


def _room(X: np.ndarray, Y: np.ndarray, Z: np.ndarray, beta: float, th: float) -> np.ndarray:
    """MIN(X, theta x max(0, beta Y - Z)): what X releases into the room left in a pool of beta per Y."""
    return np.minimum(X, th * np.maximum(0.0, beta * Y - Z))


def _search(ids, final, units, dy, read, inputs, B, Q, floor, price, skip: set):
    """One round of offer(): the best limit (plain or headroom) on top of the design B, sources in skip left out."""
    caps = [(ids[i], read[i]) for i in range(len(ids)) if ids[i] not in final] + list(inputs.items())
    best = None
    for xi, x in enumerate(ids):
        X = read[xi]
        if x in final or x in skip or np.ptp(X) <= 0:
            continue
        for name, Y in caps:
            if name == x or np.ptp(Y) <= 0 or (Y > 0).sum() < 10:
                continue
            ratio = X[Y > 0] / Y[Y > 0]
            grid = np.unique(np.quantile(ratio, np.linspace(_lo(len(X)), 1 - _lo(len(X)), GRID)))
            th, _ = _golden(lambda th: _rss(np.column_stack([B, np.minimum(X, th * Y)]), dy[xi]), grid)
            m = np.minimum(X, th * Y)
            got = _judge(xi, m, ids, dy, B, Q, floor, price, X <= th * Y, units,
                         lambda rows: _golden(lambda th: sum(math.log(_rss(np.column_stack([B, np.minimum(X, th * Y)]), dy[r]) + floor[r])
                                                             for r in rows), grid)[0],
                         lambda th: np.minimum(X, th * Y), lambda th: X <= th * Y)
            if got and (best is None or got["kink"] > best["kink"]):
                best = {"source": x, "cap": name, **got}
    # (2026-10-22, k8s-311, docs/research/fixes/311-combined2.md) a headroom limit MIN(X, theta x max(0,
    # beta Y - Z)): X released into the room left in a pool of beta a unit of Y less what Z (a stock of X's unit)
    # already holds (pending pods start into the room the nodes leave: min(0.5 pending, 4 nodes - ready))
    P = _Proj(B)
    E = [P.perp(dy[i]) for i in range(len(ids))]
    for xi, x in enumerate(ids):
        X = read[xi]
        if x in final or x in skip or np.ptp(X) <= 0 or not units.get(x):
            continue
        for zi, z in enumerate(ids):
            if z in (x,) or z in final or units.get(z) != units.get(x) or np.ptp(read[zi]) <= 0:
                continue
            Z = read[zi]
            for name, Y in caps:
                if name in (x, z) or np.ptp(Y) <= 0 or (Y > 0).sum() < 10:
                    continue
                pos = Y > 0
                zr = Z[pos] / Y[pos]
                bgrid = np.unique(np.concatenate([np.quantile(zr, np.linspace(0.5, 1.0, BETAS - 1)), [zr.max() * 1.05]]))

                def fit_th(beta, rows=(xi,)):
                    R = np.maximum(0.0, beta * Y - Z)
                    ok = R > 0
                    if ok.sum() < 10:
                        return None, math.inf
                    tg = np.unique(np.quantile(X[ok] / R[ok], np.linspace(_lo(len(X)), 1 - _lo(len(X)), GRID)))
                    tg = tg[tg > 0]
                    if not tg.size:
                        return None, math.inf
                    return _golden(lambda th: sum(math.log(P.rss(E[r], _room(X, Y, Z, beta, th)) + floor[r]) for r in rows), tg)

                vals = [fit_th(b) for b in bgrid]
                j = int(np.argmin([v[1] for v in vals]))
                if vals[j][0] is None:
                    continue
                lo, hi = bgrid[max(0, j - 1)], bgrid[min(len(bgrid) - 1, j + 1)]
                beta, _ = _golden(lambda b: fit_th(b)[1], np.array([lo, bgrid[j], hi]))
                th, _ = fit_th(beta)
                if th is None:
                    continue

                def refine(rows, X=X, Y=Y, Z=Z, beta=beta, lo=lo, hi=hi):
                    b, _ = _golden(lambda b: fit_th(b, rows)[1], np.unique(np.array([lo, beta, hi])))
                    refine.beta = b
                    return fit_th(b, rows)[0]

                m = _room(X, Y, Z, beta, th)
                got = _judge(xi, m, ids, dy, B, Q, floor, price, X <= th * np.maximum(0.0, beta * Y - Z), units, refine,
                             lambda th, f=refine: _room(X, Y, Z, getattr(f, "beta", beta), th),
                             lambda th, f=refine: X <= th * np.maximum(0.0, getattr(f, "beta", beta) * Y - Z))
                if got and got.get("theta") is not None and (best is None or got["kink"] > best["kink"]):
                    best = {"source": x, "cap": name, "room": z, "beta": float(getattr(refine, "beta", beta)), **got}
    return best


def _judge(xi, m, ids, dy, B, Q, floor, price, first_regime, units, refine, series, regime) -> dict | None:
    """The offer rule for one candidate series m (module docstring): it takes from X; its receiver; the
    threshold refined on X's row and the receiver's; each regime on MIN_SHARE of the steps; gain and kink.
    (2026-10-22, k8s-312, docs/research/fixes/312-combined2.md) The receiver is a stock of X's unit: a move
    carries one thing (the user's rule), and 312 none-long's best offer had been requests moved into nodes."""
    gx, cx = _gain(B, m, dy[xi], floor[xi])
    if cx >= 0 or gx <= 0:                                 # a limited outflow of X takes from X
        return None
    to = None
    for z in range(len(ids)):
        if z != xi and units.get(ids[z]) == units.get(ids[xi]):
            gz, cz = _gain(B, m, dy[z], floor[z])
            if cz > 0 and gz > price and (to is None or gz > to[0]):
                to = (gz, z)
    rows = [xi] + ([to[1]] if to else [])
    th = refine(rows)
    if th is None:
        return None
    share = float(np.mean(regime(th)))
    if not (_lo(len(m)) <= share <= 1 - _lo(len(m))):
        return None
    m = series(th)
    gain = sum(_gain(B, m, dy[r], floor[r])[0] for r in rows)
    kink = sum(_gain(Q, m, dy[r], floor[r])[0] for r in rows)
    if gain > price and kink > price:
        k = -_gain(B, m, dy[xi], floor[xi])[1]             # the limited flow's coefficient on X's row (place())
        if k <= 0 or (to and _gain(B, m, dy[to[1]], floor[to[1]])[1] <= 0):
            return None                                    # (2026-10-22, k8s-312) refined, it must still take from X and enter its receiver
        return {"theta": th, "gain": gain, "kink": kink, "share": share, **({"to": ids[to[1]]} if to else {}), "series": m, "k": k}
    return None


def offer(stocks: list[dict], run: dict, opts: dict | None) -> tuple[dict, dict | None]:
    """opts with the regime-clipped series added as a measured input where a capacity limit wins, and
    what restore() needs (None where none is offered).

    For each non-final stock X and capacity Y: theta on X's row (a grid of X / Y quantiles, then golden
    section); m must take from X (a negative coefficient in X's row). Its receiver is the row where m
    enters with a positive coefficient and lowers the residual most (none: an outflow to outside), and
    theta is refined on X's row and the receiver's together. The evidence is the kink: what m adds to
    each of those rows on top of every product of two levels or inputs (a smooth curve is not a limit),
    summed over the two rows; it must exceed PRICE x log T, and so must m's gain on the linear rows.

    (2026-10-22, k8s-311) The capacity may also be the room left in a pool, max(0, beta Y - Z) for a stock Z
    of X's unit (_search). And after the best limit, the search runs again with it among the columns, for
    another source, up to MAX_LIMITS: a model may have more than one limit (a queue's dispatch by the pods
    ready, and the pods' start by the nodes' room). The first limit is returned as before; the others
    under "more"."""
    opts = dict(opts or {})
    if any(str(k).startswith(NAME) for k in (opts.get("inputs") or {})):
        return opts, None                                  # already offered (a strategy calling itself)
    got = _steps(stocks, run, opts)
    if got is None:
        return opts, None
    ids, final, dy, read, inputs = got
    units = {s["id"]: s.get("unit") for s in stocks}
    T = dy.shape[1]
    B, Q = _design(ids, read, inputs, opts, np.asarray(run["t"], dtype=float), T)
    floor = [RESOLUTION * float(np.mean(dy[i] ** 2)) * T + 1e-300 for i in range(len(ids))]   # the data's resolution
    price = PRICE * math.log(T)
    found = []
    while len(found) < MAX_LIMITS:
        best = _search(ids, final, units, dy, read, inputs, B, Q, floor, price, {c["source"] for c in found})
        if best is None:
            break
        m = best.pop("series")
        found.append(best)
        B, Q = np.column_stack([B, m]), np.column_stack([Q, m])
    if not found:
        return opts, None
    inp = dict(opts.get("inputs") or {})
    reg = dict(opts.get("capmin") or {})
    for best in found:
        X = read[ids.index(best["source"])]
        Y = read[ids.index(best["cap"])] if best["cap"] in ids else inputs[best["cap"]]
        if best.get("room"):
            Z = read[ids.index(best["room"])]
            m = _room(X, Y, Z, best["beta"], best["theta"])
            first = float(_room(X[:1], Y[:1], Z[:1], best["beta"], best["theta"])[0])
            name = f"{NAME}{best['source']}__{best['cap']}__{best['room']}"
        else:
            m = np.minimum(X, best["theta"] * Y)
            first = min(X[0], best["theta"] * Y[0])
            name = f"{NAME}{best['source']}__{best['cap']}"
        series = np.concatenate([[first], m])              # input i is read by step i - 1
        inp[name] = [float(v) for v in series]
        best["name"] = name
        reg[name] = {"source": best["source"], "to": best.get("to")}
    opts["inputs"] = inp
    opts["capmin"] = reg
    cap = dict(found[0])
    if len(found) > 1:
        cap["more"] = found[1:]
    return opts, cap


def place(result: dict, cap: dict | None) -> dict:
    """(2026-10-22, k8s-311) Each offered series read only by the flow it limits: the move from its source to its
    receiver (or the source's outflow where it has none). A fit may write a series' term into any row that may
    read it (311 none-long: the pods' limit as -0.51 x it on ready's outflow, the start left 0.015 x pending; the
    queue's limit on mem's drain); those terms are dropped, and the limited flow is added where it is missing,
    at the coefficient the offer fitted on the source's row. The later passes repair the rows around it."""
    if not cap or not isinstance(result, dict) or not result.get("flows"):
        return result
    caps = [cap] + list(cap.get("more") or [])
    out = copy.deepcopy(result)
    notes = []
    for c in caps:
        name, src, dst = c["name"], c["source"], c.get("to")
        flows = []
        has = False
        for f in out["flows"]:
            r = f.get("rate") or {}
            terms = [{"stock": r.get("stock"), "k": r.get("k")}] if r.get("form") == "proportional" else \
                list(r.get("terms") or []) if r.get("form") == "linear" else []
            if not any(t.get("stock") == name for t in terms) or f.get("byTime"):
                flows.append(f)
                continue
            if f.get("from") == src and f.get("to") == dst:
                has = True
                flows.append(f)
                continue
            rest = [t for t in terms if t.get("stock") != name]
            notes.append(f"{name} dropped from {f.get('from') or 'outside'} -> {f.get('to') or 'outside'}")
            const = float(r.get("c") or 0.0) if r.get("form") == "linear" else 0.0
            if not rest and not const:
                continue
            g = copy.deepcopy(f)
            g["rate"] = {"form": "linear", "c": const, "terms": rest} if rest else {"form": "constant", "value": const}
            g.pop("rates", None)
            flows.append(g)
        if not has and dst is not None and c.get("k", 0) > 0:          # a move (an outflow may not be declared)
            flows.append({"id": f"limit_{src}_{dst or 'out'}", "from": src, "to": dst, "ratio": 1,
                          "rate": {"form": "linear", "c": 0, "terms": [{"stock": name, "k": float(c["k"])}]}})
            notes.append(f"{src} -> {dst or 'outside'} added at {float(c['k']):.4g} x {name}")
        out["flows"] = flows
    if notes:
        out["capmin_placed"] = notes
    return out


def plain_cap(cap: dict | None) -> dict | None:
    """The first limit alone where it is a plain MIN(X, theta Y) (what oefit can run), else None."""
    if not cap or cap.get("room"):
        return None
    return {k: v for k, v in cap.items() if k != "more"}


def _min_text(k: float, cap: dict) -> str:
    x, y, th = cap["source"], cap["cap"], cap["theta"]
    if cap.get("room"):
        z, b = cap["room"], cap["beta"]
        if k >= 0:
            return f"min({k!r} * {x}, max(0, {k * th * b!r} * {y} + {-k * th!r} * {z}))"
        return f"{k!r} * min({x}, max(0, {th * b!r} * {y} + {-th!r} * {z}))"
    return f"min({k!r} * {x}, {k * th!r} * {y})" if k >= 0 else f"{k!r} * min({x}, {th!r} * {y})"


def _expr(rate: dict, caps: dict) -> dict:
    """A linear rate with terms reading offered series, as an expression with each MIN written out."""
    form = rate.get("form")
    if form == "proportional":
        terms, c = [{"stock": rate.get("stock"), "k": rate.get("k", 0.0)}], 0.0
    elif form == "linear":
        terms, c = list(rate.get("terms") or []), float(rate.get("c") or 0.0)
    else:
        return rate
    if not any(t.get("stock") in caps for t in terms):
        return rate
    parts = [repr(c)] if c else []
    for t in terms:
        k = float(t.get("k") or 0.0)
        if t.get("stock") in caps:
            parts.append(_min_text(k, caps[t.get("stock")]))
        else:
            parts.append(f"{k!r} * {t.get('stock')}")
    return {"form": "expr", "expr": " + ".join(parts) or "0"}


def restore(result: dict, cap: dict | None) -> dict:
    """The strategy's answer with every rate that reads an offered series written as its MIN."""
    if not cap or not isinstance(result, dict):
        return result
    caps = {c["name"]: c for c in [cap] + list(cap.get("more") or [])}
    out = copy.deepcopy(result)
    for n, f in enumerate(out.get("flows") or []):
        for g in f.get("byTime") or []:
            if g.get("rate"):
                g["rate"] = _expr(g["rate"], caps)
        if f.get("rate"):
            f["rate"] = _expr(f["rate"], caps)
        if f.get("rates"):
            f["rates"] = [_expr(r, caps) for r in f["rates"]]
        if f.get("input") in caps:
            f.pop("input", None)
        rates = [g.get("rate") or {} for g in f.get("byTime") or []] + [f.get("rate") or {}]
        if any(r.get("form") == "expr" for r in rates):
            f.setdefault("id", f"capmin{n}")             # an expression flow is named (the engine's compiler wants one)
    keys = ("source", "cap", "room", "beta", "to", "theta", "gain", "kink", "share")
    out["capmin"] = {k: cap[k] for k in keys if k in cap}
    if cap.get("more"):
        out["capmin"]["more"] = [{k: c[k] for k in keys if k in c} for c in cap["more"]]
    return out


def wrap(identify, stocks: list[dict], run: dict, opts: dict | None, *args, **kw) -> dict:
    """identify(stocks, run, opts) with a capacity limit offered where the data show one."""
    o, cap = offer(stocks, run, opts)
    return restore(identify(stocks, run, o, *args, **kw), cap)
