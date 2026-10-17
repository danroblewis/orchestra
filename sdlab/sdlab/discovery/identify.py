"""identify(): several ways of estimating the matrix, and the one whose model behaves best on the data.

A model is judged as the goal judges it: run forward from many moments in the measured data and
compared with what was measured (its own estimated outside inflows feed it), over 5, 20 and 100
steps (loops that only mimic an outside input drift apart later). Only the data is used.
"""

from __future__ import annotations

from .matrix import identify_one
from .simulate import behaviour_error

# each combination of: forward or backward search; outside inflows that change or stay constant;
# trusting the receivers or the rows where stocks are seen receiving more than a stock's own row
# says it loses; and (with announced eras) numbers per configuration
VARIANTS: list[dict] = []
for search in ({"name": "forward"}, {"name": "backward", "backward_max": 20}):
    for inflow in ({"name": "changing inflows"}, {"name": "constant inflows", "changes": False}):
        for recv in ({"name": "trust receivers"}, {"name": "trust rows", "trust_receivers": False}):
            for era in ({"name": ""}, {"name": ", numbers per era", "split_eras": True}):
                VARIANTS.append({**search, **inflow, **recv, **era, "name": f"{search['name']}, {inflow['name']}, {recv['name']}{era['name']}"})


def judge(flows: list[dict], stocks: list[dict], run: dict, horizons=(5, 20, 100)) -> float:
    hs = [h for h in horizons if h < len(run["t"]) / 4]
    if not flows or not hs:
        return float("inf")
    ids = [s["id"] for s in stocks]
    return sum(behaviour_error(flows, ids, run["t"], run["levels"], horizon=h) for h in hs) / len(hs)


def identify(stocks: list[dict], run: dict, opts: dict | None = None) -> dict:
    opts = dict(opts or {})
    has_eras = len({e.get("label") or e.get("start") for e in opts.get("eras") or [] if e}) >= 2
    best, tried = None, []
    for v in opts.pop("variants", None) or VARIANTS:
        if v.get("split_eras") and not has_eras:
            continue
        r = identify_one(stocks, run, {**opts, **v})
        e = judge(r["flows"], stocks, run)
        tried.append({"name": v["name"], "error": e})
        if best is None or e < best[1]:
            best = (r, e, v["name"])
    r = best[0]
    r["chosen"], r["tried"] = best[2], tried
    return r
