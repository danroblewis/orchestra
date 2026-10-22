"""A counted move with a threshold effect (k8s 310, 2026-10-21, docs/research/fixes/310-structures.md).

A counter (a measured stock that only grows: a final stock, or one whose levels never fall) whose outside
inflow counts what one move carries (310: `oom_kills_total` counts the pods `ready -> pending` takes when
memory nears its limit) holds that move's amount at every step, and the move itself is often too small or
too rare in its two stocks' rows to be found there. Here each counter's increments y are fitted as
A x e(X): A a measured stock in the counter's unit (what is counted moves out of it), e a monotone
piecewise-linear table of one measured stock or input X (an effect: X may be in any unit), 0 below a
threshold, its slopes non-negative (NNLS) on 1-3 segments whose knots are the threshold and quantiles of X
where the counter moves, capped at 1 (a move takes at most the whole stock in a step); the threshold must
bind (the table is 0 on at least MIN_ACTIVE steps where A holds something), so a counter fed by a plain or
bilinear rate is left to the fits upstream. The threshold, A, X
and the segments are chosen on BIC, and the fit is offered only when it beats the best plain rate of the
counter's row (a constant or one level) by FIT_GAIN x log n.

The counter's inflow is then written as that rate. The same rate is offered as a move A -> B for every
measured B in the same unit (a move needs both ends in one unit); the plain flows touching A and B are
refitted with it under the engine's floors (floor._refit), the floored outside rates searched again
(floor.apply), the rows' missing plain moves added back (repair.py, 2026-10-22), and the move kept when combined's judge (judge.score) prefers the model by more than log T.
"""

from __future__ import annotations

import copy
import math

import numpy as np
from scipy.optimize import nnls

from sdlab.discovery.simulate import Model

from . import floor, steps
from ._vendored.combined import judge as J

FIT_GAIN = 2.0      # the effect fit must beat the best plain rate by this x log n
MIN_ACTIVE = 3      # the counter must move on at least this many steps
MAX_SEG = 3
TOP_B = 2          # (k8s 317) receivers tried in full: the ones whose rows the counted amount repairs most


def _segments(x: np.ndarray, knots: list[float]) -> np.ndarray:
    cols = []
    for j, k in enumerate(knots):
        hi = knots[j + 1] - k if j + 1 < len(knots) else np.inf
        cols.append(np.clip(x - k, 0.0, hi))
    return np.column_stack(cols)


def _fit(y: np.ndarray, a: np.ndarray, x: np.ndarray, active: np.ndarray) -> dict | None:
    """The best table e (threshold, knots, slopes) for y ~ a x e(x), on BIC."""
    n = len(y)
    xa = np.sort(np.unique(x[active]))
    below = x[~active]
    lo_cands = list(np.unique(np.quantile(xa, [0.0, 0.1, 0.25]))) if len(xa) else []
    if len(below):
        lo_cands += [float(np.max(below[below <= xa[0]])) if np.any(below <= xa[0]) else float(xa[0])]
    best = None
    for th in sorted(set(float(v) for v in lo_cands)):
        if int(np.sum((x <= th) & (a > 0))) < MIN_ACTIVE:
            continue                                    # a threshold effect: 0 on some steps where A holds something
        above = xa[xa > th]
        for m in range(1, MAX_SEG + 1):
            inner = list(np.unique(np.quantile(above, np.linspace(0, 1, m + 1)[1:-1]))) if m > 1 and len(above) > m else []
            knots = [th] + [float(k) for k in inner if k > th]
            if len(knots) < m:
                continue
            if len(knots) > 1:
                knots = _refine(y, a, x, knots, float(above.max()))
            B = a[:, None] * _segments(x, knots)
            s, _ = nnls(B, y)
            sse = float(np.sum((y - B @ s) ** 2))
            bic = n * math.log(max(sse, 1e-300) / n) + (1 + len(knots)) * math.log(n)
            if best is None or bic < best["bic"]:
                best = {"bic": bic, "sse": sse, "knots": knots, "slopes": [float(v) for v in s]}
    return best


