"""(realistic_hats: copied from matrix/earned.py at 49e4ca7, with earned_rows.py and earned_joint.py, as the
base in place of identify.identify; kubernetes 303 counts-short, docs/research/k8s-303-realistic-hats.md.)

The main line (identify.identify) with each candidate's pieces earned: a copy of earned_pieces
(sdlab/discovery/strategies/earned_pieces/__init__.py, rows.py, joint.py at 66086e7; strategies are
isolated, so this package carries its own copy and never imports that one).

Every candidate is fitted by matrix.identify_one with its cheap pieces, then rebuilt before the
behaviour judge chooses: each row's levels are chosen again and its outside-inflow pieces dropped
when a constant (or no) inflow leaves white residuals and a lower BIC with every change priced as a
value and a place, or replaced by changes found again at the textbook price when those win on the
same BIC (earned_rows.py; the second is this copy's addition: without it, a stock whose inflow
really changes but which settles fast after each change lost its pieces and came out an integrator,
drain near 0); conservation is decided for all rows at once on the counting
likelihood (earned_joint.py). Without this, chance pieces on a stock with no outside inflow could
win the in-sample judge (302 counts-short: four pieces of a 32-per-step drain on inflight, after a
final counter fixed inflight's drain; docs/research/k8s-302.md). The judge, the candidates, known
changes, "candidates" and "variants" are the main line's.
"""

from __future__ import annotations

import numpy as np

from ...identify import VARIANTS, judge
from ...matrix import finish, identify_one, known_flows
from . import boundary
from .earned_joint import System, decide
from .earned_rows import reselect, rss_floor


def refit(stocks: list[dict], r: dict, opts: dict, b: boundary.Boundary | None = None) -> dict:
    """The candidate's rows refitted jointly, sources tied to their receivers where the counting
    likelihood says so; the model read off again (earned_pieces.refit).

    (this copy) Inside the boundary b (boundary.py): a row has an outside term (constant or pieces)
    only where its stock may have an estimated outside flow, reads a measured input only where it may
    have a measured one, and reads a stock of another unit (a link from or a drain to outside) only
    where it may have an estimated one; a source with no estimated outflow to outside is tied (its
    drain is all moves)."""
    b = b or boundary.Boundary({})
    fit, ctx = r.get("fit"), r.get("ctx")
    if not fit or not ctx:
        return r
    ids, rows = fit["ids"], fit["rows"]
    names, columns = ctx.get("names") or ids, ctx.get("columns", fit["prev"])
    inputs = list(range(len(ids), len(names))) if ctx.get("inputs") else []
    unit = {s["id"]: s.get("unit") or "" for s in stocks}
    final = {s["id"] for s in stocks if s.get("final")}
    L = len(fit["labels"])
    floor = rss_floor(fit["prev"], fit["dy"].shape[1])

    def exclude(s: int) -> tuple:
        out = [] if b.inputs_ok(ids[s]) else list(inputs)
        if not b.links_ok(ids[s]):
            out += [j for j in range(len(ids)) if unit[ids[j]] != unit[ids[s]]]
        return tuple(out)

    rows = [reselect(row, s, ids, stocks, columns if inputs else fit["prev"], fit["dy"], fit["cfg"], L, 2, 0.01, floor, "beside", inputs,
                     pieces_ok=b.pieces_ok(ids[s]), exclude=exclude(s))["row"]
            for s, row in enumerate(rows)]
    system = System(rows, ids, unit, final, fit["dy"], fit["cfg"], L, True, opts.get("min_piece", 5), "unit")
    best = decide(system, ctx["log_t"], forced={a for a in range(len(ids)) if b.must_tie(ids[a])})
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


def main_line(stocks: list[dict], run: dict, opts: dict | None = None) -> dict:
    """identify.identify, each candidate refitted (refit) before it is judged; (this copy) inside the
    announced boundary (boundary.py): refitted inside it, then guarded, so the judge only sees
    candidates without an undeclared outside flow."""
    opts = dict(opts or {})
    b = boundary.Boundary(run)
    keep = opts.pop("candidates", False)
    has_eras = len({e.get("label") or e.get("start") for e in opts.get("eras") or [] if e}) >= 2
    best, tried, candidates = None, [], []
    extra = known_flows(opts["known"], [s["id"] for s in stocks], run["t"]) if opts.get("known") else []
    for v in opts.pop("variants", None) or VARIANTS:
        if v.get("split_eras") and not has_eras:
            continue
        r = identify_one(stocks, run, {**opts, **v, "keep_fit": True, "keep_rows": True, "input_columns": True})
        if r.get("flows") is not None and r.get("fit"):
            try:
                r = refit(stocks, r, opts, b)
            except np.linalg.LinAlgError:       # a degenerate joint fit: the candidate as the matrix fitted it
                pass
        for k in ("fit", "ctx", "raw_rows"):
            r.pop(k, None)
        if b.declared and r.get("flows"):
            r = boundary.apply(r, stocks, run, opts, final=False)
        e = judge(r["flows"] + extra if r["flows"] else [], stocks, run, injections=opts.get("injections"),
                  inputs=opts.get("inputs"))
        tried.append({"name": v["name"], "error": e})
        if keep:
            candidates.append({"name": v["name"], "error": e, "flows": r["flows"]})
        if best is None or e < best[1]:
            best = (r, e, v["name"])
    r = best[0]
    r["chosen"], r["tried"] = best[2], tried
    if keep:
        r["candidates"] = candidates
    return r
