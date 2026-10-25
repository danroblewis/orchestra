# Vendored for combined2 from sdlab/discovery/strategies/structures/__init__.py at commit 7e0a2bf (HEAD ebe9a4f); imports
# rewritten to these copies, otherwise unchanged (CLAUDE.md invariant 11). Re-vendor rather than edit.
"""structures: combined's model, replaced by one built from the classic SD structures when the data
prefer it (docs/research/structures.md).

1. The search (discover.py), under its own time cap (step 2 runs first): each stock's change regressed on its own
   (rowwise.py) and read as terms, then a stepwise BIC search over plain terms (constants, drains,
   moves, links, goal gaps), bilinear terms (a flow proportional to one stock times a linear effect
   of another or the same: S x I, P x A, crowding X x X), multi-stock goal gaps closed at one shared
   time (gaps.py), and one hidden Erlang chain of order 1-4 whose delay is profiled (a supply line,
   a construction or transmission delay, a hidden rework stock). Outside inflows are floored at 0 as
   the engine floors them.
2. combined (unchanged, through its identify()): the base answer.
   combined runs first, so it runs exactly as it does alone; the search gets at most 60% of
   the time the caller's timer leaves after it, less 10 s.
3. The search's model replaces the base only when combined's own judge prefers it (its one-step
   likelihood with a BIC price on every number, judge.py) AND it behaves at least as well over many
   steps on the run (combined's behaviour judge, within `slack`) with no more numbers than the
   base's, or clearly better (CLEARLY x the base's error) with more. Otherwise combined's model is
   returned as it is. Chains under MIN_DELAY (3) steps, and a chain from A to B beside a move or
   link from A to B, are never offered (measurement noise makes them fit).

opts (also SDLAB_STRUCTURES, JSON): "seconds" (the search's cap, default 90, never more than
60% of what the caller's timer leaves after combined, less 10 s for the judge), "slack" (relative, default 0.02), "base" ("combined" or
"lna_stack"), "alone" (return the search's model, for diagnosis), "chains", "products".
"""

from __future__ import annotations

import json
import os
import time

from orchestra.sdlab.discovery.strategies.combined2._vendored.combined import identify as combined
from orchestra.sdlab.discovery.strategies.combined2._vendored.combined import judge as J
from orchestra.sdlab.discovery.strategies.combined2._vendored.combined.deadline import Overrun, deadline, outer_left
from orchestra.sdlab.discovery.strategies.combined2._vendored.lna_stack import identify as lna_stack
from .discover import discover

DEFAULTS = {"seconds": 90.0, "slack": 0.02, "base": "combined", "alone": False, "chains": True, "products": True}
CLEARLY = 0.8        # a search model with more numbers than the base must behave this much better
BASES = {"combined": combined, "lna_stack": lna_stack}


def identify(stocks: list[dict], run: dict, opts: dict | None = None) -> dict:
    opts = dict(opts or {})
    env = json.loads(os.environ.get("SDLAB_STRUCTURES") or "{}")
    own = {k: opts.pop(k) for k in list(opts) if k in DEFAULTS}
    cfg = {**DEFAULTS, **own, **env}
    if cfg["alone"]:
        mine = discover(stocks, run, opts, seconds=float(cfg["seconds"]), chains=cfg["chains"], products=cfg["products"])
        r = mine or {"flows": []}
        return {**r, "canon": {k: r.get(k) for k in ("terms", "trace", "bic", "seconds")}}
    base = BASES[cfg["base"]](stocks, run, opts)          # first, so the base runs exactly as it does alone
    left = outer_left()
    cap = float(cfg["seconds"]) if left is None else min(float(cfg["seconds"]), 0.6 * left - 10)
    began = time.perf_counter()
    mine, why = None, None
    if opts.get("eras") and len(opts["eras"]) > 1:
        why = "announced eras (the search fits one set of numbers)"
    elif cap < 1:
        why = "no time left"
    else:
        try:
            with deadline(cap + 1.0):                    # a hard stop besides the search's own checks
                mine = discover(stocks, run, opts, seconds=cap, chains=cfg["chains"], products=cfg["products"], base_flows=base.get("flows"))
            why = None if mine else "no model in time"
        except Overrun:
            why = "no model in time"
        except Exception as e:                           # noqa: BLE001
            why = f"{type(e).__name__}: {e}"[:300]
    spent = round(time.perf_counter() - began, 2)
    info = {"search_seconds": spent, "why": why}
    if mine and mine.get("flows"):
        try:
            info.update(_compare(mine, base, stocks, run, opts, float(cfg["slack"])))
        except Exception as e:                           # noqa: BLE001
            info["judge_error"] = f"{type(e).__name__}: {e}"[:300]
        info["terms"] = mine.get("terms")
        info["trace"] = mine.get("trace")
    if info.get("chosen") == "structures":
        out = {k: v for k, v in mine.items() if k in ("flows", "inferred_levels")}
        out["method"] = "structures"
        out["structures"] = info
        return out
    info["chosen"] = info.get("chosen") or cfg["base"]
    return {**base, "structures": info}


def _compare(mine: dict, base: dict, stocks: list[dict], run: dict, opts: dict, slack: float) -> dict:
    """combined's judge on both models: the search's wins on a lower BIC and behaviour no worse."""
    data = J.Data(stocks, run, opts.get("injections"), opts.get("inputs"))
    starts_m = {h: v[0] for h, v in (mine.get("inferred_levels") or {}).items() if v}
    starts_b = {h: v[0] for h, v in (base.get("inferred_levels") or {}).items() if v}
    sm = J.score(mine["flows"], data, 1.0, 0.0, starts_m)
    sb = J.score(base.get("flows") or [], data, 1.0, 0.0, starts_b)
    out = {"bic": {"structures": round(sm["bic"], 3), "base": round(sb["bic"], 3)}, "numbers": {"structures": sm["k"], "base": sb["k"]}}
    if not sm["bic"] < sb["bic"]:
        return out
    bm = J.behaviour(mine["flows"], data, run, starts_m)
    bb = J.behaviour(base.get("flows") or [], data, run, starts_b) if base.get("flows") else float("inf")
    out["behaviour"] = {"structures": round(bm, 6), "base": round(bb, 6)}
    # no more numbers than the base and behaving as well; or, with more numbers, behaving clearly better
    # (measurement noise on the levels lets bigger models win the one-step judge by a hair: 082, 087 meas)
    if (sm["k"] <= sb["k"] and bm <= bb * (1 + slack) + 1e-9) or bm <= CLEARLY * bb:
        out["chosen"] = "structures"
    return out