def _refine(y: np.ndarray, a: np.ndarray, x: np.ndarray, knots: list[float], top: float, rounds: int = 3) -> list[float]:
    """(k8s 312, docs/research/fixes/312-structures.md) the inner knots moved, one at a time, to where the NNLS fit's
    SSE is least (golden section between the neighbouring knots). Quantile knots of the kills' mem bunch where
    the kills are (312 none-long: 480.0, 481.1, 482.7 for the truth's 480, 512, 560), and the slope above the
    second knot, which few steps reach, came out the first one's: the counter's whole flow 2.0% off."""
    def sse(ks):
        B = a[:, None] * _segments(x, ks)
        s, _ = nnls(B, y)
        return float(np.sum((y - B @ s) ** 2))
    ks = list(knots)
    for _ in range(rounds):
        for j in range(1, len(ks)):
            lo, hi = ks[j - 1], (ks[j + 1] if j + 1 < len(ks) else top)
            if not hi > lo:
                continue
            a_, b_ = lo, hi
            for _ in range(40):
                c_, d_ = b_ - 0.618 * (b_ - a_), a_ + 0.618 * (b_ - a_)
                if sse(ks[:j] + [c_] + ks[j + 1:]) < sse(ks[:j] + [d_] + ks[j + 1:]):
                    b_ = d_
                else:
                    a_ = c_
            cand = ks[:j] + [0.5 * (a_ + b_)] + ks[j + 1:]
            if sse(cand) < sse(ks):
                ks = cand
    return ks


def _points(knots: list[float], slopes: list[float], xmin: float) -> list[list[float]] | None:
    pts = [[min(xmin, knots[0]) - 1.0, 0.0], [knots[0], 0.0]]
    e = 0.0
    for j, k in enumerate(knots):
        if j + 1 < len(knots):
            e2 = e + slopes[j] * (knots[j + 1] - k)
            if e2 >= 1.0:
                pts.append([k + (1.0 - e) / slopes[j], 1.0])
                return pts
            e = e2
            pts.append([knots[j + 1], e])
        elif slopes[j] > 0:
            pts.append([k + (1.0 - e) / slopes[j], 1.0])
    if pts[-1][1] <= 0:
        return None
    return pts


def _plain_bic(y: np.ndarray, cols: dict[str, np.ndarray]) -> float:
    n = len(y)
    best = n * math.log(max(float(np.sum((y - y.mean()) ** 2)), 1e-300) / n) + math.log(n)
    for v in cols.values():
        A = np.column_stack([np.ones(n), v])
        r = y - A @ np.linalg.lstsq(A, y, rcond=None)[0]
        best = min(best, n * math.log(max(float(r @ r), 1e-300) / n) + 2 * math.log(n))
    return best


def apply(result: dict, stocks: list[dict], run: dict, opts: dict | None, judge_opts: dict | None = None) -> dict:
    if not isinstance(result, dict) or not result.get("flows") or (opts or {}).get("eras"):
        return result                                 # (k8s 311) injections are taken into the rows (steps.py)
    try:
        return _apply(result, stocks, run, opts or {}, judge_opts if judge_opts is not None else (opts or {}))
    except Exception as e:                            # noqa: BLE001  (the answer stands as it was)
        return {**result, "counted": {"error": f"{type(e).__name__}: {e}"[:300]}}


