"""row_crossover: the judge's pick, then each stock's row swapped for another candidate's where the
whole model behaves clearly better (sdlab/discovery/crossover.py; docs/research/row-crossover.md).

Options (beside identify's): crossover_margin (relative improvement a swap must bring, 0.05),
crossover_sweeps (2), crossover_judge (a function (flows, stocks, run) -> error used for the swaps;
default identify's in-data judge).

The in-data judge can be fooled by a flexible row (see the topic document): more choices per stock
give it more chances, so this is meant to run behind a stricter judge when one exists.
"""

from __future__ import annotations

from ..crossover import Pool, crossover
from ..identify import VARIANTS, judge
from ..matrix import identify_one, known_flows


def identify(stocks: list[dict], run: dict, opts: dict | None = None) -> dict:
    opts = dict(opts or {})
    margin = opts.pop("crossover_margin", 0.05)
    sweeps = opts.pop("crossover_sweeps", 2)
    swap_judge = opts.pop("crossover_judge", None) or judge
    has_eras = len({e.get("label") or e.get("start") for e in opts.get("eras") or [] if e}) >= 2
    extra = known_flows(opts["known"], [s["id"] for s in stocks], run["t"]) if opts.get("known") else []
    cands, tried, best = [], [], None
    for v in opts.pop("variants", None) or VARIANTS:
        if v.get("split_eras") and not has_eras:
            continue
        r = identify_one(stocks, run, {**opts, **v, "keep_rows": True})
        e = judge(r["flows"] + extra if r["flows"] else [], stocks, run)
        tried.append({"name": v["name"], "error": e})
        if "raw_rows" in r:
            if cands:                                   # the data's arrays are the same in every candidate
                for key in ("prev", "dy"):
                    r["ctx"][key] = cands[0]["result"]["ctx"][key]
            cands.append({"variant": v, "result": r})
            if best is None or e < best[1]:
                best = (len(cands) - 1, e)
    if best is None:                                   # too few steps: no rows to mix
        return {"flows": [], "note": "Too few steps.", "tried": tried}
    pool = Pool(cands, stocks, opts)
    start = pool.start(best[0])
    mix, r, e, swaps = crossover(pool, start, run, extra, margin=margin, sweeps=sweeps, judge=swap_judge)
    if not swaps:
        r = {k: v for k, v in cands[best[0]]["result"].items() if k not in ("raw_rows", "ctx")}
    name = cands[best[0]]["variant"]["name"]
    # each swap's stock and the error ratio it brought, so a bench run shows which swaps it took
    r["chosen"] = name + (" + rows swapped: " + ", ".join(f"{s['stock']} x{s['error'][1] / s['error'][0]:.2f}" for s in swaps) if swaps else "")
    r["tried"], r["swaps"] = tried, swaps
    return r
