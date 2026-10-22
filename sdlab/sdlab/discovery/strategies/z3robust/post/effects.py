"""Table-effect flows: a flow that reads one stock and is switched on by the level of another (k8s-310, 2026-10-21).

A rate R x effect(X), with effect a table of X (Sterman's lookup), is zero or small over most of X's
range and grows past a threshold: pods killed in proportion to the pods ready once memory nears its
limit, a drain that opens as a level rises. The program's columns are linear in the levels, so such a
flow is invisible to it: its amounts are spikes on the few steps where X is past the threshold, and the
program explains them by a small steady flow where none moves, or leaves them.

The mechanism, the same for every stock:
- every candidate flow the boundary allows: a move between two measured stocks of one unit (reading
  its source), an outside inflow on a side declared "estimate" (reading a measured stock of the
  stock's unit, or nothing), an outside outflow on such a side (reading its stock); and a move whose
  amount a counter also counts (a counted move: the same amount fed from outside into a counter of the
  move's unit, the counter's declared inflow, as `flow(name)` counts a flow). Each is tried against every
  measured level X that is not a counter (an effect may read any unit);
- the effect is a sum of ramps, s max(0, X - h) (or s max(0, h - X)), so for a given hinge h the amount
  R x ramp is one column, fitted by least squares with the plain flows on the rows it touches (their
  numbers refitted, unfloored as the program fits them). A plain flow on the candidate's own ends (the
  same pair, or the counter's outside inflow) is the one it would replace: the comparison is with it
  in, the candidate is without it. Hinges are tried on a grid of X's quantiles, the best polished
  between its neighbours, then a second hinge (a bend) is tried;
- a candidate is kept when BIC over the rows it touches beats the answer by more than MARGIN, it moves
  something on at least EVENTS steps, and it explains at least SHARE of the misfit of one row it
  touches (a flow that only trims a misfit left by some other missing structure is a proxy, not a
  flow); the best is taken and the search runs again (at most MAX_FLOWS flows).
The effect is written as a table ("shape": "table") on a rate of 1 x R: points at the hinges and beyond
the run's range, the engine interpolating between them and holding the last value past them.
"""

from __future__ import annotations

import numpy as np
from scipy.optimize import lsq_linear, minimize_scalar

from .hinge import _amount, _env, _plain, _resolution
from .steps import Steps

MARGIN = 10.0        # BIC units an effect flow must win by
EVENTS = 5           # it moves something on at least this many steps
SHARE = 0.5          # and explains at least this share of one touched row's misfit
GRID = 40            # hinges tried: this many quantiles of X (from LOW to HIGH)
LOW, HIGH = 0.02, 0.995
MAX_FLOWS = 3        # effect flows added at most per call
FLOOR = 1e-5         # a row's misfit is at least this share of its typical change (and the levels' rounding)
QUIET = 2.0          # a row whose misfit is within this many times its rounding noise is explained (_quiet)
MATERIAL = 1e-5      # an effect flow moves at least this share of the gross amount through its rows (rms): the numbers are
                     # written to 6 digits, so a smaller flow fits their rounding (k8s-312: 7e-7 x inflight on queue's row)
DEBUG = bool(__import__("os").environ.get("Z3ROBUST_DEBUG"))


def _num(v: float) -> float:
    return float(f"{v:.6g}")


def _ramp(x: np.ndarray, h: float, up: bool) -> np.ndarray:
    return np.maximum(0.0, x - h) if up else np.maximum(0.0, h - x)


def _table(x: np.ndarray, hs: list, ss: list, up: bool) -> list:
    """The effect sum_m s_m ramp(x, h_m) as table points: at the hinges, and a range beyond the run's
    levels (the engine holds the last point's value past it)."""
    lo, hi = float(np.min(x)), float(np.max(x))
    span = max(hi - lo, 1e-9)
    f = lambda v: float(sum(s * (max(0.0, v - h) if up else max(0.0, h - v)) for h, s in zip(hs, ss)))  # noqa: E731
    pts = sorted({*map(float, hs), lo - span, hi + span})
    return [[_num(p), _num(f(p))] for p in pts]


