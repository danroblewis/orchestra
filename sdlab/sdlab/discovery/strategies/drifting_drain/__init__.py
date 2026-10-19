"""Drifting drain: a stock's drain whose rate moves in time, unannounced, beside a steady inflow.

Labour-market transition rates drift with the business cycle (the BLS flows); a drain whose rate
drifts is read by the main line as a constant drain and an inflow in many pieces, which copy the
drift into the wrong flow (121-drifting-drain, none-long: 0.086 A and 92 pieces), and on the long
counting-noise run every candidate failed and no model came back.

This strategy takes the main line's model (possibly empty) and, row by row, offers one rewrite: the
row's outside inflow (constant or pieces) and its own-level drain replaced by a constant inflow c
and a drain k_t x level whose rate changes in stretches (era segments, byTime), found by
segment.py. Flows the main line has between measured stocks, and those reading other levels or
measured inputs, are kept. The rewrite is kept when the whole model's one-step BIC (onestep.py, a
copy of censored's that counts every stretch's rate and cut) beats the main line's by `margin` x
log T. Rows with announced eras or effects are left as they are, and so are rows the main line read
as steady (no inflow in pieces, and some flow in or out) or fed by a link from another level.

When the levels are whole numbers (counts) and the main line left a stock with no flows at all, the
inflow is read from the size of the noise as well (segment.py) and models are priced by the
counting-noise likelihood (counts.py), under which no flows is not the cheapest reading of a stock
that barely changes. Elsewhere least squares decides: read from the noise everywhere, the inflow
followed any misfit (041-random-chain-3#8 counts-long, 051-sweep-level-scale#5 counts-short).
Every drift must beat one steady drain read the same way by `margin` x log T.
"""

from __future__ import annotations

import math

import numpy as np

from ...identify import identify as main_line
from ...matrix import injected
from . import counts, onestep, segment

DEFAULTS = {"margin": 2.0, "mult": 2.0, "fine": 10, "trim": 0.01}


def _r(v: float) -> float:
    return float(f"{float(v):.6g}")


def _flow(src, dst, rate: dict, **extra) -> dict:
    return {"from": src, "to": dst, "ratio": 1, "rate": rate, "rates": [rate], "nearly": [], "bothWays": False, **extra}


def _replaced(f: dict, row: str) -> bool:
    """The row's outside inflow (constant or pieces) and its own drain (proportional or constant)."""
    r = f.get("rate") or {}
    if f.get("from") is None and f.get("to") == row:
        return bool(f.get("inflow")) or r.get("form") == "constant"
    if f.get("from") == row and f.get("to") is None:
        return r.get("form") == "constant" or (r.get("form") == "proportional" and r.get("stock") == row)
    return False


def drift_flows(row: str, fit: dict, t: list) -> list[dict]:
    at = lambda k: t[k + 1]  # noqa: E731  (step k runs from t[k] to t[k + 1])
    segs = [{"from": at(a), "to": at(b - 1), "rate": {"form": "proportional", "stock": row, "k": _r(max(0.0, k))}}
            for (a, b), k in zip(fit["spans"], fit["k"])]
    if len(segs) == 1:
        out = [_flow(row, None, segs[0]["rate"])] if segs[0]["rate"]["k"] > 0 else []
    else:
        drain = _flow(row, None, segs[0]["rate"], byTime=segs, drift=True)
        drain["rates"] = [g["rate"] for g in segs]
        out = [drain]
    if fit["c"] > 0:
        out.insert(0, _flow(None, row, {"form": "constant", "value": _r(fit["c"])}))
    return out


def candidate(flows, ids, t, prev, dy, i, floor_var, o, mi=None, counting=False):
    row = ids[i]
    mine = [f for f in flows if (f.get("from") is None and f.get("to") == row) or (f.get("from") == row and f.get("to") is None)]
    if any(f.get("byTime") or f.get("effects") or f.get("uses") for f in mine):
        return None
    # only a row the main line could not read as steady: its inflow in pieces, or nothing in or out
    if any(f.get("from") is None and f.get("to") == row and not f.get("inflow") and not _replaced(f, row) for f in mine):
        return None
    if mine and not any(len(f.get("inflow") or []) > 1 for f in mine):
        return None
    base = [f for f in flows if not _replaced(f, row)]
    y = dy[i] - onestep.changes(base, ids, t, prev, mi)[i]
    fit = segment.search(y, prev[i], floor_var, o["mult"], o["fine"], counting=counting)
    if fit is None or len(fit["spans"]) < 2:
        return None
    one = segment.steady(y, prev[i], counting=counting)
    return (base + drift_flows(row, fit, t), f"drain on {row} in {len(fit['spans'])} stretches, inflow {fit['c']:.4g}",
            base + drift_flows(row, one, t))


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
    floor_rss = T * ((1e-4 * dy.std(axis=1)) ** 2 + 1e-8)
    o["counting"] = counts.whole(lv)
    final = {s["id"] for s in stocks if s.get("final")}
    flows = list(r0.get("flows") or [])
    skip = onestep.outliers(flows, ids, t, prev, dy, o["trim"], mi) if o["trim"] and flows else None

    def price(fl, counting):
        if counting:
            return counts.bic(fl, ids, t, prev, dy, mi)
        return onestep.bic(fl, ids, t, prev, dy, floor_rss, skip, mi)

    log_t = math.log(T)
    taken = []
    for i, row in enumerate(ids):
        if row in final:
            continue
        # counting noise only where the main line left the stock with no flows at all (a stock that
        # barely changes reads as empty by least squares): there the inflow is read from the noise's
        # size and models are priced by the counting likelihood. Elsewhere least squares throughout:
        # the noise's size is a fragile reading of the inflow wherever the model misses a little
        # (051-sweep-level-scale#5 counts-short: a start-up transient read as 50% more inflow)
        empty = o["counting"] and not any(row in (f.get("from"), f.get("to")) for f in flows)
        cand = candidate(flows, ids, t, prev, dy, i, float(floor_rss[i]) / T, o, mi, counting=empty)
        if cand is None:
            continue
        sc, score = price(cand[0], empty), price(flows, empty)
        # the drift must also earn its stretches against one steady drain read the same way
        if sc > price(cand[2], empty) - o["margin"] * log_t:
            continue
        if sc < score - o["margin"] * log_t:
            flows = cand[0]
            taken.append({"row": row, "rewrite": cand[1], "bic": round(sc, 2), "counting": empty})
    return {**r0, "flows": flows, "drifting_drain": taken}
