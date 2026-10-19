# Vendored for combined2 from sdlab/discovery/strategies/own_tables/__init__.py at commit 67a604b (HEAD 05ae898); imports
# rewritten to these copies, otherwise unchanged (CLAUDE.md invariant 11). Re-vendor rather than edit.
"""Own tables: a stock's flows to and from outside as a table of the stock's own level.

A drain that bends with its own level (a tank's k sqrt(H)) or an inflow that a stock shuts off as it
fills (a heater switched by the temperature it raises) is a table effect of the stock on its own flow.
The main line's rows are straight, so it writes the bend as a straight drain plus a constant, and
copies the rest into inflow pieces (122-concave-drain: 0.045 H and 142 pieces; 123: a constant
inflow and a drain twice the true one).

This strategy takes the main line's chosen model and, row by row, offers one rewrite: the row's
change, less the flows kept from the main line (moves between measured stocks, flows of other rows),
is fitted as a curve g of the row's own level with free points (curve.py), beside the levels of other
stocks and the measured inputs that the replaced flows read. The curve is read back as flows
(split.py): one table flow when it keeps one sign, else a plain drain and an inflow table (or a
constant and a table), whichever table moves least.

The rewrite is kept only when the curve beats a straight line in the same columns by BIC (`margin` x
log T), and the whole model's one-step BIC (onestep.py, in the form the engine steps it, with the
table's values and point positions counted) beats the main line's by `margin` x log T. With
`halves`, the curve fitted on each half of the run (same points) must also predict the other half
better than the straight line fitted there.

First, a move between measured stocks that reads its source may be rewritten as a table of the
source (moves.py), fitted on the destination's row. Rows with era segments or effects already are
left as they are. Measured inputs (opts "inputs") are
columns of the fit when a replaced flow read them, and every model is stepped with them.
"""

from __future__ import annotations

import math

import numpy as np

from sdlab.discovery.identify import identify as main_line
from sdlab.discovery.matrix import injected
from . import curve, moves, onestep, split

DEFAULTS = {"rising": 0.25, "margin": 2.0, "halves": True, "weighted": True, "trim": 0.03, "most": 12, "moves": True}


def _touches_outside(f: dict, row: str) -> bool:
    return (f.get("from") is None and f.get("to") == row) or (f.get("from") == row and f.get("to") is None)


def _reads(f: dict) -> list[str]:
    r = f.get("rate") or {}
    if r.get("form") in ("proportional", "gap"):
        return [r.get("stock")]
    if r.get("form") == "linear":
        return [x.get("stock") for x in r.get("terms") or []]
    return []


def _flow(src, dst, rate: dict, **extra) -> dict:
    return {"from": src, "to": dst, "ratio": 1, "rate": rate, "rates": [rate], "nearly": [], "bothWays": False, **extra}


def _column_flows(row: str, names: list[str], cols: list[int], b: np.ndarray, inputs: list[str], tol: float = 1e-12) -> list[dict]:
    """The other columns' numbers as links into the row (b > 0) or drains of it reading them (b < 0)."""
    out = []
    for m, k in zip(cols, b):
        mark = {"input": names[m]} if names[m] in inputs else {}
        rate = {"form": "linear", "c": 0, "terms": [{"stock": names[m], "k": float(f"{abs(float(k)):.6g}")}]}
        if k > tol:
            out.append(_flow(None, row, rate, driver=names[m], **mark))
        elif k < -tol:
            out.append(_flow(row, None, rate, driver=names[m], **mark))
    return out


def _weights(y: np.ndarray, x: np.ndarray, kn: np.ndarray, Z: np.ndarray) -> np.ndarray | None:
    """Rows weighted by their noise where it grows with the level (counting noise): the squared
    residuals of an unweighted fit regressed on the level; None when the noise does not change."""
    b, _ = curve.fit(y, x, kn, Z)
    A = np.vstack([curve.hats(x, kn), Z]).T if len(Z) else curve.hats(x, kn).T
    r2 = (y - A @ b) ** 2
    c = np.linalg.lstsq(np.vstack([np.ones_like(x), x]).T, r2, rcond=None)[0]
    var = c[0] + c[1] * x
    m = float(r2.mean())
    if m <= 0:
        return None
    var = np.maximum(var, 0.05 * m)
    if var.max() / var.min() < 2.0:
        return None
    return 1.0 / np.sqrt(var)


