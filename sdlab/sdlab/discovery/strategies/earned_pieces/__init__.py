"""The matrix method where a stock's outside inflow may change only once the data earns it
(docs/research/earned_pieces.md).

Every main-line candidate is fitted by matrix.identify_one, then rebuilt: each row's levels are
chosen again and its pieces dropped when a constant (or no) inflow leaves white residuals and a
lower BIC with changes priced honestly (rows.py); conservation is decided for all rows at once on
the counting likelihood (joint.py). The behaviour judge then chooses among the candidates.

Measured inputs (opts "inputs": {name: value per step aligned with t}) are columns of every row, as
in the matrix (which offers them to a caller that keeps its fit only on request, "input_columns"):
a row's levels chosen again may include them, the joint fit refits their numbers as free ones (an
input is never a source to tie), and the judge steps every candidate with them.
"""

from __future__ import annotations

import json
import os

import numpy as np

from ...identify import VARIANTS
from ...matrix import finish, identify_one
from ...simulate import behaviour_error
from . import boundary
from .joint import System, decide
from .rows import reselect, rss_floor


def judge(flows: list[dict], stocks: list[dict], run: dict, horizons=(5, 20, 100), injections: list[dict] | None = None,
          inputs: dict | None = None) -> float:
    """The main line's judge (identify.judge), with the measured inputs the flows read."""
    hs = [h for h in horizons if h < len(run["t"]) / 4]
    if not flows or not hs:
        return float("inf")
    ids = [s["id"] for s in stocks]
    return sum(behaviour_error(flows, ids, run["t"], run["levels"], horizon=h, injections=injections, inputs=inputs) for h in hs) / len(hs)


def refit(stocks: list[dict], r: dict, opts: dict, b: boundary.Boundary | None = None) -> dict:
    """The candidate's rows refitted jointly, sources tied to their receivers where the counting
    likelihood says so; the model read off again.

    Inside the boundary b (boundary.py, docs/research/declared-boundary.md): a row has an outside term
    (constant or pieces) only where its stock may have an estimated outside flow, reads a measured input
    only where it may have a measured one, and reads a stock of another unit (a link from or a drain to
    outside) only where it may have an estimated one; a source with no estimated outflow to outside is
    tied (its drain is all moves)."""
    b = b or boundary.Boundary({})
    fit, ctx = r.get("fit"), r.get("ctx")
    if not fit or not ctx:
        return r
    ids, rows = fit["ids"], fit["rows"]
    # the columns a row may read: the stocks' levels, then the measured inputs' (ctx["names"], the
    # matrix's; the levels alone without inputs)
    names, columns = ctx.get("names") or ids, ctx.get("columns", fit["prev"])
    inputs = list(range(len(ids), len(names))) if ctx.get("inputs") else []
    unit = {s["id"]: s.get("unit") or "" for s in stocks}
    final = {s["id"] for s in stocks if s.get("final")}
    L = len(fit["labels"])
    def exclude(s: int) -> tuple:
        out = [] if b.inputs_ok(ids[s]) else list(inputs)
        if not b.links_ok(ids[s]):
            out += [j for j in range(len(ids)) if unit[ids[j]] != unit[ids[s]]]
        return tuple(out)

    if opts.get("reselect", True) or b.declared:
        floor = rss_floor(fit["prev"], fit["dy"].shape[1])
        rows = [reselect(row, s, ids, stocks, columns if inputs else fit["prev"], fit["dy"], fit["cfg"], L, opts.get("change_params", 2), opts.get("alpha", 0.01), floor, opts.get("levels", "beside"), inputs,
                         pieces_ok=b.pieces_ok(ids[s]), exclude=exclude(s))["row"]
                for s, row in enumerate(rows)]
    system = System(rows, ids, unit, final, fit["dy"], fit["cfg"], L, opts.get("counting", True), opts.get("min_piece", 5), opts.get("scale", "unit"))
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
    out = finish(new, {**ctx, "final": set(ids)}, opts)
    out["tied"] = sorted(ids[a] for a in best["tied"])
    return out


def _identify(stocks: list[dict], run: dict, opts: dict | None = None) -> dict:
    opts = dict(opts or {})
    env = json.loads(os.environ.get("SDLAB_EARNED") or "{}")
    opts = {**opts, **env}
    joint = opts.pop("joint", True)
    b = boundary.Boundary(run)
    has_eras = len({e.get("label") or e.get("start") for e in opts.get("eras") or [] if e}) >= 2
    best, tried = None, []
    for v in opts.pop("variants", None) or VARIANTS:
        if v.get("split_eras") and not has_eras:
            continue
        r = identify_one(stocks, run, {**opts, **v, "keep_fit": joint, "keep_rows": joint, "input_columns": True})
        if joint and r.get("flows") is not None and r.get("fit"):
            try:
                r = refit(stocks, r, opts, b)
            except np.linalg.LinAlgError:       # a degenerate joint fit: the candidate as the matrix fitted it
                pass
        if b.declared and r.get("flows"):
            # the guard before the judge (boundary.py): no candidate with an undeclared outside flow
            r = boundary.apply({k: v for k, v in r.items() if k not in ("fit", "ctx", "raw_rows")}, stocks, run, opts, final=False)
        e = judge(r["flows"], stocks, run, injections=opts.get("injections"), inputs=opts.get("inputs") or None)
        tried.append({"name": v["name"], "error": e})
        if best is None or e < best[1]:
            best = (r, e, v["name"])
    r = best[0]
    for k in ("fit", "ctx", "raw_rows"):
        r.pop(k, None)
    r["chosen"], r["tried"] = best[2], tried
    return r


def identify(stocks: list[dict], run: dict, opts: dict | None = None) -> dict:
    """The answer above with its numbers refitted by instrumental variables where the levels carry
    measurement error (eiv.py), then kept inside the announced boundary (boundary.py,
    docs/research/declared-boundary.md: the guard and moves where one is declared, each outside flow
    priced as a boundary claim where none is)."""
    from .eiv import apply

    return boundary.apply(apply(_identify(stocks, run, dict(opts or {})), stocks, run, opts), stocks, run, opts)