def _quiet(st: Steps, flows: list[dict], env: dict, amounts: list) -> set:
    """(k8s-312) The rows whose misfit under the flows as they stand is within QUIET times their rounding noise: each
    one-step change's own rounding, and the rounding of every level the flows read carried through their slopes (a
    MIN arm 40 x ready, ready written to 4 decimals, misfits by 40 x that). The levels are written in one format, so a
    level's rounding is the run's finest resolution (a stock whose levels happen to be whole is not rounded to 1).
    Such a row offers no misfit for an effect flow to explain (on 312 a slope of 1e-6 on queue's row fitted it)."""
    if st.counts:
        return set()
    res = [r for r in (_resolution(st.L[i]) for i in range(len(st.ids))) if r > 0]
    if not res:
        return set()
    r0 = min(res)
    pos = {s: i for i, s in enumerate(st.ids)}

    def net(env2, amts=None):
        out = np.zeros_like(st.dy)
        for i, f in enumerate(flows):
            a = amts[i] if amts is not None else (_amount(f, st, env2) if amounts[i] is not None else None)
            if a is None:
                continue
            if f.get("from") in pos:
                out[pos[f["from"]]] -= a
            if f.get("to") in pos:
                out[pos[f["to"]]] += a
        return out

    base = net(env, amounts)
    var = np.zeros_like(st.dy)
    for x in st.ids:
        e2 = dict(env)
        e2[x] = np.asarray(env[x], float) + r0 / 2.0
        var += (net(e2) - base) ** 2 / 3.0                  # uniform rounding: var r0^2 / 12 = (half-step change)^2 / 3
    e = st.dy - base
    noise = var.sum(axis=1) + st.T * r0 ** 2 / 6.0
    return {i for i in range(len(st.ids)) if float(e[i] @ e[i]) <= QUIET * noise[i]}


