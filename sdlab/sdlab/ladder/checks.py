"""Checks a case must pass to be on the ladder (adapted from tests/test_sd_examples.py): its runs stay
sane, keep exercising the model, and every flow moves, so the flows are identifiable in principle.

    problems(case) -> ["A grew from at most 40 to 9000", ...]     (empty: the case is fine)

Over five times the case's longest length, with counting noise: every level finite and never
negative; a stock that is not final stays within 5x (+50) of its highest level in the first short
run; everything that moved is accounted for (each stock's change is its inflows minus its outflows,
what co-flows used, plus injections); every flow moves; and over the longest variant, every stock
that is not final keeps moving as much late in the run as early on (the spread of its step changes in the last tenth at least half the second
tenth's; a run under 20 steps compares its last quarter with its second, and one under 8 steps is not checked). Without noise: every measured stock's level changes over each variant's run. (Queue item 2d: a signed
stock may go negative, a switch is not checked as a stock, and a two-way flow moves when it moves either way.)
"""

from __future__ import annotations

import math
import statistics

from .cases import truth_model
from .data import load, simulate


def problems(case: dict) -> list[str]:
    if case.get("real"):             # a real-data case (real/): measured data, not an engine run to check
        return []
    if case.get("example"):          # a realistic case (realistic.py) is an example as it is: never changed for a check
        return []
    out: list[str] = []
    counts = [v for v in case["variants"] if v["noise"] == "counts"]
    if counts:
        v = max(counts, key=lambda v: v["steps"])
        model = truth_model(case, v["name"])
        short = min(x["steps"] for x in counts)
        r = simulate(model, steps=v["steps"] * 5)
        final = {s["id"] for s in model["stocks"] if s.get("final")}
        signed = {s["id"] for s in model["stocks"] if s.get("signed")}               # 2d: a signed stock may go negative
        switch = {s["id"] for s in model["stocks"] if s.get("switch")}               # 2d: a switch is 0 or 1, set by its rule
        for s, lv in r["all_levels"].items():
            if s in switch:
                continue
            if not all(math.isfinite(x) and (x >= 0 or s in signed) for x in lv):
                out.append(f"{s} goes negative or not finite")
            first = max(lv[:short])
            if s not in final and max(lv) > 5 * first + 50:
                out.append(f"{s} grew from at most {first} to {max(lv)}")
            lv = lv[: v["steps"]]                        # moving: over the case's own longest run
            w = len(lv) // 10 if len(lv) >= 20 else len(lv) // 4     # under 20 steps a tenth has under 2 changes: quarters
            early, late = lv[w: 2 * w], lv[-w:]
            spread = lambda a: statistics.pstdev([b - x for x, b in zip(a, a[1:])])  # noqa: E731
            if s not in final and w >= 2 and spread(early) > 0 and spread(late) < 0.5 * spread(early):
                out.append(f"{s} stops moving: {spread(late):.2f} late vs {spread(early):.2f} early")
        start = {s["id"]: float(s.get("initial") or 0) for s in model["stocks"]}
        for s in (x for x in start if x not in switch):
            net = sum(j["amount"] for j in r.get("injections") or [] if j["stock"] == s) + sum(sum(r["counters"][f["id"]]) for f in model["flows"] if f.get("to") == s) \
                - sum(sum(r["counters"][f["id"]]) * float(f.get("ratio") or 1) for f in model["flows"] if f.get("from") == s) \
                - sum(sum(r["counters"][f["id"]]) * float(u.get("per") or 0) for f in model["flows"] for u in f.get("uses") or [] if u.get("stock") == s)
            if abs(start[s] + net - r["all_levels"][s][-1]) > 1e-6 * max(1, abs(net)) + 1:
                out.append(f"{s}: its flows do not add up to its level")
        for f in model["flows"]:
            if sum(abs(x) for x in r["counters"][f["id"]]) <= 0:
                out.append(f"flow {f['id']} never moves")
    for v in case["variants"]:
        if v["noise"] != "none":
            continue
        d = load(case, v["name"])
        for s, lv in d["levels"].items():
            if max(lv) - min(lv) <= 0:
                out.append(f"{s} never changes in {v['name']}")
    return out
