"""Floors and caps: flows estimated in the form the engine steps them.

SD Lab's engine floors every rate at 0 and lets no stock give more than it holds (its outflows share
what it has). Where either binds, a stock's change is not the straight line the matrix method fits,
so its numbers bend toward those steps. This strategy is the matrix method (every candidate of
identify.VARIANTS, judged the same way) with two additions, each giving more candidates:

- **Caps** (caps.py, on by default): the found model says which outflows wanted more than their
  stock held, the data confirms the stock was emptied, the shortfall is added back to the changes
  and the rows are fitted again (a round of EM for censored data; sd-orders: a constant sale of 15 a
  day read as 21.8 a day plus "stock grows with itself" until the cut steps are undone).
- **Floors** (hinges.py, opts["hinges"]; off by default, see the experiment log): a column
  `max(0, +-(x - theta))` per stock whose level shows a kink, its threshold chosen from the data,
  offered to every row beside the levels; a row that takes it has a flow with a floor, read as
  `linear {c, terms}` that the model floors exactly as the truth does.

Every candidate (each round of the caps, with or without hinges) is judged on the data as identify()
judges; a round that runs away (a wrong model inventing cuts) is never chosen over the plain fit.
"""

from __future__ import annotations

import math

import numpy as np

from .. import hinges
from ..caps import flow_amounts, shortfall
from ..identify import VARIANTS, judge
from ..matrix import identify_one


def levels(stocks: list[dict], run: dict) -> np.ndarray:
    t = run["t"]
    return np.nan_to_num(np.array([np.asarray(run["levels"].get(s["id"], [0] * len(t)), dtype=float) for s in stocks]))


def rounds_of(stocks: list[dict], run: dict, opts: dict, rounds: int = 3):
    """The plain fit, then each refit on the changes with the cut-off outflows added back."""
    ids = [s["id"] for s in stocks]
    lv = levels(stocks, run)
    r = identify_one(stocks, run, opts)
    yield 0, r
    for k in range(1, rounds + 1):
        if not r.get("flows"):
            return
        adj, capped = shortfall(r["flows"], ids, run["t"], lv[:, :-1], lv[:, 1:] if opts.get("confirm", True) else None)
        if not capped.any():
            return
        r = identify_one(stocks, run, {**opts, "dy_adjust": adj})
        r["capped"] = {i: int(c) for i, c in zip(ids, capped.sum(axis=1)) if c}
        yield k, r


def find_hinges(stocks: list[dict], run: dict, opts: dict, cap_factor: float = 2.0, greedy: bool = True, same_unit: bool = True) -> list[dict]:
    """Hinges chosen on the changes beside all the levels, with each row's outside inflow in the
    pieces a plain fit finds for it. A kink where a stock holds about one step's outflow is the
    engine's cap (an emptied stock gives what it has), not a floor: the caps are left to the EM
    rounds, so a stock's thresholds are tried only above `cap_factor` x its typical outflow a step
    in the plain fit."""
    plain = identify_one(stocks, run, opts)
    if not plain.get("matrix"):
        return []
    lv = levels(stocks, run)
    ids = [s["id"] for s in stocks]
    ends, amt = flow_amounts(plain["flows"], ids, run["t"], lv[:, :-1])
    out = np.zeros_like(lv[:, :-1])
    for (src, _, ratio), a in zip(ends, amt):
        if src is not None:
            out[src] += a * ratio
    above = cap_factor * np.median(out, axis=1) if cap_factor else None
    return hinges.choose(stocks, lv[:, :-1], np.diff(lv, axis=1), [row.get("cuts") for row in plain["matrix"]], above=above,
                          greedy=greedy, same_unit=same_unit)


def bic_of(r: dict, T: int, extra: int) -> float:
    """The rows' BIC summed (each row's numbers and inflow pieces), plus a threshold per hinge."""
    rows = r.get("matrix") or []
    if not rows:
        return float("inf")
    return sum(T * math.log(max(row["rss"], 1e-12) / T) + row["p"] * math.log(T) for row in rows) + extra * math.log(T)


def _chain(first, rest):
    yield first
    yield from rest


# cap_rounds: EM rounds for the caps (0: none); hinges: look for floors; select: how a variant's
# fit with floors is preferred to its plain fit ("judge": both are candidates for the judge; "bic":
# the rows' BIC; "both": BIC, and the judge no worse than judge_slack x); cap_factor, greedy,
# same_unit: how hinges are chosen (find_hinges, hinges.choose)
DEFAULTS = {"cap_rounds": 3, "hinges": False, "select": "judge", "judge_slack": 1.5, "cap_factor": 0, "greedy": True, "same_unit": True}


def identify(stocks: list[dict], run: dict, opts: dict | None = None) -> dict:
    opts = {**DEFAULTS, **(opts or {})}
    o_ = {k: opts.pop(k) for k in DEFAULTS}
    rounds, select, slack = o_["cap_rounds"], o_["select"], o_["judge_slack"]
    has_eras = len({e.get("label") or e.get("start") for e in opts.get("eras") or [] if e}) >= 2
    variants = opts.pop("variants", None) or VARIANTS
    found = find_hinges(stocks, run, {**opts, **variants[0]}, o_["cap_factor"], o_["greedy"], o_["same_unit"]) if o_["hinges"] else []
    T = len(run["t"]) - 1
    best, tried = None, []

    def consider(family, v, extra):
        nonlocal best
        for k, r in family:
            e = judge(r["flows"], stocks, run)
            name = v["name"] + (", floors at " + ", ".join(h["id"] for h in extra) if extra else "") + (f", outflows uncut x{k}" if k else "")
            tried.append({"name": name, "error": e})
            if best is None or e < best[1]:
                best = (r, e, name)

    for v in variants:
        if v.get("split_eras") and not has_eras:
            continue
        o = {**opts, **v}
        family = rounds_of(stocks, run, o, rounds)
        if not found:
            consider(family, v, None)
            continue
        hinged = rounds_of(stocks, run, {**o, "extra_columns": found}, rounds)
        if select == "judge":                   # both families, the judge alone decides
            consider(family, v, None)
            consider(hinged, v, found)
            continue
        # with or without the floors by the rows' own BIC (the judge replays each model's outside
        # inflow pieces, so a plain fit whose pieces copy a kink's history wins there, while in BIC
        # every piece pays for itself); with "both", only if the judge does not find the floors
        # clearly worse on the data either
        plain0, hinged0 = next(family), next(hinged)
        take = bic_of(hinged0[1], T, len(found)) < bic_of(plain0[1], T, 0)
        if take and select == "both":
            take = judge(hinged0[1]["flows"], stocks, run) <= slack * judge(plain0[1]["flows"], stocks, run)
        consider(_chain(hinged0, hinged) if take else _chain(plain0, family), v, found if take else None)
    r = best[0]
    r["chosen"], r["tried"], r["hinges"] = best[2], tried, [{k: h[k] for k in ("id", "base", "theta", "sign", "score")} for h in found]
    return r
