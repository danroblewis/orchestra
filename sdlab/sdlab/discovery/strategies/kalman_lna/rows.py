"""Each stock's row read off the data, and the flows rebuilt where the answer misses it (kubernetes 309, 2026-10-21).

docs/research/fixes/309-kalman_lna.md. The strategy's answer is a set of flows; the flows touching a stock S
give S's row: its one-step change as a function of the levels. Where the answer's row is far from what the
data show (a near-collinear set of levels let the search pick the wrong readers; or a flow floored at 0,
`max(0, B . x)`, that a linear row can only draw a proxy for), the stock's row is read off the data directly
and the flows touching it are rebuilt from the rows:

1. Rows. For every measured stock, two forms are fitted to its one-step change (less announced injections),
   reading every measured non-final stock, every measured input and a constant:
   - linear: the best sparse subset (every subset up to SUB terms, then forward steps up to MOST_TERMS);
   - linear + one floored term on a side the boundary allows (an outside inflow max(0, B . x), or an
     outflow): the always-on part fitted by trimmed least squares on every support up to two readers
     (the steps where the floored term is off fit it exactly), the floored term's readers searched on the
     steps it acts, then both refitted jointly with the active steps re-read from B . x > 0 until stable.
   The best by Gaussian BIC (the rounding of the data as a floor) is the stock's row.
2. Which stocks. A stock is rebuilt where its row beats the answer's flows on it by BIC + PRICE log T and
   explains EXPLAINED of its change's squares; a stock joined to a rebuilt one by a flow is rebuilt too
   where its own row is not worse than its answer (so a move is never cut on one side only). Flows
   between rebuilt stocks and the others stay, and the rebuilt rows are refitted on the change they leave.
3. Flows from rows. A positive term reading X in T's row, X a rebuilt stock in T's unit with a drain of
   its own (a negative self term) at least that large, is a move X -> T (the largest first); what is left
   of a drain is X's outflow to outside; every other term is an outside link on the side its sign gives
   (one flow per side: the positive terms in, the negative out; the floored term its own side, alone).
   A side the declared boundary does not allow removes the stock from the rebuild.
4. The rebuild is kept only where, over the rebuilt stocks, the new flows beat the answer's by BIC +
   PRICE log T. The same rule for every case; nothing reads the case or its truth.

To adopt it in another strategy: copy this file into the package and call
`result = rows.revise(result, stocks, run, opts)` on the answer after any MIN or expression is written back
and before a controller pass (tracker.py): the controller then reads the rebuilt neighbours. Self-contained.
"""

from __future__ import annotations

import copy
import itertools
import math
import time

import numpy as np

PRICE = 6.0            # the margin a rebuild must win by, in log T
RESOLUTION = 1e-8      # a residual variance below this share of the mean squared change is rounding
EXPLAINED = 0.5        # a rebuilt row explains at least this share of the stock's change's squares (counting noise leaves the rest)
SUB = 3                # every subset up to this many readers is tried
MOST_TERMS = 5         # then forward steps up to this many
BASE_SUB = 2           # the always-on part of a floored row: every support up to this many readers
MIN_ON = 5             # a floored term acts on at least this many steps
TIME = 40.0            # seconds for the whole pass
TOL_MOVE = 0.02        # a move may take this share more than the source's drain (rounding)
REPAIRS = 3            # rounds of refitting a row that needs a side the boundary lacks
LEFT = 1e-4            # what a drain leaves below this share of itself after its moves is rounding


def _rate_value(rate: dict, state: dict) -> float | None:
    form = (rate or {}).get("form")
    if form == "proportional":
        return float(rate.get("k") or 0.0) * state.get(rate.get("stock"), 0.0)
    if form == "linear":
        return float(rate.get("c") or 0.0) + sum(float(t.get("k") or 0.0) * state.get(t.get("stock"), 0.0)
                                                 for t in rate.get("terms") or [])
    if form == "constant":
        return float(rate.get("value", rate.get("c", 0.0)) or 0.0)
    if form == "expr":
        try:
            return float(eval(rate["expr"], {"__builtins__": {}}, {"min": min, "max": max, "ceil": math.ceil,
                                                                 "abs": abs, **state}))
        except Exception:                                  # noqa: BLE001 (an expression this reader cannot run)
            return None
    return None


