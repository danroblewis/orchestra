"""The matrix method where a stock's outside inflow may change only once the data earns it.

(work in progress)
"""

from __future__ import annotations

import json
import os

import numpy as np

from ...identify import VARIANTS, judge
from ...matrix import finish, identify_one
from .joint import System, decide
from .rows import reselect


def refit(stocks: list[dict], r: dict, opts: dict) -> dict:
    """The candidate's rows refitted jointly, sources tied to their receivers where the counting
    likelihood says so; the model read off again."""
    fit, ctx = r.get("fit"), r.get("ctx")
    if not fit or not ctx:
        return r
    ids, rows = fit["ids"], fit["rows"]
    unit = {s["id"]: s.get("unit") or "" for s in stocks}
    final = {s["id"] for s in stocks if s.get("final")}
    L = len(fit["labels"])
    if opts.get("reselect", True):
        rows = [reselect(row, s, ids, stocks, fit["prev"], fit["dy"], fit["cfg"], L, opts.get("change_params", 2), opts.get("alpha", 0.01))["row"] for s, row in enumerate(rows)]
    system = System(rows, ids, unit, final, fit["dy"], fit["cfg"], L, opts.get("counting", True), opts.get("min_piece", 5), opts.get("scale", "unit"))
    best = decide(system, ctx["log_t"], trace=opts.get("trace_joint", False))
    at = fit["at"]
    new = []
    for s, row in enumerate(rows):
        coef_l = [{} for _ in range(system.L)]
        for q, b in zip(row["set"], best["beta"][s]):
            j, lab = row["col"][q]
            for c in range(system.L):
                if lab < 0 or lab == c:
                    coef_l[c][ids[j]] = coef_l[c].get(ids[j], 0.0) + float(b)
        u = best["inflow"][s]
        cuts = best["cuts"][s]
        inflow = [{"from": at[a], "to": at[b - 1], "value": float(u[a])} for a, b in zip(cuts[:-1], cuts[1:])] if cuts else []
        new.append({"id": row["id"], "coefL": coef_l, "inflow": inflow, "cuts": cuts, "set": [], "col": [],
                    "X": np.zeros((0, system.T)), "beta": np.zeros(0), "rss": 0.0, "p": 0})
    out = finish(new, {**ctx, "final": set(ids)}, opts)
    out["tied"] = sorted(ids[a] for a in best["tied"])
    return out


def identify(stocks: list[dict], run: dict, opts: dict | None = None) -> dict:
    opts = dict(opts or {})
    env = json.loads(os.environ.get("SDLAB_EARNED") or "{}")
    opts = {**opts, **env}
    joint = opts.pop("joint", True)
    has_eras = len({e.get("label") or e.get("start") for e in opts.get("eras") or [] if e}) >= 2
    best, tried = None, []
    for v in opts.pop("variants", None) or VARIANTS:
        if v.get("split_eras") and not has_eras:
            continue
        r = identify_one(stocks, run, {**opts, **v, "keep_fit": joint, "keep_rows": joint})
        if joint and r.get("flows") is not None and r.get("fit"):
            r = refit(stocks, r, opts)
        e = judge(r["flows"], stocks, run, injections=opts.get("injections"))
        tried.append({"name": v["name"], "error": e})
        if best is None or e < best[1]:
            best = (r, e, v["name"])
    r = best[0]
    for k in ("fit", "ctx", "raw_rows"):
        r.pop(k, None)
    r["chosen"], r["tried"] = best[2], tried
    return r
