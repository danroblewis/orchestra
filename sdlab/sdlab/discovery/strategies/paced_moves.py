"""Paced moves: the matrix read as stoichiometry x rate laws (discovery/stoich.py), beside the usual reading.

Every candidate of the main line (identify.VARIANTS) is also read with moves paced by a third stock
(matched entries refitted with one shared number), and with those moves' gaps on the destination; the
best of these readings by the judge is then offered gap inflows one (stock, driver) at a time, each kept if the
judge prefers it. All readings go before the same judge as the main line's candidates.

opts:
  "paced_readings": the readings offered beside the usual one (default ("paced", "destination", "gaps"))
  "match_z", "match_room": the matching test (stoich.match)
  "paced_discount" (0.15): a paced reading is kept unless its judged error is more than this share
      above the usual reading's (it has fewer free numbers)
  "gap_margin" (0.1): a gap inflow is kept only if it lowers the judged error by this share
"""

from __future__ import annotations

from ..identify import VARIANTS, judge
from ..matrix import identify_one, known_flows
from ..stoich import match, paced_flows


def identify(stocks: list[dict], run: dict, opts: dict | None = None) -> dict:
    opts = dict(opts or {})
    has_eras = len({e.get("label") or e.get("start") for e in opts.get("eras") or [] if e}) >= 2
    extra = known_flows(opts["known"], [s["id"] for s in stocks], run["t"]) if opts.get("known") else []
    offered = opts.get("paced_readings") or ("paced", "destination", "gaps")
    tol = opts.get("tol", 0.003)
    best, tried = None, []

    margin = opts.get("gap_margin", 0.1)
    # a reading with paced moves has fewer free numbers (one shared number for two, and the source's
    # drain that only imitated the cut-off gone): it is preferred unless its error is clearly larger
    discount = opts.get("paced_discount", 0.0)

    def consider(r, flows, label, info, price=0.0):
        # a reading's score is its error x (1 + price): a reading with gap inflows must beat the others
        # by `margin`; one with paced moves may be worse by `discount`
        nonlocal best
        e = judge(flows + extra if flows else [], stocks, run)
        tried.append({"name": label, "error": e})
        if best is None or e * (1 + price) < best[1]:
            best = ({**r, "flows": flows, "paced": info}, e * (1 + price), label)
        return e

    for v in opts.pop("variants", None) or VARIANTS:
        if v.get("split_eras") and not has_eras:
            continue
        r = identify_one(stocks, run, {**opts, **v, "keep_fit": True})
        fit = r.pop("fit", None)
        base = (consider(r, r["flows"], v["name"], None), {}, "", 0.0)       # error, options, name, price
        if not fit:
            continue
        groups = match(fit, stocks, tol, z=opts.get("match_z", 2.0), room=opts.get("match_room", 2.0))
        for name, o in (("paced", {}), ("destination", {"destination": True})):
            if name not in offered or not groups:
                continue
            flows, info = paced_flows(fit, stocks, tol, groups=groups, **o)
            if name == "destination" and not info["destination"]:
                continue
            price = -discount / (1 + discount)
            e = consider(r, flows, f"{v['name']}, {name}", info, price)
            if e * (1 + price) < base[0] * (1 + base[3]):
                base = (e, o, f", {name}", price)
        if "gaps" not in offered:
            continue
        # gap inflows, one (stock, driver) at a time, on the best reading so far
        g = groups if base[2] else []
        _, info = paced_flows(fit, stocks, tol, groups=g, gaps=True, **base[1])
        # each alone first; then, best first, each kept if the judge's error falls by gap_margin
        price = (1 + base[3]) * (1 + margin) - 1
        alone = []
        for stock in info["gaps"]:
            flows, inf = paced_flows(fit, stocks, tol, groups=g, gaps=[stock], **base[1])
            alone.append((consider(r, flows, f"{v['name']}{base[2]}, gap inflow {stock}", inf, price), stock))
        kept: list[str] = []
        err = base[0]
        for e1, stock in sorted(alone):
            if e1 >= err * (1 - margin):
                continue
            if kept:
                flows, inf = paced_flows(fit, stocks, tol, groups=g, gaps=[*kept, stock], **base[1])
                e1 = consider(r, flows, f"{v['name']}{base[2]}, gap inflows {', '.join([*kept, stock])}", inf, price)
            if e1 < err * (1 - margin):
                kept, err = [*kept, stock], e1
    r = best[0]
    if not r.get("paced"):
        r.pop("paced", None)
    r["chosen"], r["tried"] = best[2], tried
    return r
