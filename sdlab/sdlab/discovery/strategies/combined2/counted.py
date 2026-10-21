"""Counted flows: a measured counter that counts another flow (docs/research/fixes/310-combined2.md, 2026-10-21).

A final stock C (nothing leaves it) that the boundary lets be fed from outside may be a counter:
its one-step increase is the amount of some flow elsewhere (kube's restarts counter counts the OOM kills
that move pods from ready back to pending). Its increase y is measured exactly, so that flow's rate can be
read off it: y = k x A x table(X) for a base stock A of C's unit (a per-capita rate) or no base (k x
table(X)), and a reader X (any measured stock or input; a link may cross units). The table is piecewise
linear on knots at quantiles of X over the steps where y > 0, plus the onset (the last X where nothing
happened, beyond the active range on one side), its values >= 0 by non-negative least squares; knots and
(A, X) by BIC on C's row (SSE floored at FLOOR_REL of the row's scale, so exact fits tie and parsimony
picks). Kept only where C's row's BIC falls by more than GAIN log n against the model's own inflows to C
(a move into C that already explains its row, inflight -> responses_total, is left alone; a smeared one,
pending -> counter at 0.33 x pending, is replaced, and its source's row repaired with the rest).

Where the counted flow lands: a move A -> B between measured stocks of C's unit (a move needs one unit),
an outflow A -> outside on a declared side, or nowhere (the counter alone). Each is tried on the rows it
touches: the move is inserted, the moves between the touched stocks are refitted jointly by least squares
with it held, and each touched stock's outside sides are refitted as floored rates (hinge.refit_row); the
placement whose rows' BIC is lowest wins, and only by more than GAIN log n over leaving the rows without it
(repaired the same way). The counter's own inflow becomes 1 x the same rate and table.

Adopting it: copy this file and hinge.py (amount() evaluates table effects) into the strategy's package and
call `apply(result, stocks, run, opts)` on the answer, then the floored refit (hinge.apply) once more.
"""

from __future__ import annotations

import copy
import math

import numpy as np
from scipy.optimize import nnls

from . import hinge

GAIN = 2.0
FLOOR_REL = 1e-9
MAX_KNOTS = 6
MIN_ACTIVE = 3        # steps with y > 0 the table needs
PER_KNOT = 3          # active steps per knot of the table (a few events cannot carry a shape)
ROUNDS = 3            # alternations of the joint move refit and the floored side refit
ACTIVE_ITERS = 20     # active-set passes of the joint refit


def _hats(x: np.ndarray, knots: np.ndarray) -> np.ndarray:
    B = np.zeros((len(x), len(knots)))
    for j in range(len(knots)):
        e = np.zeros(len(knots))
        e[j] = 1.0
        B[:, j] = np.interp(x, knots, e)
    return B