def _amounts(f: dict, states: list[dict], t_end: np.ndarray) -> np.ndarray | None:
    """The flow's amount on each step (floored at 0), pieces and eras included; None where it cannot run."""
    if f.get("effects") or f.get("uses"):
        return None
    T = len(states)
    out = np.zeros(T)
    if f.get("inflow"):
        for k in range(T):
            seg = next((g for g in f["inflow"] if g["from"] <= t_end[k] <= g["to"]), f["inflow"][-1])
            out[k] = max(0.0, float(seg.get("value") or 0.0))
        return out
    segs = f.get("byTime")
    for k, s in enumerate(states):
        rate = f.get("rate") or {}
        if segs:
            rate = next((g for g in segs if g["from"] <= t_end[k] <= g["to"]), segs[-1]).get("rate") or {}
        v = _rate_value(rate, s)
        if v is None:
            return None
        out[k] = max(0.0, v)
    return out


def _numbers(f: dict) -> int:
    if f.get("inflow"):
        return len(f["inflow"])
    if f.get("byTime"):
        return sum(_numbers({"rate": g.get("rate")}) for g in f["byTime"])
    r = f.get("rate") or {}
    if r.get("form") == "linear":
        return len(r.get("terms") or []) + (1 if r.get("c") else 0)
    if r.get("form") == "expr":
        return max(1, r.get("expr", "").count("."))
    return 1


def _data(stocks: list[dict], run: dict, opts: dict):
    ids = [s["id"] for s in stocks]
    t = np.asarray(run["t"], dtype=float)
    L = np.array([np.asarray(run["levels"].get(i, []), dtype=float) for i in ids])
    if L.ndim != 2 or L.shape[1] < 30 or not np.isfinite(L).all() or np.any(np.diff(t) != 1):
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
    return ids, dy, read, inputs, states, t[1:]


def _lstsq(A: np.ndarray, y: np.ndarray):
    b, *_ = np.linalg.lstsq(A, y, rcond=None)
    e = y - A @ b
    return b, float(e @ e)


def _sparse(X: np.ndarray, y: np.ndarray, floor: float, cols: list[int] | None = None):
    """(bic, support, coefs, sse) of the best sparse linear fit of y on X's columns (BIC; floor: rounding)."""
    n, p = X.shape
    cols = list(range(p)) if cols is None else cols
    logn = math.log(max(n, 2))
    bic = lambda sse, k: n * math.log((sse + floor) / n) + k * logn  # noqa: E731
    best = (bic(float(y @ y), 0), (), np.zeros(0), float(y @ y))
    by_size = {}
    for k in range(1, min(SUB, len(cols)) + 1):
        for sub in itertools.combinations(cols, k):
            b, sse = _lstsq(X[:, sub], y)
            if k not in by_size or sse < by_size[k][3]:
                by_size[k] = (bic(sse, k), sub, b, sse)
    for k, got in by_size.items():
        if got[0] < best[0]:
            best = got
    cur = by_size.get(min(SUB, len(cols)))
    while cur is not None and len(cur[1]) < min(MOST_TERMS, len(cols)):
        step = None
        for j in cols:
            if j in cur[1]:
                continue
            sub = tuple(sorted(cur[1] + (j,)))
            b, sse = _lstsq(X[:, sub], y)
            if step is None or sse < step[3]:
                step = (bic(sse, len(sub)), sub, b, sse)
        if step is None or step[3] >= cur[3] * (1 - 1e-9):
            break
        cur = step
        if cur[0] < best[0]:
            best = cur
    return best


def _trimmed(A: np.ndarray, y: np.ndarray, keep: float = 0.5, rounds: int = 6) -> np.ndarray:
    """Least trimmed squares: the half of the informative steps (those where a reader is not 0) it fits best."""
    b, _ = _lstsq(A, y)
    info = np.flatnonzero(np.any(A != 0, axis=1))
    if len(info) < A.shape[1] + 2:
        return b
    for _ in range(rounds):
        r = np.abs(y[info] - A[info] @ b)
        idx = info[np.argsort(r)[: max(A.shape[1] + 2, int(keep * len(info)))]]
        b, _ = _lstsq(A[idx], y[idx])
    return b