def _halves_ok(y, x, kn, Z, wt) -> bool:
    """Fitted on one half (the same points), the curve predicts the other half better than the
    straight line fitted on the same half, both ways round."""
    T = len(y)
    h = T // 2
    line = np.array([kn[0], kn[-1]])
    for a, b in ((slice(0, h), slice(h, T)), (slice(h, T), slice(0, h))):
        w_a = None if wt is None else wt[a]
        w_b = np.ones(len(y[b])) if wt is None else wt[b]
        errs = []
        for k in (kn, line):
            # a point the fitting half never reached keeps no value: predict only where both halves were
            if np.ptp(x[a]) <= 0:
                return False
            coef = curve.fit(y[a], x[a], k, Z[:, a], w_a)[0]
            A = np.vstack([curve.hats(x[b], k), Z[:, b]]).T if len(Z) else curve.hats(x[b], k).T
            inside = (x[b] >= x[a].min()) & (x[b] <= x[a].max())
            r = (y[b] - A @ coef) * w_b
            errs.append(float((r[inside] ** 2).sum()))
        if not errs[0] < errs[1]:
            return False
    return True


def _snap(y, x, Z, wt, cv, rd, log_t, small=0.1):
    """A two-flow reading's table points that sit near 0 (under `small` of its largest) set to exactly 0,
    and the rest refitted with the other flow's number, which the points at 0 now pin down (a curve
    alone cannot tell a drain from a sloping table). Kept when the BIC says the zeros cost less than
    the numbers they save, and every number stays >= 0."""
    if rd["other"] is None:
        return rd
    v = np.asarray(rd["values"], dtype=float)
    S = v <= small * v.max()
    if not S.any() or S.all():
        return rd
    kn = cv["knots"]
    H = curve.hats(x, kn)[~S]
    kind = rd["other"][0]
    other = x if kind == "drain" else np.ones_like(x)
    A = np.vstack([H, other[None, :], Z]).T
    yy, AA = (y, A) if wt is None else (y * wt, A * wt[:, None])
    b = np.linalg.lstsq(AA, yy, rcond=None)[0]
    r = yy - AA @ b
    rss = float(r @ r)
    T = len(y)
    if T * math.log(max(rss, 1e-300) / max(cv["rss"], 1e-300)) > int(S.sum()) * log_t:
        return rd
    nv = np.zeros(len(kn))
    nv[~S] = rd["table"] * b[: int((~S).sum())]
    o = b[int((~S).sum())] * (-1.0 if kind in ("drain", "out") else 1.0)
    if o <= 0 or np.any(nv < -1e-9 * max(1.0, float(np.abs(nv).max()))):
        return rd
    return {**rd, "values": np.maximum(0.0, nv), "other": (kind, float(o)), "z": b[int((~S).sum()) + 1:]}