class _Rows:
    """One candidate's least squares: the rows it touches, what the fixed flows leave of their changes,
    the free plain flows' columns (weighted by each row's typical change), and those of the flows it
    would replace."""

    def __init__(self, st, flows, amounts, cand, scale, floor):
        src, dst, reader, counter = cand
        pos = {s: i for i, s in enumerate(st.ids)}
        self.ok = False
        self.rows = [pos[e] for e in dict.fromkeys((src, dst, counter)) if e in pos]
        ends = {(src, dst)} | ({(None, counter)} if counter else set())
        self.drop = [i for i, f in enumerate(flows) if (f.get("from"), f.get("to")) in ends]
        # (k8s-310 counts-long) a counter's declared inflow may be a schedule (the program steps a constant to follow
        # kills): a counted move may replace it, the schedule held at its amounts in the comparison and charged its numbers
        held = [i for i in self.drop if _plain(flows[i]) is None]
        # (k8s-312) or a MIN the program wrote on the candidate's own pair (min(0.43 ready, 1.57 pending) standing in for kills):
        # held at its amounts in the answer's side and charged its numbers, as a schedule is
        own_min = lambda f: ((f.get("from"), f.get("to")) == (src, dst) and src is not None and dst is not None  # noqa: E731
                             and not f.get("effects") and not f.get("room_fit") and str((f.get("rate") or {}).get("expr") or "").startswith("min("))
        if any(not (((counter and (flows[i].get("from"), flows[i].get("to")) == (None, counter)) or own_min(flows[i]))
                    and not flows[i].get("effects") and amounts[i] is not None) for i in held):
            return
        n, rows = st.T, self.rows
        w = 1.0 / scale[rows]
        target = st.dy[rows].copy()
        free, dropped = [], []
        for i, f in enumerate(flows):
            e = [x for x in (f.get("from"), f.get("to")) if x in pos]
            if not {pos[x] for x in e} & set(rows):
                continue
            d = _plain(f)
            if i in held:
                continue
            if i in self.drop:
                dropped.append((f.get("from"), f.get("to"), d))
                continue
            if d is not None and all(pos[x] in rows for x in e):
                free.append((f.get("from"), f.get("to"), d))
                continue
            if amounts[i] is None:
                return
            for j, r in enumerate(rows):                       # what the fixed flow does to the row, off its change
                if st.ids[r] == f.get("from"):
                    target[j] += amounts[i]
                if st.ids[r] == f.get("to"):
                    target[j] -= amounts[i]

        def columns(fl):
            out = []
            for a, b, d in fl:
                for r in d:
                    c = np.zeros((len(rows), n))
                    for j, row in enumerate(rows):
                        if st.ids[row] == a:
                            c[j] -= st.series(r)
                        if st.ids[row] == b:
                            c[j] += st.series(r)
                    out.append((c * w[:, None]).ravel())
            return out

        self.B = columns(free)
        self.D = columns(dropped)
        self.y = (target * w[:, None]).ravel()
        fixed = np.zeros((len(rows), n))                         # the held schedules' amounts on their rows
        for i in held:
            for j, row in enumerate(rows):
                if st.ids[row] == flows[i].get("to"):
                    fixed[j] += amounts[i]
                if st.ids[row] == flows[i].get("from"):
                    fixed[j] -= amounts[i]
        self.held = (fixed * w[:, None]).ravel()
        self.held_n = sum(2 if own_min(flows[i]) else len(flows[i].get("byTime") or [1]) for i in held)
        self.sign = np.array([(-1.0 if st.ids[r] == src else 0.0) + (1.0 if st.ids[r] in (dst, counter) else 0.0) for r in rows])
        self.w, self.n, self.floor = w, n, floor[rows]
        self.R = st.series(reader)
        self.ok = True

    def bic(self, resid: np.ndarray, p: int) -> float:
        e = resid.reshape(len(self.rows), self.n)
        rss = np.maximum(np.sum(e * e, axis=1), self.n * self.floor ** 2)
        return float(np.sum(self.n * np.log(rss / self.n)) + p * np.log(self.n * len(self.rows)))

    def col(self, amt: np.ndarray) -> np.ndarray:
        return (self.sign[:, None] * amt[None, :] * self.w[:, None]).ravel()

    def fit(self, amts: list) -> tuple[float, np.ndarray, np.ndarray]:
        """BIC, the ramps' slopes (non-negative) and the residual, with these ramp amounts."""
        A = np.column_stack(self.B + [self.col(a) for a in amts])
        k = len(amts)
        lo = np.r_[np.full(A.shape[1] - k, -np.inf), np.zeros(k)]
        r = lsq_linear(A, self.y, bounds=(lo, np.full(A.shape[1], np.inf)), method="bvls")
        e = self.y - A @ r.x
        return self.bic(e, A.shape[1] + k), r.x[A.shape[1] - k:], e