def _floored(X: np.ndarray, y: np.ndarray, sign: float, floor: float, deadline: float, a_cols: list[int] | None = None):
    """(bic, base support, a, floored support, b, sse) of y = X_A a + sign max(0, X_B b); None where none fits."""
    n, p = X.shape
    logn = math.log(max(n, 2))
    best = None
    res = math.sqrt(floor / n)
    a_cols = list(range(p)) if a_cols is None else a_cols
    supports = [()] + [s for k in range(1, BASE_SUB + 1) for s in itertools.combinations(a_cols, k)]
    for A in supports:
        if time.monotonic() > deadline:
            break
        a = _trimmed(X[:, A], y) if A else np.zeros(0)
        r = y - (X[:, A] @ a if A else 0.0)
        small = np.abs(r) <= np.quantile(np.abs(r), 0.5)
        mad = float(np.median(np.abs(r[small]))) if small.any() else 0.0
        tol = max(4.0 * 1.4826 * mad, 10 * res, 1e-9)
        on = sign * r > tol
        if int(on.sum()) < MIN_ON:
            continue
        for B, b in _hinge_readers(X, r, on, sign, floor, n, logn):
            got = _joint(X, y, A, a, B, b, sign, floor, n, logn)
            if got is not None and (best is None or got[0] < best[0]):
                best = got
    while best is not None:                                  # terms of either part that do not pay are dropped
        _, A, a, B, b, _ = best
        trial = None
        for drop in [("A", j) for j in range(len(A))] + [("B", j) for j in range(len(B))] * (len(B) > 1):
            A2 = tuple(x for i, x in enumerate(A) if not (drop[0] == "A" and i == drop[1]))
            B2 = tuple(x for i, x in enumerate(B) if not (drop[0] == "B" and i == drop[1]))
            a2 = np.array([v for i, v in enumerate(a) if not (drop[0] == "A" and i == drop[1])])
            b2 = np.array([v for i, v in enumerate(b) if not (drop[0] == "B" and i == drop[1])])
            got = _joint(X, y, A2, a2, B2, b2, sign, floor, n, logn)
            if got is not None and got[0] < (trial or best)[0]:
                trial = got
        if trial is None:
            break
        best = trial
    return best


def _joint(X, y, A, a, B, b, sign, floor, n, logn):
    """(bic, A, a, B, b, sse) of both parts refitted jointly, the active steps re-read from X_B b > 0."""
    on1 = None
    for _ in range(12):
        on2 = X[:, B] @ b > 0
        if int(on2.sum()) < MIN_ON:
            return None
        M = np.hstack([X[:, A], sign * X[:, B] * on2[:, None]])
        coef, _ = _lstsq(M, y)
        a, b = coef[: len(A)], coef[len(A):]
        if on1 is not None and np.array_equal(on2, on1):
            break
        on1 = on2
    pred = (X[:, A] @ a if len(A) else 0.0) + sign * np.maximum(0.0, X[:, B] @ b)
    sse = float(((y - pred) ** 2).sum())
    return n * math.log((sse + floor) / n) + (len(A) + len(B)) * logn, A, a, B, b, sse


def _hinge_readers(X, r, on, sign, floor, n, logn, top: int = 3):
    """The floored term's best readers for what the always-on part leaves (r): each subset fitted on the steps
    it acts (on) and scored on every step (off steps must read B . x <= 0); the top few (support, coefs)."""
    p = X.shape[1]
    got = []
    Xo, yo = X[on], sign * r[on]
    for k in range(1, min(SUB, p) + 1):
        for sub in itertools.combinations(range(p), k):
            b, _ = _lstsq(Xo[:, sub], yo)
            sse = float(((sign * r - np.maximum(0.0, X[:, sub] @ b)) ** 2).sum())
            got.append((n * math.log((sse + floor) / n) + k * logn, sub, b))
    got.sort(key=lambda g: g[0])
    return [(g[1], g[2]) for g in got[:top]]


def _sides(S: str, declared: bool, bd: dict) -> set[str]:
    if not declared:
        return {"in", "out"}
    d = bd.get(S) or {}
    return {s for s in ("in", "out") if d.get(s)}


