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
(floor.apply), and the move kept when combined's judge (judge.score) prefers the model by more than log T.
"""

from __future__ import annotations

import copy
import math

import numpy as np
from scipy.optimize import nnls

from sdlab.discovery.simulate import Model

from . import floor
from ._vendored.combined import judge as J

FIT_GAIN = 2.0      # the effect fit must beat the best plain rate by this x log n
MIN_ACTIVE = 3      # the counter must move on at least this many steps
MAX_SEG = 3


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
            B = a[:, None] * _segments(x, knots)
            s, _ = nnls(B, y)
            sse = float(np.sum((y - B @ s) ** 2))
            bic = n * math.log(max(sse, 1e-300) / n) + (1 + len(knots)) * math.log(n)
            if best is None or bic < best["bic"]:
                best = {"bic": bic, "sse": sse, "knots": knots, "slopes": [float(v) for v in s]}
    return best


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
    if not isinstance(result, dict) or not result.get("flows") or (opts or {}).get("eras") or (opts or {}).get("injections"):
        return result
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
        y = np.diff(L)
        if np.any(y < -1e-9 * max(1.0, np.max(np.abs(L)))) and not st.get("final"):
            continue                                    # not a counter
        if declared and not (bound.get(c) or {}).get("in"):
            continue
        if declared and (bound.get(c) or {}).get("out"):
            continue
        ins = [f for f in flows if f.get("from") is None and f.get("to") == c]
        if not declared and not ins:
            continue
        if any(f.get("from") == c for f in flows) or any(f.get("to") == c and f.get("from") for f in flows):
            continue                                    # the counter has a move: not counting one
        active = y > 1e-9 * max(1.0, float(np.max(np.abs(y))))
        if int(active.sum()) < MIN_ACTIVE:
            continue
        n = len(y)
        prev = {k: v[:-1] for k, v in levels.items() if len(v) == len(L)}
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
        for b in same:
            if b == top["a"]:
                continue
            mv = {"id": f"counted_{top['a']}_{b}", "from": top["a"], "to": b, "ratio": 1, "rate": dict(rate), "rates": [dict(rate)],
                  "effects": copy.deepcopy(eff)}
            cand = floor._refit(base + [mv], data, mat, offered, near={top["a"], b})
            cand = (floor.apply({"flows": cand}, stocks, run, opts, judge_opts=jo).get("flows")) or cand
            sc = J.score(cand, data)["bic"]
            if sc < best - math.log(max(2, data.T)):
                best_flows, best, note["move"] = cand, sc, f"{top['a']} -> {b}"
        flows = best_flows
        notes.append(note)
    if not notes:
        return result
    return {**result, "flows": flows, "counted": notes}