def refine(flows: list[dict], stocks: list[dict], run: dict, opts: dict | None, skip=()) -> tuple[list[dict], dict]:
    opts = opts or {}
    st = Steps(stocks, run, opts)
    if st.T < 20 or not st.ids:
        return flows, {}
    env = _env(st)
    declared = bool(run.get("boundary_declared"))
    bd = run.get("boundary") or {}
    flows = [dict(f) for f in flows or []]
    scale = np.sqrt(np.mean(st.dy ** 2, axis=1)) + 1e-12
    res = np.zeros(len(st.ids)) if st.counts else np.array([_resolution(st.L[i]) for i in range(len(st.ids))])
    floor = np.maximum(FLOOR, res / np.sqrt(6.0) / scale)
    n = st.T
    skip = set(skip)
    drivers = [x for x in st.ids if x not in st.final] + sorted(st.inputs)
    grids = {}
    for x in drivers:
        v = st.series(x)
        g = np.unique(np.quantile(v, np.linspace(LOW, HIGH, GRID)))
        grids[x] = g[(g > v.min()) & (g < v.max())]

    def sides(s: str, side: str) -> bool:
        if declared:
            return "estimate" in ((bd.get(s) or {}).get(side) or [])
        return any((f.get("from"), f.get("to")) == ((None, s) if side == "in" else (s, None)) for f in flows)

    unit = lambda x: st.units.get(x)  # noqa: E731
    cands = []                                    # (src, dst, reader, counter)
    counters = [c for c in st.ids if c in st.final and c not in skip and sides(c, "in")]
    for a in st.ids:
        for b in st.ids:
            if a != b and a not in st.final and unit(a) and st.same_unit(a, b) and not ({a, b} & skip):
                cands.append((a, b, a, None))
                if b not in st.final:
                    cands += [(a, b, a, c) for c in counters if unit(c) == unit(a)]
    for s in st.ids:
        if s in skip:
            continue
        if sides(s, "in"):
            readers = [None] + [x for x in st.ids if x not in st.final and x not in skip and unit(x) and unit(x) == unit(s)]
            cands += [(None, s, r, None) for r in readers]
        if sides(s, "out") and s not in st.final:
            cands.append((s, None, s, None))
    notes = []
    flows, polished = _polish(st, flows, env, scale, floor, grids)
    if polished:
        notes.append({"polished": polished})
    for _ in range(MAX_FLOWS):
        amounts = [_amount(f, st, env) for f in flows]
        have = {(f.get("from"), f.get("to")) for f in flows if f.get("effects")}
        read = {}                                  # rows an effect flow already acts on: {row: the levels its effects read}
        for f in flows:
            for e in (f.get("from"), f.get("to")):
                if e in st.ids:
                    read.setdefault(e, set()).update(x.get("stock") for x in f.get("effects") or [])
        best, tops = None, []
        quiet = _quiet(st, flows, env, amounts)
        gross = np.zeros(len(st.ids))                    # each row's gross amount per step (rms over the steps)
        for f, a in zip(flows, amounts):
            if a is None:
                continue
            for e in (f.get("from"), f.get("to")):
                if e in st.ids:
                    gross[st.ids.index(e)] += float(np.sqrt(np.mean(a ** 2)))
        for cand in cands:
            src, dst, reader, counter = cand
            if (src, dst) in have or (counter and (None, counter) in have):
                continue
            rw = _Rows(st, flows, amounts, cand, scale, floor)
            if not rw.ok:
                continue
            B = np.column_stack(rw.B) if rw.B else np.zeros((len(rw.y), 0))
            Q = np.linalg.qr(B)[0] if B.shape[1] else np.zeros((len(rw.y), 0))
            r0 = rw.y - Q @ (Q.T @ rw.y)
            BD = np.column_stack(rw.B + rw.D) if rw.B + rw.D else np.zeros((len(rw.y), 0))
            QD = np.linalg.qr(BD)[0] if BD.shape[1] else np.zeros((len(rw.y), 0))
            yD = rw.y - rw.held
            eD = yD - QD @ (QD.T @ yD)
            base = rw.bic(eD, BD.shape[1] + rw.held_n)   # the answer as it stands (the replaced flows in, refitted; a held schedule as it is)
            rss0 = np.sum(eD.reshape(len(rw.rows), n) ** 2, axis=1)
            for x in drivers:
                if any(x in read.get(st.ids[r], ()) for r in rw.rows):
                    continue                           # an effect of x already acts on that row: a second is its adjustment
                xv = st.series(x)
                for up in (True, False):
                    for h in grids[x]:
                        amt = rw.R * _ramp(xv, h, up)
                        if int(np.sum(amt > 1e-9 * (np.abs(amt).max() + 1e-300))) < EVENTS:
                            continue
                        c = rw.col(amt)
                        cp = c - Q @ (Q.T @ c)
                        den = float(cp @ cp)
                        if den <= 0:
                            continue
                        s = float(cp @ r0) / den
                        if s <= 0:
                            continue
                        if not st.counts and float(np.sqrt(np.mean((s * amt) ** 2))) < MATERIAL * max(gross[r] for r in rw.rows):
                            continue
                        e1 = r0 - s * cp
                        b = rw.bic(e1, B.shape[1] + 2)
                        rss1 = np.sum(e1.reshape(len(rw.rows), n) ** 2, axis=1)
                        loud = [j for j, r in enumerate(rw.rows) if r not in quiet]
                        share = float(np.max(1.0 - rss1[loud] / np.maximum(rss0[loud], 1e-300))) if loud else 0.0
                        if DEBUG:
                            tops.append((round(base - b, 1), round(share, 3), cand, x, up, round(float(h), 3)))
                        if share >= SHARE and (best is None or base - b > best[0]):
                            best = (base - b, cand, x, up, float(h))
        if DEBUG:
            for z in sorted(tops, key=lambda z: -z[0])[:6]:
                print("  effect cand", z)
        if best is None or best[0] <= MARGIN:
            break
        gain, cand, x, up, h = best
        src, dst, reader, counter = cand
        rw = _Rows(st, flows, amounts, cand, scale, floor)
        hs, ss = _bend(rw, st.series(x), up, [h], grids[x])
        if not ss:
            break
        rate = {"form": "proportional", "stock": reader, "k": 1.0} if reader else {"form": "constant", "value": 1.0}
        eff = [{"stock": x, "shape": "table", "points": _table(st.series(x), hs, ss, up)}]
        new = [{"from": src, "to": dst, "ratio": 1, "id": f"z3robust:effect:{src or 'outside'}->{dst or 'outside'}", "rate": rate, "effects": eff}]
        new[0]["effect_fit"] = {"reader": reader, "up": up, "hinges": hs, **({"counter": counter} if counter else {})}
        if counter:
            new.append({"from": None, "to": counter, "ratio": 1, "id": f"z3robust:effect:outside->{counter}", "rate": dict(rate),
                        "effects": [dict(e) for e in eff], "counts": new[0]["id"]})
        flows = [g for i, g in enumerate(flows) if i not in rw.drop] + new   # the other flows' numbers stay the program's
        notes.append({"flow": f"{src or 'outside'}->{dst or 'outside'}", "counted_by": counter, "reads": reader or "1",
                      "effect_of": x, "hinges": [_num(v) for v in hs], "slopes": [_num(v) for v in ss], "gain": round(gain, 1),
                      "replaced": len(rw.drop)})
        if DEBUG:
            print("effect", notes[-1])
    return flows, {"effects": notes} if notes else {}