def revise(result: dict, stocks: list[dict], run: dict, opts: dict | None) -> dict:
    """The answer with the flows of the stocks whose rows it misses rebuilt from rows read off the data."""
    if not isinstance(result, dict) or not result.get("flows"):
        return result
    if result.get("lag") or result.get("scales") or (result.get("kalman") or {}).get("reading"):
        return result                                        # the answer reads the data in another frame
    opts = opts or {}
    got = _data(stocks, run, opts)
    if got is None:
        return result
    ids, dy, read, inputs, states, t_end = got
    deadline = time.monotonic() + TIME
    T = dy.shape[1]
    logT = math.log(T)
    unit = {s["id"]: s.get("unit") or "" for s in stocks}
    final = {s["id"] for s in stocks if s.get("final")}
    declared = bool(run.get("boundary_declared"))
    bd = run.get("boundary") or {}
    readers = [i for i, s in enumerate(ids) if s not in final]
    names = [ids[i] for i in readers] + list(inputs) + [None]
    X = np.vstack([read[i] for i in readers] + [inputs[k] for k in inputs] + [np.ones(T)]).T
    keep_cols = [j for j in range(X.shape[1]) if np.ptp(X[:, j]) > 0 or names[j] is None]
    X, names = X[:, keep_cols], [names[j] for j in keep_cols]
    flows = list(result["flows"])
    amts = [_amounts(f, states, t_end) for f in flows]
    floor = {S: RESOLUTION * float(np.mean(dy[i] ** 2)) * T + 1e-300 for i, S in enumerate(ids)}
    bic = lambda sse, k, S: T * math.log((sse + floor[S]) / T) + k * logT  # noqa: E731

    def answer(S, skip=frozenset()):
        """(sse, numbers) of the answer's flows on S, flows in skip left out; None where one cannot run."""
        i = ids.index(S)
        pred, k = np.zeros(T), 0
        for n, f in enumerate(flows):
            if n in skip or S not in (f.get("from"), f.get("to")):
                continue
            if amts[n] is None:
                return None
            pred += amts[n] if f.get("to") == S else -float(f.get("ratio") or 1) * amts[n]
            k += _numbers(f)
        return float(((dy[i] - pred) ** 2).sum()), k

    def row(S, y, self_k=None, exclude=frozenset()):
        """The best row for S's change y: {bic, sse, lin: {name: k}, hinge: (side, {name: k}) | None}; with
        self_k, S's own term is fixed at self_k (its drain is what its moves take) and the rest is searched;
        the always-on part reads no name in exclude (links on a side the boundary does not allow)."""
        yy, cols = y, [j for j, n in enumerate(names) if n not in exclude]
        if self_k is not None and S in names and S not in exclude:
            j = names.index(S)
            yy = y - self_k * X[:, j]
            cols.remove(j)                                   # S's own term fixed; its floored term may read it
        lin = _sparse(X, yy, floor[S], cols)
        out = {"bic": lin[0], "sse": lin[3], "lin": dict(zip([names[j] for j in lin[1]], map(float, lin[2]))),
               "hinge": None}
        if lin[3] > floor[S] and S not in final:
            for side in sorted(_sides(S, declared, bd)):
                h = _floored(X, yy, 1.0 if side == "in" else -1.0, floor[S], deadline, cols)
                if h is not None and h[0] < out["bic"] - 1e-9:
                    out = {"bic": h[0], "sse": h[5], "lin": dict(zip([names[j] for j in h[1]], map(float, h[2]))),
                           "hinge": (side, dict(zip([names[j] for j in h[3]], map(float, h[4]))))}
        if self_k is not None:
            out["lin"][S] = out["lin"].get(S, 0.0) + self_k
            out["bic"] += logT
        return out

    rows, old = {}, {}
    for i, S in enumerate(ids):
        if np.ptp(read[i]) <= 0 and not np.any(dy[i]):
            continue
        a = answer(S)
        if a is None:
            continue
        old[S] = a
        rows[S] = row(S, dy[i])
    if time.monotonic() > deadline:
        return result
    if opts.get("rows_trace"):
        for S, r in rows.items():
            print("rows", S, round(r["bic"], 1), round(bic(*old[S], S), 1), r["sse"], old[S], r["lin"], r["hinge"])
    wins = {S for S, r in rows.items()
            if r["bic"] + PRICE * logT < bic(*old[S], S) and r["sse"] <= (1 - EXPLAINED) * float(dy[ids.index(S)] @ dy[ids.index(S)])}
    if not wins:
        return result
    B = set(wins)
    fine = {S for S in old if old[S][0] <= (1 - EXPLAINED) * float(dy[ids.index(S)] @ dy[ids.index(S)])}
    while True:                                              # a stock joined to a rebuilt one by a flow joins
        grow = set()
        for n, f in enumerate(flows):
            a, b = f.get("from"), f.get("to")
            if a is None or b is None or (a in B) == (b in B):
                continue
            X_ = b if a in B else a
            if X_ in rows and rows[X_]["bic"] <= bic(*old[X_], X_) + PRICE * logT:
                grow.add(X_)
        if not grow:
            break
        B |= grow
    for _ in range(len(ids) + 1):
        built = _build(B, flows, amts, rows, ids, dy, X, names, unit, final, declared, bd, row, T, fine, floor)
        if built is None:
            return result
        new_flows, bad = built
        if not bad:
            break
        B -= bad
        if not B:
            return result
    else:
        return result
    new_amts = [_amounts(f, states, t_end) for f in new_flows]
    tot_old = tot_new = 0.0
    for S in B:
        i = ids.index(S)
        pred, k = np.zeros(T), 0
        for n, f in enumerate(new_flows):
            if S not in (f.get("from"), f.get("to")):
                continue
            if new_amts[n] is None:
                return result
            pred += new_amts[n] if f.get("to") == S else -float(f.get("ratio") or 1) * new_amts[n]
            k += _numbers(f)
        tot_new += bic(float(((dy[i] - pred) ** 2).sum()), k, S)
        tot_old += bic(*old[S], S)
    if not tot_new + PRICE * logT < tot_old:
        return result
    out = copy.copy(result)
    out["flows"] = new_flows
    out["rows"] = {"rebuilt": sorted(B), "bic": [tot_old, tot_new]}
    return out


