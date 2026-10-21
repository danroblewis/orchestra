"""earned_pieces' refit (rows reselected, conservation decided jointly), with shared change places
offered to every row after the reselection (places.py)."""

from __future__ import annotations

import numpy as np

from ._vendored.matrix import Ops, finish
from .exact import tiebreak
from .joint import System, decide
from .places import offer
from .rows import reselect
from . import boundary

ALPHA = 0.001       # the whiteness test's level (one test per row and candidate: 1% rejects true rows too often)


def refit(stocks: list[dict], r: dict, opts: dict, ops: Ops, b: boundary.Boundary | None = None) -> dict:
    """(the declared boundary b, boundary.py) rows reselected inside it (an outside term only on an
    estimate side, inputs only on a measured side, other-unit levels only on an estimate side), shared
    places offered only to rows that may have an outside term, sources with no estimated outflow tied."""
    b = b or boundary.Boundary({})
    fit, ctx = r.get("fit"), r.get("ctx")
    if not fit or not ctx:
        return r
    ids, rows = fit["ids"], fit["rows"]
    unit = {s["id"]: s.get("unit") or "" for s in stocks}
    final = {s["id"] for s in stocks if s.get("final")}
    L = len(fit["labels"])
    mp = opts.get("min_piece", 5)
    fs, pelt = ops.fit_subset, ops.pelt
    # measured inputs (opts "inputs"): columns after the levels, read as the matrix reads them (the
    # value during the step), offered to every row in the reselection and the shared places
    inp = list(ctx.get("inputs") or [])
    names = ids + inp
    lev = np.vstack([fit["prev"]] + [ctx["columns"][ctx["names"].index(k)][None, :] for k in inp]) if inp else fit["prev"]
    def exclude(s: int) -> tuple:
        out = [] if b.inputs_ok(ids[s]) else list(range(len(ids), len(names)))
        if not b.links_ok(ids[s]):
            out += [j for j in range(len(ids)) if unit[ids[j]] != unit[ids[s]]]
        return tuple(out)

    if opts.get("reselect", True) or b.declared:
        rows = [reselect(row, s, ids, stocks, lev, fit["dy"], fit["cfg"], L, opts.get("change_params", 2), opts.get("alpha", ALPHA), fs,
                         pieces_ok=b.pieces_ok(ids[s]), exclude=exclude(s))["row"] for s, row in enumerate(rows)]
    if opts.get("shared_places", True):
        rows = offer(rows, ids, stocks, lev, fit["dy"], fit["cfg"], L, pelt, mp, opts.get("change_params", 2), opts.get("trace_places", False), alpha=opts.get("alpha", ALPHA), re_cut=opts.get("honest", True), fs=fs,
                     pieces_ok=[b.pieces_ok(i) for i in ids])
    if opts.get("tiebreak", True):
        rows = [tiebreak(row, s, fit["dy"][s], fs) for s, row in enumerate(rows)]
    system = System(rows, ids, unit, final, fit["dy"], fit["cfg"], L, opts.get("counting", True), mp, opts.get("scale", "unit"), pelt)
    best = decide(system, ctx["log_t"], trace=opts.get("trace_joint", False), forced={a for a in range(len(ids)) if b.must_tie(ids[a])})
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
    out = finish(new, {**ctx, "final": set(ids)}, opts, ops)
    out["tied"] = sorted(ids[a] for a in best["tied"])
    return out