def _apply(result: dict, stocks: list[dict], run: dict, opts: dict, jo: dict) -> dict:
    levels = {k: np.asarray(v, dtype=float) for k, v in (run.get("levels") or {}).items()}
    inputs = {k: np.asarray(v, dtype=float) for k, v in (opts.get("inputs") or {}).items() if k not in levels}
    unit = {s["id"]: s.get("unit") for s in stocks}
    declared = bool(run.get("boundary_declared"))
    bound = run.get("boundary") or {}
    flows = list(result["flows"])
    notes = []
    data = None
    for st in stocks:
        c = st["id"]
        L = levels.get(c)
        if L is None or len(L) < 10:
            continue
        inj = steps.injected(run, opts, len(L) - 1)
        y = np.diff(L) - inj.get(c, 0.0)
        if np.any(y < -1e-9 * max(1.0, np.max(np.abs(L)))) and not st.get("final"):
            continue                                    # not a counter
        if declared and not (bound.get(c) or {}).get("in"):
            continue
        if declared and (bound.get(c) or {}).get("out"):
            continue
        ins = [f for f in flows if f.get("from") is None and f.get("to") == c]
        if not declared and not ins:
            continue
        movers = [f for f in flows if f.get("to") == c and f.get("from")]
        if any(f.get("from") == c for f in flows) or any(not floor._plain(f) or f.get("effects") for f in movers):
            continue                                    # the counter has a move: not counting one
        # (k8s 312, docs/research/fixes/312-structures.md) a plain move into the counter (312 none-long's base:
        # `pending -> oom_kills_total = 0.07 pending`, a stand-in for the counted kills) is one more rate the
        # counted fit must beat, and goes with the counter's outside inflows when it does
        ins = ins + movers
        active = y > 1e-9 * max(1.0, float(np.max(np.abs(y))))
        if int(active.sum()) < MIN_ACTIVE:
            continue
        n = len(y)
        prev = {k: v[:-1] + inj.get(k, 0.0) for k, v in levels.items() if len(v) == len(L)}
        prev.update({k: v[1:len(L)] for k, v in inputs.items() if len(v) >= len(L)})   # an input's value during the step
        same = [a for a in prev if a != c and a in unit and unit[a] == unit[c] and np.ptp(prev[a]) > 0 and np.min(prev[a]) >= 0]
        drivers = [x for x in prev if x != c and np.ptp(prev[x]) > 0]
        top = None
        for a in same:
            for x in drivers:
                if x == a:
                    continue
                f = _fit(y, prev[a], prev[x], active)
                if f and (top is None or f["bic"] < top["bic"]):
                    top = {**f, "a": a, "x": x}
        if top is None:
            continue
        plain = _plain_bic(y, {k: v for k, v in prev.items() if k != c})
        if not top["bic"] < plain - FIT_GAIN * math.log(n):
            continue
        pts = _points(top["knots"], top["slopes"], float(np.min(prev[top["x"]])))
        if pts is None:
            continue
        rate = {"form": "proportional", "stock": top["a"], "k": 1.0}
        eff = [{"stock": top["x"], "shape": "table", "points": [[round(p, 6), round(v, 6)] for p, v in pts]}]
        counter = {"id": f"counted_{c}", "from": None, "to": c, "ratio": 1, "rate": rate, "rates": [rate], "effects": eff}
        base = [f for f in flows if f not in ins] + [counter]
        if data is None:
            data = J.Data(stocks, run, jo.get("injections"), jo.get("inputs"))
            R = Model([], data.ids, inputs=data.model_inputs)._read(data.prev, data.tt)
            names = list(data.ids) + ([k for k in data.inputs if k not in set(data.ids)] if data.inputs else [])
            mat = {k: R[i] for i, k in enumerate(names)}
            offered = set((jo.get("capmin") or {}).keys())
        note = {"counter": c, "reads": top["a"], "effect": top["x"], "points": eff[0]["points"], "move": None}
        best_flows, best = base, J.score(base, data)["bic"]
        for b in _receivers(base, data, top["a"], same, y):
            mv = {"id": f"counted_{top['a']}_{b}", "from": top["a"], "to": b, "ratio": 1, "rate": dict(rate), "rates": [dict(rate)],
                  "effects": copy.deepcopy(eff)}
            cand = floor._refit(base + [mv], data, mat, offered, near={top["a"], b})
            cand = (floor.apply({"flows": cand}, stocks, run, opts, judge_opts=jo, only=_near(cand, {top["a"], b})).get("flows")) or cand
            # (2026-10-22) the rows the move lands on repaired with the plain moves they lack (repair.py):
            # 310 none-long on node2 had lost `pending -> ready`, which only pays once the kill move is in
            from . import repair
            cand = repair.apply({"flows": cand}, stocks, run, opts).get("flows") or cand
            sc = J.score(cand, data)["bic"]
            if sc < best - math.log(max(2, data.T)):
                best_flows, best, note["move"] = cand, sc, f"{top['a']} -> {b}"
        flows = best_flows
        notes.append(note)
    if not notes:
        return result
    return {**result, "flows": flows, "counted": notes}


def _near(flows: list[dict], ends: set) -> set:
    """(k8s 317) The stocks a floor search revisits after a move is inserted: its two ends and every stock a flow
    joins to them (the rows its numbers were refitted on), not all 36 of 317's."""
    out = set(ends)
    for f in flows:
        if f.get("from") in ends or f.get("to") in ends:
            out |= {x for x in (f.get("from"), f.get("to")) if x}
    return out


def _receivers(flows: list[dict], data, a: str, same: list[str], m: np.ndarray) -> list[str]:
    """(k8s 317) The stocks B a counted move A -> B is tried into, best first: the move takes the counted amount m
    from A's row and gives it to B's, so each B is ranked by how much of the two rows' one-step residuals (under
    the answer with the counter's rate in) that one column explains, and only the TOP_B that it repairs (a
    positive gain) are refitted in full. 317 has nine stocks of the counters' unit (pods) for each of three
    counters, and each full try (refit, floor search, repair) costs a minute and more on 36 stocks."""
    try:
        res = data.dy - J.one_step(flows, data)[0]
    except Exception:                                 # noqa: BLE001  (unranked: every same-unit stock, in order)
        return [b for b in same if b != a]
    idx = {k: i for i, k in enumerate(data.ids)}
    if a not in idx or len(m) != res.shape[1]:
        return [b for b in same if b != a]
    ra = res[idx[a]]
    mm = 2.0 * float(m @ m)
    ranked = []
    for b in same:
        if b == a or b not in idx:
            continue
        g = float(res[idx[b]] @ m - ra @ m)
        if g > 0 and mm > 0:
            ranked.append((g * g / mm, b))
    ranked.sort(reverse=True)
    return [b for _, b in ranked[:TOP_B]]