def _rate(terms: dict[str | None, float]) -> dict:
    c = float(terms.get(None, 0.0))
    links = [{"stock": s, "k": float(k)} for s, k in terms.items() if s is not None]
    if not links:
        return {"form": "constant", "value": c}
    if len(links) == 1 and not c:
        return {"form": "proportional", "stock": links[0]["stock"], "k": links[0]["k"]}
    return {"form": "linear", "c": c, "terms": links}


def _flow(a, b, terms) -> dict:
    r = _rate(terms)
    return {"from": a, "to": b, "ratio": 1, "rate": r, "rates": [dict(r)], "id": f"rows_{a}_{b}"}


def _pair(R, B, unit, final):
    """Moves, outside links in and out, each stock's drain and what its moves leave of it."""
    drain = {S: max(0.0, -R[S]["lin"].get(S, 0.0)) for S in B}
    moves, link_in, link_out = [], {S: {} for S in B}, {S: {} for S in B}
    cands = []
    for Tt in B:
        for x, k in R[Tt]["lin"].items():
            if x == Tt:
                continue
            if k > 0 and x in B and unit.get(x) == unit.get(Tt) and x not in final:
                cands.append((k, x, Tt))
            elif k > 0:
                link_in[Tt][x] = k
            else:
                link_out[Tt][x] = -k
    left = dict(drain)
    for k, x, Tt in sorted(cands, key=lambda c: -c[0]):
        if k <= left[x] * (1 + TOL_MOVE) + 1e-12:
            moves.append((x, Tt, k))
            left[x] = max(0.0, left[x] - k)
        else:
            link_in[Tt][x] = k
    return moves, link_in, link_out, drain, left


