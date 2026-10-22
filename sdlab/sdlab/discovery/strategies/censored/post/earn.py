"""Terms of an outside rate that earn nothing are dropped (censored port, 2026-10-22; the fix ledger's type 17,
"spurious flows must earn their place", applied to the terms of one rate; the pair drop is milp's
`refit.pair_drops` idea, d44d014, written here anew).

A floored side fitted while other stages were still to come can keep terms that move nothing on the run: 311
none-long's scale-down came out as `max(0, 12 + ready - desired - 4 nodes)`, and while one node is down (nodes 2)
ready stays at least 4 below desired, so `12 - 4 nodes` never changes what the floored rate moves. Each linear
rate on an estimated outside side (not an expression, not a flow in pieces, not one reading an offered series) is
tried with one of its numbers, and with each pair of them, set to nothing; the drop is kept when the whole model's
BIC on combined's judge (judge.score, the price of every number in) falls, so the data must pay for every term.
"""

from __future__ import annotations

import copy
import itertools

from . import judge as J
from .repair import _fixed_side

MAX_NUMBERS = 6      # rates with more numbers than this are left alone (pairs grow as the square)


def apply(result: dict, stocks: list[dict], run: dict, opts: dict | None) -> dict:
    if not isinstance(result, dict) or not result.get("flows") or (opts or {}).get("eras"):
        return result
    try:
        return _apply(result, stocks, run, opts or {})
    except Exception as e:                            # noqa: BLE001  (the answer stands as it was)
        return {**result, "earn": {"error": f"{type(e).__name__}: {e}"[:300]}}


def _numbers(rate: dict) -> list:
    """The droppable numbers of a linear rate: "1" for its constant, else the stock each term reads."""
    out = ["1"] if float(rate.get("c") or 0.0) != 0.0 else []
    return out + [t.get("stock") for t in rate.get("terms") or []]


def _without(rate: dict, drop: tuple) -> dict | None:
    c = 0.0 if "1" in drop else float(rate.get("c") or 0.0)
    terms = [dict(t) for t in rate.get("terms") or [] if t.get("stock") not in drop]
    if not terms:
        return None if c == 0.0 else {"form": "constant", "value": c}
    if c == 0.0 and len(terms) == 1:
        return {"form": "proportional", "stock": terms[0]["stock"], "k": float(terms[0]["k"])}
    return {"form": "linear", "c": c, "terms": terms}


def _apply(result: dict, stocks: list[dict], run: dict, opts: dict) -> dict:
    data = J.Data(stocks, run, opts.get("injections"), opts.get("inputs"))
    bound = run.get("boundary") or {}
    declared = bool(run.get("boundary_declared"))
    flows = copy.deepcopy(result["flows"])
    starts = {h: v[0] for h, v in (result.get("inferred_levels") or {}).items() if v}
    best = J.score(flows, data, starts=starts)["bic"]
    notes = []
    for i in range(len(flows)):
        f = flows[i]
        r = f.get("rate") or {}
        if (f.get("from") and f.get("to")) or r.get("form") != "linear" or f.get("inflow") or f.get("byTime") \
                or f.get("via") or f.get("uses") or _fixed_side(f, bound, declared):
            continue
        if any(str(t.get("stock", "")).startswith(("capmin__", "room__")) for t in r.get("terms") or []):
            continue
        nums = _numbers(r)
        if len(nums) < 2 or len(nums) > MAX_NUMBERS:
            continue
        top = None
        for size in (1, 2):
            for drop in itertools.combinations(nums, size):
                rate = _without(r, drop)
                if rate is None:
                    continue
                cand = flows[:i] + [{**f, "rate": rate, "rates": [rate]}] + flows[i + 1:]
                b = J.score(cand, data, starts=starts)["bic"]
                if b < best and (top is None or b < top[0]):
                    top = (b, cand, drop)
        if top is not None:
            best, flows = top[0], top[1]
            notes.append({"flow": f"{f.get('from')} -> {f.get('to')}", "dropped": list(top[2]), "bic": round(best, 2)})
    if not notes:
        return result
    return {**result, "flows": flows, "earn": notes}