def _bend(rw: _Rows, xv: np.ndarray, up: bool, hs: list, grid: np.ndarray) -> tuple[list, list]:
    """The hinge polished between its grid neighbours, then a second hinge where it lowers BIC by more
    than MARGIN; the slopes non-negative, by least squares with the free flows."""
    g = np.sort(np.asarray(grid, float))
    fit = lambda hset: rw.fit([rw.R * _ramp(xv, h, up) for h in hset])  # noqa: E731

    def polish(hset, m):
        k = int(np.searchsorted(g, hset[m]))
        lo = g[k - 1] if k > 0 else hset[m] - 1e-6
        hi = g[k + 1] if k + 1 < len(g) else hset[m] + 1e-6
        put = lambda h: sorted(hset[:m] + [float(h)] + hset[m + 1:])  # noqa: E731
        r = minimize_scalar(lambda h: fit(put(h))[0], bounds=(lo, hi), method="bounded",
                            options={"xatol": 1e-6 * max(1.0, abs(hi - lo))})
        return put(r.x) if r.fun < fit(hset)[0] else hset

    hs = polish([float(h) for h in hs], 0)
    b1, s1, _ = fit(hs)
    best = (b1, list(hs), list(s1))
    for h in g:
        if min(abs(h - z) for z in hs) < 1e-12:
            continue
        b2, s2, _ = fit(sorted(hs + [float(h)]))
        if b2 < best[0] - MARGIN and np.all(s2 > 0):
            best = (b2, sorted(hs + [float(h)]), list(s2))
    if len(best[1]) > 1:
        two = best[1]
        for m in range(len(two)):
            two = polish(two, m)
        b2, s2, _ = fit(two)
        if b2 <= best[0] and np.all(s2 > 0):
            best = (b2, two, list(s2))
    _, hset, ss = best
    keep = [(h, s) for h, s in zip(hset, ss) if s > 0]
    return [h for h, _ in keep], [s for _, s in keep]