def _build(B, flows, amts, rows, ids, dy, X, names, unit, final, declared, bd, row, T, fine, floor):
    """(flows, stocks to leave out) of the rebuild over B; None where a flow cannot run."""
    series = {n: X[:, j] for j, n in enumerate(names)}
    kept, kept_on = [], {S: np.zeros(T) for S in B}
    for n, f in enumerate(flows):
        a, b = f.get("from"), f.get("to")
        if a not in B and b not in B:
            kept.append(f)
            continue
        if a is None or b is None or (a in B and b in B):
            continue                                         # rebuilt
        if amts[n] is None:
            return None
        other = b if a in B else a
        if other not in fine:
            continue                                         # the other stock's answer misses it too: cut
        kept.append(f)                                       # between a rebuilt stock and a fitted one: stays
        if b in B:
            kept_on[b] += amts[n]
        if a in B:
            kept_on[a] -= float(f.get("ratio") or 1) * amts[n]
    R, y = {}, {}
    for S in B:
        y[S] = dy[ids.index(S)] - kept_on[S]
        R[S] = row(S, y[S]) if np.any(kept_on[S]) else rows[S]
    fixed, excl = {}, {S: set() for S in B}
    for _ in range(REPAIRS + 1):
        moves, link_in, link_out, drain, left = _pair(R, B, unit, final)
        for S in B:                                          # a link that moves S by less than the data's
            res = 10.0 * math.sqrt(floor[S] / T)             # rounding is rounding, not a flow
            for links in (link_in[S], link_out[S]):
                for x in [x for x, k in links.items() if np.max(np.abs(k * series[x])) < res]:
                    del links[x]
        redo = []
        for S in B:                                          # a row that needs a side the boundary lacks is
            sides = _sides(S, declared, bd)                  # refitted without those links (and, with no
            off = set()                                      # outflow, with its drain fixed at its moves')
            if "in" not in sides:
                off |= {x for x in link_in[S] if x != S}
                if R[S]["lin"].get(S, 0.0) > 0:
                    off.add(S)                               # growth in proportion to itself is an inflow
            if "out" not in sides:
                off |= {x for x in link_out[S] if x != S}
            self_k = fixed.get(S)
            if "out" not in sides and left[S] > LEFT * drain[S] and drain[S] > left[S]:
                self_k = -(drain[S] - left[S])
            if off - excl[S] or self_k != fixed.get(S):
                excl[S] |= off
                if self_k is not None:
                    fixed[S] = self_k
                redo.append(S)
        if not redo:
            break
        for S in redo:
            R[S] = row(S, y[S], fixed.get(S), frozenset(excl[S]))
    bad = set()
    for S in B:
        self_k = R[S]["lin"].get(S, 0.0)
        if self_k > 0:
            link_in[S][S] = self_k
        if left[S] > LEFT * drain[S]:
            link_out[S][S] = left[S]
        sides = _sides(S, declared, bd)
        h = R[S]["hinge"]
        need = {"in": bool(link_in[S]), "out": bool(link_out[S])}
        if h is not None:
            if need[h[0]]:
                bad.add(S)                                   # one flow per side: the floored term alone
                continue
            need[h[0]] = True
        if any(v and s not in sides for s, v in need.items()):
            bad.add(S)
    if bad:
        return flows, bad
    new = [(x, Tt, {x: k}, False) for x, Tt, k in moves]
    for S in sorted(B):
        h = R[S]["hinge"]
        if link_in[S]:
            new.append((None, S, dict(link_in[S]), False))
        if link_out[S]:
            new.append((S, None, dict(link_out[S]), False))
        if h is not None:
            new.append((None, S, dict(h[1]), True) if h[0] == "in" else (S, None, dict(h[1]), True))
    new = _together(new, B, y, R, series, floor, T)
    out = list(kept)
    for a, b, terms, _ in new:
        out.append(_flow(a, b, terms))
    return out, set()


def _together(new, B, y, R, series, floor, T, rounds: int = 4):
    """Every rebuilt flow's numbers refitted at once over the rebuilt stocks' rows (a move's number shows in
    both its stocks), each row weighted by its own residual scale; a floored flow's active steps re-read."""
    order = sorted(B)
    w = {S: 1.0 / math.sqrt(max(R[S]["sse"], floor[S]) / T) for S in order}
    yy = np.concatenate([w[S] * y[S] for S in order])
    params = [(n, x) for n, (_, _, terms, _) in enumerate(new) for x in terms]
    if not params:
        return new
    cur = [dict(t) for _, _, t, _ in new]

    def design(cur):
        M = np.zeros((len(order) * T, len(params)))
        for c, (n, x) in enumerate(params):
            a, b, _, hinged = new[n]
            col = series[x].copy()
            if hinged:
                col = col * (sum(k * series[z] for z, k in cur[n].items()) > 0)
            for r, S in enumerate(order):
                if S == b:
                    M[r * T:(r + 1) * T, c] += w[S] * col
                if S == a:
                    M[r * T:(r + 1) * T, c] -= w[S] * col
        return M

    def sse(cur):
        tot = 0.0
        for S in order:
            pred = np.zeros(T)
            for n, (a, b, _, _) in enumerate(new):
                if S in (a, b):
                    amt = np.maximum(0.0, sum(k * series[z] for z, k in cur[n].items()))
                    pred += amt if S == b else -amt
            tot += float((w[S] * (y[S] - pred)) @ (w[S] * (y[S] - pred)))
        return tot

    best, best_sse = cur, sse(cur)
    for _ in range(rounds):
        coef, *_ = np.linalg.lstsq(design(best), yy, rcond=None)
        trial = [dict(t) for t in best]
        for c, (n, x) in enumerate(params):
            trial[n][x] = float(coef[c])
        got = sse(trial)
        if not got < best_sse * (1 - 1e-9):
            break
        best, best_sse = trial, got
    return [(a, b, best[n], h) for n, (a, b, _, h) in enumerate(new)]
