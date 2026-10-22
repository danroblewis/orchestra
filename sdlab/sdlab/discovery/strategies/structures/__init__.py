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

from ._vendored.combined import identify as combined
from ._vendored.combined import judge as J
from ._vendored.combined.deadline import Overrun, deadline, outer_left
from ._vendored.lna_stack import identify as lna_stack
from . import boundary, pairing
from .discover import discover

DEFAULTS = {"seconds": 90.0, "slack": 0.02, "base": "combined", "alone": False, "chains": True, "products": True}
CLEARLY = 0.8        # a search model with more numbers than the base must behave this much better
BASES = {"combined": combined, "lna_stack": lna_stack}


def _identify(stocks: list[dict], run: dict, opts: dict | None = None) -> dict:
    opts = dict(opts or {})
    env = json.loads(os.environ.get("SDLAB_STRUCTURES") or "{}")
    own = {k: opts.pop(k) for k in list(opts) if k in DEFAULTS}
    cfg = {**DEFAULTS, **own, **env}
    if cfg["alone"]:
        mine = discover(stocks, run, opts, seconds=float(cfg["seconds"]), chains=cfg["chains"], products=cfg["products"])
        r = mine or {"flows": []}
        return {**r, "canon": {k: r.get(k) for k in ("terms", "trace", "bic", "seconds")}}
    base = BASES[cfg["base"]](stocks, run, opts)          # first, so the base runs exactly as it does alone
    if base.get("flows"):
        # (pairing.py, copied from common_cause at f252b8c) the offered MIN series' two outside terms made the
        # move the offer found, before the guard pairs outside flows one at a time (306 counts-long: the guard
        # joined queue -> outside at the MIN to outside -> responses_total, which read ready)
        base = {**base, "flows": pairing.pair(base["flows"], opts)}
    if boundary.Boundary(run).declared and base.get("flows"):
        # the base kept inside the announced boundary (boundary.py's guard) before it is compared: its
        # own copy of combined searches with every outside flow open
        base = boundary.apply(base, stocks, run, opts, final=False)
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


def identify(stocks: list[dict], run: dict, opts: dict | None = None) -> dict:
    """The answer above with its numbers refitted by instrumental variables where the levels carry
    measurement error (eiv.py), then kept inside the announced boundary (boundary.py,
    docs/research/declared-boundary.md: the guard and moves where one is declared, each outside flow
    priced as a boundary claim where none is). The search itself offers only terms inside a declared
    boundary (discover.term_filter)."""
    from .eiv import apply

    return boundary.apply(apply(_identify(stocks, run, dict(opts or {})), stocks, run, opts), stocks, run, opts)


RESERVE = 90.0       # (k8s 317) seconds of the caller's timer each optional stage leaves for the stages after it


def _timed(stage, r, *args, **kw):
    """(k8s 317, docs/research/fixes/317-structures.md) An optional stage that rewrites the answer, run under what
    is left of the caller's timer less RESERVE; past it, or with no time left, the answer stands as it came (the
    stage's name noted). 317 (36 stocks) ran 1000 s here and over 1800 s on node2, and a timeout scores nothing,
    while each of these stages only improves an answer that already exists. With no timer, the stage just runs."""
    left = outer_left()
    if left is None:
        return stage(r, *args, **kw)
    name = f"{getattr(stage, '__module__', '').rsplit('.', 1)[-1]}.{getattr(stage, '__name__', 'stage')}"
    if left <= RESERVE + 1.0:
        return {**r, "skipped": [*(r.get("skipped") or []), name]} if isinstance(r, dict) else r
    try:
        with deadline(left - RESERVE):
            return stage(r, *args, **kw)
    except Overrun:
        return {**r, "skipped": [*(r.get("skipped") or []), f"{name} (stopped)"]} if isinstance(r, dict) else r


# A capacity limit offered to the fit (capmin.py, docs/research/k8s-306-s1.md, 2026-10-21): identify above
# runs with the regime-clipped series MIN(X, theta x Y) as one more measured input where the data show a
# limit, and every term that reads it is written back as MIN(a x X, a theta x Y).
from . import capmin as _capmin  # noqa: E402

_identify_linear = identify