def candidates(flows, ids, t, prev, dy, i, floor_rss, o, inp=None):
    mi, names, X = (inp[0], ids + inp[1], np.vstack([prev, inp[2]])) if inp else (None, ids, prev)
    row = ids[i]
    mine = [f for f in flows if _touches_outside(f, row)]
    if any(f.get("byTime") or f.get("effects") or f.get("uses") for f in mine):
        return []
    rest = [f for f in flows if not _touches_outside(f, row)]
    cols = sorted({names.index(s) for f in mine for s in _reads(f) if s in names and s != row})
    y = dy[i] - onestep.changes(rest, ids, t, prev, mi)[i]
    x = prev[i]
    T = len(y)
    Z = X[cols] if cols else np.zeros((0, T))
    wt = None
    if o["weighted"]:
        wt = _weights(y, x, np.array([x.min(), np.median(x), x.max()]) if np.ptp(x) > 0 else np.array([x.min(), x.min() + 1]), Z)
    if np.ptp(x) <= 0:
        return []
    # a cheap screen first: fixed points at the level's quantiles must already beat the straight line
    # (the free-point search is the expensive part, and most rows are straight)
    log_t = math.log(T)
    qk = np.unique(np.quantile(x, np.linspace(0, 1, 9)))
    if len(qk) < 3:
        return []
    bic = lambda rss, K: T * math.log(max(rss, floor_rss) / T) + K * log_t  # noqa: E731
    if bic(curve.fit(y, x, qk, Z, wt)[1], len(qk)) > bic(curve.fit(y, x, qk[[0, -1]], Z, wt)[1], 2) - o["margin"] * log_t:
        return []
    cv = curve.search(y, x, Z, floor_rss, wt=wt, most=o["most"])
    if cv is None or len(cv["knots"]) <= 2:
        return []
    if cv["bic"] > cv["line_bic"] - o["margin"] * log_t:
        return []
    if o["halves"] and not _halves_ok(y, x, cv["knots"], Z, wt):
        return []
    g = cv["values"]
    # no reinforcing loop the main line did not find: a curve that rises with the stock's own level
    # (rises > `rising` of its total variation) is a stock feeding itself, which an inflow that steps
    # with time imitates when the stock follows it (053 counts-long: an inflow table of A in place of
    # the inflow's pieces); a falling curve (a drain, a shut-off) is balancing
    d = np.diff(g)
    grows = any(f.get("from") is None and f.get("to") == row and _reads(f) == [row] for f in mine)
    if not grows and float(d[d > 0].sum()) > o["rising"] * float(np.abs(d).sum()):
        return []
    eps = 1e-3 * float(np.max(np.abs(g))) if np.any(g) else 0.0
    out = []
    for rd in split.readings(cv["knots"], g, eps):
        rd = _snap(y, x, Z, wt, cv, rd, log_t)
        z = rd.pop("z", cv["z"])
        extra = _column_flows(row, names, cols, z, names[len(ids):])
        out.append((rest + split.flows(row, cv["knots"], rd) + extra, f"{split.name(rd)} on {row} ({len(cv['knots'])} points)"))
    return out


def identify(stocks: list[dict], run: dict, opts: dict | None = None) -> dict:
    opts = dict(opts or {})
    o = {k: opts.pop(k, v) for k, v in DEFAULTS.items()}
    r0 = main_line(stocks, run, opts)
    ids = [s["id"] for s in stocks]
    t = run["t"]
    lv = onestep.levels(stocks, run)
    if lv.shape[1] < 30 or not ids:
        return r0
    prev, dy = lv[:, :-1], np.diff(lv, axis=1)
    if opts.get("injections"):
        inj = injected(opts["injections"], ids, t)[:, 1:]
        prev, dy = prev + inj, dy - inj
    T = prev.shape[1]
    mi = onestep.model_inputs(opts.get("inputs"), ids, t)
    in_names, in_rows = onestep.input_rows(opts.get("inputs"), ids, t, T)
    inp = (mi, in_names, in_rows) if mi is not None and in_rows.shape[1] == T else None
    floor_rss = T * ((1e-4 * dy.std(axis=1)) ** 2 + 1e-8)
    final = {s["id"] for s in stocks if s.get("final")}
    flows = list(r0.get("flows") or [])
    skip = onestep.outliers(flows, ids, t, prev, dy, o["trim"], mi) if o["trim"] else None
    score = onestep.bic(flows, ids, t, prev, dy, floor_rss, skip, mi)
    log_t = math.log(T)
    taken = []
    # moves between measured stocks first (moves.py), then each row's flows to and from outside
    if o["moves"]:
        best = None
        for fl, name in moves.candidates(flows, ids, t, prev, dy, floor_rss, o, inp):
            sc = onestep.bic(fl, ids, t, prev, dy, floor_rss, skip, mi)
            if sc < score - o["margin"] * log_t and (best is None or sc < best[1]):
                best = (fl, sc, name)
        if best:
            flows, score = best[0], best[1]
            taken.append({"row": None, "rewrite": best[2], "bic": round(score, 2)})
    for i, row in enumerate(ids):
        if row in final:
            continue
        # the readings come preferred first; a later one is taken only if it prices clearly better
        scored = [(fl, onestep.bic(fl, ids, t, prev, dy, floor_rss, skip, mi), name)
                  for fl, name in candidates(flows, ids, t, prev, dy, i, float(floor_rss[i]), o, inp)]
        best = None
        if scored:
            low = min(sc for _, sc, _ in scored)
            best = next(c for c in scored if c[1] <= low + o["margin"] * log_t)
            if not best[1] < score - o["margin"] * log_t:
                best = None
        if best:
            flows, score = best[0], best[1]
            taken.append({"row": row, "rewrite": best[2], "bic": round(score, 2)})
    return {**r0, "flows": split.extend(flows), "own_tables": taken}