def _polish(st, flows, env, scale, floor, grids) -> tuple[list[dict], list]:
    """Each effect flow this module wrote (and the counter inflow counting it) refitted with the flows as
    they now are: its slopes were fitted beside misfits (a floored gap, say) that a later step removed."""
    done = []
    for f0 in [f for f in flows if f.get("effect_fit")]:
        if f0 not in flows:
            continue
        fit = f0["effect_fit"]
        counter = fit.get("counter")
        x = f0["effects"][0]["stock"]
        if x not in grids:
            continue
        group = [f for f in flows if f is f0 or f.get("counts") == f0.get("id")]
        rest = [f for f in flows if not any(f is g for g in group)]
        cand = (f0.get("from"), f0.get("to"), fit.get("reader"), counter)
        rw = _Rows(st, rest, [_amount(f, st, env) for f in rest], cand, scale, floor)
        if not rw.ok:
            continue
        hs, ss = _bend(rw, st.series(x), fit["up"], [float(fit["hinges"][0])], grids[x])
        if not ss:
            continue
        eff = [{"stock": x, "shape": "table", "points": _table(st.series(x), hs, ss, fit["up"])}]
        keep = [g for i, g in enumerate(rest) if i not in rw.drop]
        flows = keep + [{**g, "effects": [dict(e) for e in eff], **({"effect_fit": {**fit, "hinges": hs}} if g is f0 else {})} for g in group]
        done.append({"flow": f"{cand[0] or 'outside'}->{cand[1] or 'outside'}", "hinges": [_num(v) for v in hs], "slopes": [_num(v) for v in ss]})
    return flows, done


def _refit(flows, stocks, run, opts, skip):
    from .polish import refine
    return refine(flows, stocks, run, opts, skip=skip)


def prune(flows: list[dict], stocks: list[dict], run: dict, opts: dict | None, skip=()) -> tuple[list[dict], dict]:
    """(k8s-312) An effect flow this module wrote, not a counted move or a counter's inflow, is dropped when the rows it
    touches are within QUIET times their rounding noise without it (_quiet) once the rest is in place: found while
    another structure was still missing, it fitted that misfit (a slope of 7e-7 on queue's row while the pods' room
    was wrong), which is gone now."""
    opts = opts or {}
    st = Steps(stocks, run, opts)
    if st.T < 20 or st.counts:
        return flows, {}
    env = _env(st)
    pos = {s: i for i, s in enumerate(st.ids)}
    out, dropped = list(flows or []), []
    for f in list(out):
        fit = f.get("effect_fit") or {}
        if not fit or fit.get("counter") or f.get("counts") or any(g.get("counts") == f.get("id") for g in out):
            continue
        rows = {pos[x] for x in (f.get("from"), f.get("to")) if x in pos}
        rest = [g for g in out if g is not f]
        rest, _ = _refit(rest, stocks, run, opts, skip)          # the other numbers refitted without it (they were fitted beside it)
        amounts = [_amount(g, st, env) for g in rest]
        if any(a is None for g, a in zip(rest, amounts) if {g.get("from"), g.get("to")} & {st.ids[r] for r in rows}):
            continue
        if rows and rows <= _quiet(st, rest, env, amounts):
            out = rest
            dropped.append(f"{f.get('from') or 'outside'}->{f.get('to') or 'outside'}")
    return out, ({"pruned": dropped} if dropped else {})