def identify(stocks: list[dict], run: dict, opts: dict | None = None, *args, **kw) -> dict:  # noqa: F811
    """(2026-10-21, k8s-307, docs/research/k8s-307-c1.md) Between the fit and the MIN written back, where the
    levels carry measurement error, the numbers are refitted and the structure revised on the output error
    and judged on a Kalman likelihood (oefit.py, a copy of combined2's: the model run through the whole
    record against the measured levels)."""
    from . import floor, moves, oefit, rebuild

    o, cap = _capmin.offer(stocks, run, opts)
    r = _identify_linear(stocks, run, o, *args, **kw)
    # (k8s 312, docs/research/fixes/312-structures.md) rows whose missing terms are moves rebuilt together by
    # best subset and their terms paired into moves, before the single-row rebuild below writes them as sides
    r = moves.coflows(_timed(moves.apply, r, stocks, run, o), stocks, run, o)
    # (k8s 317, docs/research/fixes/317-structures.md) every row a candidate, not only those far from exact: on 36
    # stocks the base's rows are exact but crossed (a retries loop written as outside terms reading the queue, a
    # service's dispatch landing in another's inflight), and the best-subset rows paired into moves are sparser
    r = _timed(moves.apply, r, stocks, run, o, every=True)
    # (k8s 311, docs/research/fixes/311-structures.md) rows the forward-stepwise fits left far from exact (a fast
    # equilibrium no single column explains) rebuilt by best subset, before the floor refits their sides
    r = _timed(rebuild.apply, r, stocks, run, o)
    # (k8s-309, docs/research/fixes/309-structures.md) outside rates refitted under the engine's floor before
    # the output-error refit, which would read a floored rate fitted as a drift as measurement error
    r = _timed(floor.apply, r, stocks, run, opts, judge_opts=o)
    try:
        r = _timed(oefit.refit, r, stocks, run, o, cap)
    except Exception as e:                           # noqa: BLE001  (a failed refit leaves the answer as it was: 309 none-long)
        r = {**r, "oefit_error": f"{type(e).__name__}: {e}"[:300]}
    return _capmin.restore(r, cap)


# A stock set by a discrete controller (controller.py, docs/research/fixes/308-structures.md, 2026-10-21): a
# whole-number stock whose every step's change a target-tracking rule reproduces exactly gets that rule as
# its outside flows in place of the fitted rates.
_identify_capmin = identify


def identify(stocks: list[dict], run: dict, opts: dict | None = None, *args, **kw) -> dict:  # noqa: F811
    from . import controller

    return controller.apply(_identify_capmin(stocks, run, opts, *args, **kw), stocks, run, opts)


# A counted move with a threshold effect (counted.py, docs/research/fixes/310-structures.md, 2026-10-21): a
# counter's increments fitted as A x table(X), written as its inflow and offered as the move A -> B it counts.
_identify_controller = identify


def identify(stocks: list[dict], run: dict, opts: dict | None = None, *args, **kw) -> dict:  # noqa: F811
    from . import counted, repair, room

    r = _identify_controller(stocks, run, opts, *args, **kw)
    # (k8s 311, docs/research/fixes/311-structures.md) a move limited by the room a capacity leaves, searched on
    # the rows the answer leaves unexplained, before the repair and the counted move
    r = _timed(room.apply, r, stocks, run, opts)
    # (k8s 310, 2026-10-22) the rows repaired first (repair.py): a counted move is placed by the rows it
    # repairs, and 310 none-long had lost `pending -> ready`, so the OOM move could not be placed
    r = _timed(repair.apply, r, stocks, run, opts)
    if "repair" in r:
        r = {**{k: v for k, v in r.items() if k != "repair"}, "repair_before_counted": r["repair"]}
    return _timed(counted.apply, r, stocks, run, opts)


# A row that reads a hidden integrator and per-unit columns (hidden.py, docs/research/fixes/310-structures.md,
# 2026-10-22): an inflow side the answer leaves far from exact refitted with X / max(1, Y) columns and a hidden
# stock filled at 1 a step and drained at a constant rate or by a table effect the answer already carries.
_identify_counted = identify


def identify(stocks: list[dict], run: dict, opts: dict | None = None, *args, **kw) -> dict:  # noqa: F811
    from . import delay, hidden, room

    r = _timed(hidden.apply, _identify_counted(stocks, run, opts, *args, **kw), stocks, run, opts)
    # (k8s 311) the room move's numbers refitted last, its rows explained by everything else by then
    r = _timed(room.polish, r, stocks, run, opts)
    # (k8s 312) an outside inflow through a hidden first-order delay stage, on a row nothing else explains (after
    # the polish: the stage may read the room the polished move computes)
    return _timed(delay.apply, r, stocks, run, opts)


# Rows left unexplained repaired with the plain moves and outflows they lack (repair.py,
# docs/research/fixes/310-structures.md, 2026-10-22): the plain flows on rows far from exact refitted jointly
# (active set under the floor) and same-unit moves / declared outflows added one at a time on the rows' BIC.
_identify_hidden = identify


def identify(stocks: list[dict], run: dict, opts: dict | None = None, *args, **kw) -> dict:  # noqa: F811
    from . import repair

    return _timed(repair.apply, _identify_hidden(stocks, run, opts, *args, **kw), stocks, run, opts)
