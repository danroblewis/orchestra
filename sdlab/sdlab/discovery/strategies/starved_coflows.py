"""The matrix method plus candidates fitted where the used stocks did not run dry (discovery/starvation.py).

For each stock that runs low for a while (and for all of them together), the steps where it held
less than its users wanted are left out of the fit, the rows' cross terms "C drains faster when A is
high" become co-flows (`uses` of C on A's outflow, which the simulator caps), and every variant so
fitted joins the main line's candidates before the judge picks by behaviour on the data.

Options (defaults are the benched version): dry_low 0.5 (a candidate C is below half its median on
1% of steps), margin 1.5, refine 1, max_share 0.5 (C dry on at most half the steps), min_t 2
(A's residual on C's dry steps), moves_only True, same_unit False (C of another unit than A),
per_from "cross" ("dry": per from what the flow moved where the cap bound), remeasure_dry True,
prefer_coflows False (True: take the best co-flow candidate over the judge), starved_only False.
"""

from __future__ import annotations

import numpy as np

from ..identify import VARIANTS, judge
from ..matrix import identify_one, known_flows
from ..starvation import as_coflows, fill_gaps, first_mask, remeasure_inflows, starved_steps, stocks_running_dry

REFINE = {"name": "forward, changing inflows, trust receivers"}


def masks(stocks: list[dict], run: dict, opts: dict) -> list[tuple[list[str], np.ndarray]]:
    """The stocks found running dry, each alone and then all together, with the steps left out.

    For a stock C that runs low for a while: its users' demand is first measured where C is plentiful
    (every step with C below its median left out); C is kept only if its row shows users (a cross
    term "C drains faster when A is high") and held less than `margin` x what they want on at least
    a few steps; those steps are then left out and the demand measured again (`refine` times)."""
    ids = [s["id"] for s in stocks]
    final = {s["id"] for s in stocks if s.get("final")}
    unit = {s["id"]: s.get("unit") or "" for s in stocks}
    lv = np.nan_to_num(np.array([np.asarray(run["levels"].get(i, [0] * len(run["t"])), dtype=float) for i in ids]))
    margin, need_steps = opts.get("margin", 1.5), max(5, int(0.01 * (lv.shape[1] - 1)))
    max_share = opts.get("max_share", 0.5)          # a stock dry more than half the time is not running dry
    found: list[tuple[str, np.ndarray]] = []
    todo = [c for c in stocks_running_dry(lv, ids, low=opts.get("dry_low", 0.5)) if c not in final]
    # a second round tries the stocks not found in the first with the steps where the found ones were
    # dry left out too (one dry stock's cut hides another's users)
    for _ in range(2):
        base = np.logical_or.reduce([m for _, m in found]) if found else np.zeros(lv.shape[1] - 1, bool)
        added = False
        for c in list(todo):
            m, own = base | first_mask(lv, ids, [c], low=1.0), None
            for _ in range(1 + opts.get("refine", 1)):
                r = identify_one(stocks, run, {**opts, **REFINE, "keep": np.flatnonzero(~m)})
                users = None if opts.get("same_unit") else {i for i in ids if unit[i] != unit[c]}
                nxt = starved_steps(lv, ids, r["matrix"], c, margin, users) if r.get("matrix") else None
                if nxt is None or nxt.sum() < need_steps or (base | nxt).mean() > max_share:
                    break                                   # keep the last steps that showed users
                own, m = nxt, base | nxt
            if own is not None:
                found.append((c, own))
                todo.remove(c)
                added = True
        if not added or not found or not todo:
            break
    sets = [([c], m) for c, m in found]
    if len(found) > 1:
        union = np.logical_or.reduce([m for _, m in found])
        if union.mean() <= max_share:
            sets.append(([c for c, _ in found], union))
    return sets


def identify(stocks: list[dict], run: dict, opts: dict | None = None) -> dict:
    opts = dict(opts or {})
    ids = [s["id"] for s in stocks]
    has_eras = len({e.get("label") or e.get("start") for e in opts.get("eras") or [] if e}) >= 2
    extra = known_flows(opts["known"], ids, run["t"]) if opts.get("known") else []
    variants = opts.pop("variants", None) or VARIANTS
    lv = np.nan_to_num(np.array([np.asarray(run["levels"].get(i, [0] * len(run["t"])), dtype=float) for i in ids]))
    best: dict[bool, tuple | None] = {False: None, True: None}     # the main line's best, the co-flows' best
    tried, starved = [], []

    def consider(r, name, dry=False):
        e = judge(r["flows"] + extra if r["flows"] else [], stocks, run)
        tried.append({"name": name, "error": e})
        if best[dry] is None or e < best[dry][1]:
            best[dry] = (r, e, name)

    for v in variants if not opts.get("starved_only") else []:
        if v.get("split_eras") and not has_eras:
            continue
        consider(identify_one(stocks, run, {**opts, **v}), v["name"])
    for used, m in masks(stocks, run, opts):
        if not m.any() or (~m).sum() < 20:
            continue
        keep = np.flatnonzero(~m)
        for v in variants:
            if v.get("split_eras") and not has_eras:
                continue
            r = identify_one(stocks, run, {**opts, **v, "keep": keep})
            if not r.get("flows"):
                continue
            flows, found = as_coflows(r["flows"], r["matrix"], stocks, lv, run["t"], m, used, min_t=opts.get("min_t", 2.0),
                                      moves_only=opts.get("moves_only", True), per_from=opts.get("per_from", "cross"),
                                      same_unit=opts.get("same_unit", False))
            starved.append({"variant": v["name"], "used": used, "steps": int(m.sum()), "found": found})
            if not any(f.get("uses") for f in flows):
                continue
            flows = fill_gaps(flows, run["t"])
            if opts.get("remeasure_dry", True):
                flows = remeasure_inflows(flows, stocks, lv, run["t"], changes=v.get("changes") is not False)
            r = {**r, "flows": flows}
            consider(r, f"{v['name']}, {'+'.join(used)} dry on {int(m.sum())} steps left out", dry=True)
    # a co-flow that passed its test says the main line's rows mix two regimes (their inflow pieces
    # replay the pile-ups, which the judge, feeding each model its own inflows, cannot see): with
    # prefer_coflows the best co-flow candidate is taken whenever there is one
    pick = best[True] if best[True] and (opts.get("prefer_coflows", False) or best[False] is None or best[True][1] < best[False][1]) else best[False]
    r = pick[0]
    r["chosen"], r["tried"], r["starved"] = pick[2], tried, starved
    return r
