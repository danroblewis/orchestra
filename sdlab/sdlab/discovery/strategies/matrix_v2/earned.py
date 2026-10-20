"""(option earned) Each candidate's rows refitted before the judge: a copy of matrix/earned.py's
refit at 8c507a8 (itself earned_pieces' refit at 66086e7; strategies are isolated, so this package
carries its own copy, with earned_rows.py and earned_joint.py, and never imports those).

Each row's levels are chosen again and its outside-inflow pieces dropped when a constant (or no)
inflow leaves white residuals and a lower BIC with every change priced as a value and a place, or
replaced by changes found again at the textbook price when those win on the same BIC
(earned_rows.py); conservation is decided for all rows at once on the counting likelihood
(earned_joint.py). Without it, chance pieces on a stock with no outside inflow won the judge (302
counts-short: inflight -> outside in pieces once a final counter fixed inflight's drain;
docs/research/k8s-302.md).

Differences from matrix/earned.py: this package's matrix.py and finish() (so the options' reading
steps, pooled pieces aside, apply to the refitted rows); the rows may read the measured inputs (the
columns after the levels, before any products); a row that chose a product keeps it only if the
matrix's own row wins its reselection.
"""

from __future__ import annotations

import numpy as np

from .earned_joint import System, decide
from .earned_rows import reselect, rss_floor
from .matrix import finish


def refit(stocks: list[dict], r: dict, opts: dict) -> dict:
    """The candidate's rows refitted jointly, sources tied to their receivers where the counting
    likelihood says so; the model read off again by this package's finish()."""
    fit, ctx = r.get("fit"), r.get("ctx")
    if not fit or not ctx:
        return r
    ids, rows = fit["ids"], fit["rows"]
    names, columns = ctx["names"], ctx["columns"]
    inputs = list(range(len(ids), len(ids) + len(ctx.get("inputs") or [])))
    unit = {s["id"]: s.get("unit") or "" for s in stocks}
    final = {s["id"] for s in stocks if s.get("final")}
    L = len(fit["labels"])
    # (this copy) under the option exact, no row's rss below the data's float precision either, as in
    # this package's fits (without it a noise-free row takes collinear cross-links that cut its rss
    # by rounding error: 032, 034, 043, 057 none-short)
    floor = max(rss_floor(fit["prev"], fit["dy"].shape[1]), float(ctx.get("exact") or 0.0) * fit["dy"].shape[1])
    rows = [reselect(row, s, ids, stocks, columns, fit["dy"], fit["cfg"], L, 2, 0.01, floor, "beside", inputs)["row"]
            for s, row in enumerate(rows)]
    system = System(rows, ids, unit, final, fit["dy"], fit["cfg"], L, True, opts.get("min_piece", 5), "unit")
    best = decide(system, ctx["log_t"])
    at = fit["at"]
    new = []
    for s, row in enumerate(rows):
        coef_l = [{} for _ in range(system.L)]
        for q, b in zip(row["set"], best["beta"][s]):
            j, lab = row["col"][q]
            for c in range(system.L):
                if lab < 0 or lab == c:
                    coef_l[c][names[j]] = coef_l[c].get(names[j], 0.0) + float(b)
        u = best["inflow"][s]
        cuts = best["cuts"][s]
        inflow = [{"from": at[a], "to": at[b - 1], "value": float(u[a])} for a, b in zip(cuts[:-1], cuts[1:])] if cuts else []
        new.append({"id": row["id"], "coefL": coef_l, "inflow": inflow, "cuts": cuts, "set": [], "col": [],
                    "X": np.zeros((0, system.T)), "beta": np.zeros(0), "rss": 0.0, "p": 0})
    out = finish(new, {**ctx, "final": set(ids)}, opts)
    out["tied"] = sorted(ids[a] for a in best["tied"])
    return out