def fit_table(y: np.ndarray, base: np.ndarray, x: np.ndarray, floor: float) -> dict | None:
    """y ~ base x table(x): {"bic", "sse", "knots", "values"} with the fewest knots BIC allows."""
    n = len(y)
    act = y > 0
    if act.sum() < MIN_ACTIVE or np.std(x) <= 0:
        return None
    xa = x[act]
    onsets = []
    below = x[(~act) & (x < xa.min())]
    above = x[(~act) & (x > xa.max())]
    if below.size:
        onsets.append(("lo", float(below.max())))
    if above.size:
        onsets.append(("hi", float(above.min())))
    onsets.append((None, None))
    best = None
    for K in range(1, max(1, min(MAX_KNOTS, int(act.sum()) // PER_KNOT)) + 1):
        q = np.quantile(xa, np.linspace(0, 1, K)) if K > 1 else np.array([float(np.median(xa))])
        for _, o in onsets:
            knots = np.unique(np.concatenate([q, [o]] if o is not None else [q]))
            M = _hats(x, knots) * base[:, None]
            try:
                v, _ = nnls(M, y)
            except Exception:                                # noqa: BLE001
                continue
            sse = float(np.sum((M @ v - y) ** 2))
            bic = n * math.log(max(sse, floor) / n) + len(knots) * math.log(n)
            if best is None or bic < best["bic"] - 1e-9:
                best = {"bic": bic, "sse": sse, "knots": knots, "values": v}
    return best


def _flow(src, dst, a: str | None, x: str, knots, values, fid: str) -> dict:
    top = float(np.max(values))
    rate = {"form": "proportional", "stock": a, "k": top} if a else {"form": "constant", "value": top}
    pts = [[float(k), float(v / top)] for k, v in zip(knots, values)]
    return {"id": fid, "from": src, "to": dst, "ratio": 1, "rate": rate, "counted": True,
            "effects": [{"stock": x, "shape": "table", "points": pts}]}


def _row_sse(x: str, flows: list[dict], levels: dict, cols: dict, n: int) -> float | None:
    got = hinge.row_error(x, flows, levels, cols, n)
    if got is None:
        return None
    r, sides = got
    return float(np.sum((r - sides["in"] + sides["out"]) ** 2))


def _nums(flows: list[dict], rows: set) -> int:
    k = 0
    for f in flows:
        if f.get("from") in rows or f.get("to") in rows:
            lf = hinge._linear(f.get("rate") or {})
            k += (len(lf[1]) + (1 if lf[0] else 0)) if lf else 2
            k += sum(len(e.get("points") or []) for e in f.get("effects") or [])
    return k


def _value(names: list[str], coef, cols: dict, n: int) -> np.ndarray:
    v = np.zeros(n)
    for nm, k in zip(names, coef):
        v = v + k * (np.ones(n) if nm == "1" else cols[nm][:n])
    return v


def _refit_moves(flows: list[dict], rows: set, levels: dict, cols: dict, n: int) -> list[dict]:
    """The linear flows on `rows` (moves with both ends in them and their outside rates, floored ones too)
    refitted jointly on those rows by active-set least squares: each flow's columns count only on the steps
    where its rate is positive (the engine floors every flow at 0), the steps recomputed from the fit until
    they settle; every other flow held."""
    def free(f):
        a, b = f.get("from"), f.get("to")
        inner = a in rows and b in rows
        side = (a is None and b in rows) or (b is None and a in rows)
        return (inner or side) and not f.get("effects") and not f.get("inflow") and not f.get("counted") \
            and hinge._linear(f.get("rate") or {}) is not None and hinge.amount(f, cols, n) is not None
    idx = [i for i, f in enumerate(flows) if free(f)]
    if not idx:
        return flows
    held = [f for i, f in enumerate(flows) if i not in idx]
    order = sorted(rows)
    params = []
    for i in idx:
        c, ks = hinge._linear(flows[i]["rate"])
        params.append((i, (["1"] if c else []) + list(ks)))
    ys = []
    for x in order:
        got = hinge.row_error(x, held, levels, cols, n)
        if got is None:
            return flows
        r, sides = got
        ys.append(r - sides["in"] + sides["out"])
    y = np.concatenate(ys)
    masks = [np.ones(n, dtype=bool) for _ in params]       # start unfloored (a smeared start can sit at 0 throughout)
    b = None
    for _ in range(ACTIVE_ITERS):
        blocks = []
        for x in order:
            cols_x = []
            for (i, names), on in zip(params, masks):
                f = flows[i]
                sign = (-float(f.get("ratio") or 1)) if f.get("from") == x else (1.0 if f.get("to") == x else 0.0)
                for nm in names:
                    cols_x.append(sign * on * (np.ones(n) if nm == "1" else cols[nm][:n]))
            blocks.append(np.column_stack(cols_x))
        b, *_ = np.linalg.lstsq(np.vstack(blocks), y, rcond=None)
        new, j = [], 0
        for _, names in params:
            new.append(_value(names, b[j:j + len(names)], cols, n) > 0)
            j += len(names)
        if all(np.array_equal(m1, m2) for m1, m2 in zip(new, masks)):
            break
        masks = new
    out = copy.deepcopy(flows)
    j = 0
    for i, names in params:
        c = 0.0
        terms = []
        for nm in names:
            if nm == "1":
                c = float(b[j])
            else:
                terms.append({"stock": nm, "k": float(b[j])})
            j += 1
        if not terms:
            out[i]["rate"] = {"form": "constant", "value": c}
        elif len(terms) == 1 and not c and not str(out[i].get("id") or "").startswith("floored_"):
            out[i]["rate"] = {"form": "proportional", "stock": terms[0]["stock"], "k": terms[0]["k"]}
        else:
            out[i]["rate"] = {"form": "linear", "c": c, "terms": terms}
    return out


def _repair(flows: list[dict], rows: set, levels: dict, cols: dict, n: int, run: dict) -> tuple[list[dict], float, int] | None:
    """The rows' moves and outside sides refitted with every counted flow held: (flows, rows' SSE, numbers)."""
    cur = flows
    for _ in range(ROUNDS):
        cur = _refit_moves(cur, rows, levels, cols, n)
        for x in sorted(rows):
            have = {s for f in cur for s in [hinge._side(f, x)] if s}
            got = hinge.refit_row(x, cur, levels, cols, n, hinge.allowed_sides(x, run, cur) & have, force=True)
            if got is not None:
                cur = got[0]
    sse = 0.0
    for x in rows:
        s = _row_sse(x, cur, levels, cols, n)
        if s is None:
            return None
        sse += s
    return cur, sse, _nums(cur, rows)


def apply(result: dict, stocks: list[dict], run: dict, opts: dict | None = None, readable=None) -> dict:
    """The answer with each counter's counted flow read off its increase (see the module docstring)."""
    if not isinstance(result, dict) or not result.get("flows"):
        return result
    levels, cols, n = hinge.columns(run, opts, readable)
    if n < 10:
        return result
    unit = {s["id"]: s.get("unit") for s in stocks}
    finals = {s["id"] for s in stocks if s.get("final")}
    out = copy.deepcopy(result)
    flows = out["flows"]
    notes = []
    for c in sorted(finals & set(levels)):
        if any(f.get("from") == c for f in flows):
            continue                                       # something leaves it: not a counter
        if run.get("boundary_declared") and not ((run.get("boundary") or {}).get(c) or {}).get("in"):
            continue
        y = np.diff(levels[c][:n + 1])
        if np.any(y < -1e-9) or (y > 0).sum() < MIN_ACTIVE:
            continue
        scale = max(1e-12, float(np.abs(y).max()))
        floor = n * (FLOOR_REL * scale) ** 2
        if np.allclose(levels[c], np.round(levels[c])):
            floor = max(floor, n / 12.0)                  # whole-number counts: their rounding
        mine = [f for f in flows if f.get("to") == c]     # its inflows (a move into it too): replaced only on C's row's evidence
        own = _row_sse(c, flows, levels, cols, n)
        if own is None:
            continue
        bic_own = n * math.log(max(own, floor) / n) + _nums(mine, {c}) * math.log(n)
        bases = [a for a in levels if a not in finals and a != c and unit.get(a) == unit.get(c)] + [None]
        readers = [x for x in cols if x not in finals and x != c]
        best = None
        for a in bases:
            base = np.maximum(0.0, levels[a][:n]) if a else np.ones(n)
            for x in readers:
                t = fit_table(y, base, cols[x][:n], floor)
                if t and (best is None or t["bic"] < best[0]["bic"] - 1e-9):
                    best = (t, a, x)
        if best is None or not best[0]["bic"] < bic_own - GAIN * math.log(n):
            continue
        t, a, x = best
        counter = _flow(None, c, a, x, t["knots"], t["values"], f"counted_{c}")
        keep = [f for f in flows if f not in mine] + [counter]
        place = {"counter": c, "base": a, "reader": x, "knots": len(t["knots"]), "sse_before": own, "sse_after": t["sse"]}
        if a:
            peers = [b for b in levels if b not in finals and b not in (a, c) and unit.get(b) == unit.get(a)
                     and hinge.row_error(b, keep, levels, cols, n) is not None]       # a row this can evaluate (no switch)
            trials = [("none", None, keep)]
            trials += [(b, b, keep + [_flow(a, b, a, x, t["knots"], t["values"], f"counted_{a}_{b}")]) for b in peers]
            if "out" in hinge.allowed_sides(a, run, flows) and not any(hinge._side(f, a) == "out" for f in keep):   # one flow a side
                trials.append(("outside", None, keep + [_flow(a, None, a, x, t["knots"], t["values"], f"counted_{a}_out")]))
            scored = []
            for name, b, fl in trials:
                rows = {a} | set(peers)                   # the same rows for every placement: comparable
                got = _repair(fl, rows, levels, cols, n, run)
                if got is None:
                    continue
                cur, sse, k = got
                scored.append((n * len(rows) * math.log(max(sse, floor) / (n * len(rows))) + k * math.log(n * len(rows)), name, cur, sse))
            if scored:
                scored.sort(key=lambda s: s[0])
                none = next((s for s in scored if s[1] == "none"), None)
                top = scored[0]
                if top[1] != "none" and (none is None or top[0] < none[0] - GAIN * math.log(n)):
                    keep = top[2]
                    place.update(move=top[1], rows_sse=top[3])
                elif none is not None:
                    keep = none[2]
                    place.update(move=None, rows_sse=none[3])
        flows[:] = keep
        notes.append(place)
    if notes:
        out["counted"] = notes
    return out
