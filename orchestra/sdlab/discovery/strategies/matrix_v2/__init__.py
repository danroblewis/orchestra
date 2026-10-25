"""matrix_v2: the matrix method with the fixes other strategies proposed for it, each an option
(docs/research/matrix_v2.md; queue item 6).

The shared library's matrix method (sdlab/discovery/identify.py, matrix.py, flows.py, regression.py)
is pinned, so this package carries its own copies (matrix.py, flows.py, regression.py, changes.py, and
identify() below, from commit aad5c7b) and changes those. With every option off it is the matrix.

  option          fix                                                          proposed by
  rss_floor       every BIC's rss floored at the data's rounding               earned_pieces
  pelt_mult 2     inflow changes priced at 2 log n (PELT), not 1               censored (re-cut)
  white           a constant inflow kept unless its residuals are not white    earned_pieces
  pool            pieces pooled into a few values and re-cut (case 027)        effect_hats
                  (pool_white: kept only if what it leaves is white: sd-pipeline)
  tie_se          conservation's tie tested with both rows' standard errors    earned_pieces
  falling_inflow  a negative cross reading read as a falling inflow (a gap)    censored (links)
  gap_inflow      a gap over several stocks as one floored linear inflow       structures
  pair_moves      a drain and a link at one level paired into a move           effect_hats
  products        a x c columns, c = a or the destination allowed              structures
                  ("after": offered to the finished row; products_guard: each candidate with
                  products is judged beside the same candidate without them)
  inputs_judge    the judge steps every candidate with the measured inputs     earned_pieces, censored
  exact           noise-free fits floored at float precision, exact ties walked
                  to the plainest set (032, 034, 035, 038 without noise)       common_cause
  earned          each candidate's rows refitted before the judge: pieces kept    earned_pieces (via
                  only where earned, conservation decided jointly (earned.py)   matrix, 8c507a8)

Options are OPTIONS (the defaults) under the caller's opts. For an ablation, the SDLAB_MATRIX_V2
environment variable (JSON) starts from every option off and turns on what it names (the ladder's
result store keys results by the code, not the environment, so ablations run outside it:
tests/study_matrix_v2.py).

The declared boundary (boundary.py, a copy of matrix/boundary.py at 723f72c; docs/research/declared-boundary.md;
not an option: the boundary is announced information): each row of this package's matrix.py reads a
measured input only where its stock may have a measured outside flow, and reads a stock of another unit
or holds an outside term (constant or pieces) only where it may have an estimated one; the earned refit
keeps rows inside it and ties every source with no estimated outflow; every candidate is guarded before
the judge, and the answer is kept inside the boundary (guard and moves where declared, each outside
flow priced as a boundary claim where not).
"""

from __future__ import annotations

import json
import os

import numpy as np

from ...simulate import behaviour_error
from . import boundary
from .earned import refit
from .matrix import identify_one, known_flows

# every option off: the matrix
OFF: dict = {"rss_floor": False, "pelt_mult": 1, "white": False, "pool": False, "pool_white": False, "tie_se": False, "falling_inflow": False,
             "gap_inflow": False, "fold_strict": False, "pair_moves": False, "products": False, "inputs_judge": False, "exact": False,
             "earned": False}

# the defaults: the combination chosen by the ablation (docs/research/matrix_v2.md): every fix that
# gained cells without losing more than the data's limits explain; pelt_mult 2, white, gap_inflow and
# inputs_judge each lost cells the others did not, and are off. inputs_judge is on since the measured-input
# cases (300-317): a judge blind to the inputs ranks every candidate that reads one as a runaway (302
# counts-short: 18.7 against 0.05) and picks a degenerate one. earned is on since 302 counts-short
# (docs/research/k8s-302-round2.md): chance pieces on inflight, pooled into one, won the judge without it
OPTIONS: dict = {**OFF, "rss_floor": True, "pool": True, "pool_white": True, "tie_se": True, "falling_inflow": True, "fold_strict": True,
                 "pair_moves": True, "products": "after", "exact": True, "inputs_judge": True,
                 "earned": True}

# each combination of: forward or backward search; outside inflows that change or stay constant;
# trusting the receivers or the rows where stocks are seen receiving more than a stock's own row
# says it loses; and (with announced eras) numbers per configuration (identify.VARIANTS)
VARIANTS: list[dict] = []
for search in ({"name": "forward"}, {"name": "backward", "backward_max": 20}):
    for inflow in ({"name": "changing inflows"}, {"name": "constant inflows", "changes": False}):
        for recv in ({"name": "trust receivers"}, {"name": "trust rows", "trust_receivers": False}):
            for era in ({"name": ""}, {"name": ", numbers per era", "split_eras": True}):
                VARIANTS.append({**search, **inflow, **recv, **era, "name": f"{search['name']}, {inflow['name']}, {recv['name']}{era['name']}"})


def judge(flows: list[dict], stocks: list[dict], run: dict, horizons=(5, 20, 100), injections: list[dict] | None = None,
          inputs: dict | None = None) -> float:
    """identify.judge: runs from many moments in the data over 5, 20 and 100 steps; with inputs (the
    option inputs_judge) every run reads the measured inputs the flows read."""
    hs = [h for h in horizons if h < len(run["t"]) / 4]
    if not flows or not hs:
        return float("inf")
    ids = [s["id"] for s in stocks]
    return sum(behaviour_error(flows, ids, run["t"], run["levels"], horizon=h, injections=injections, inputs=inputs) for h in hs) / len(hs)


def options(opts: dict | None) -> dict:
    """The defaults and the caller's opts; with SDLAB_MATRIX_V2 set (an ablation), every option starts
    off (the matrix) and the variable's options are turned on."""
    env = os.environ.get("SDLAB_MATRIX_V2")
    if env:
        return {**OFF, **(opts or {}), **json.loads(env)}
    return {**OPTIONS, **(opts or {})}


def one(stocks: list[dict], run: dict, opts: dict) -> dict:
    """identify_one; with the option earned, the candidate's rows refitted (earned.refit)."""
    b = boundary.Boundary(run)
    if not opts.get("earned"):
        r = identify_one(stocks, run, opts)
    else:
        r = identify_one(stocks, run, {**opts, "keep_fit": True})
        if r.get("flows") is not None and r.get("fit"):
            try:
                r = refit(stocks, r, opts, b)
            except np.linalg.LinAlgError:       # a degenerate joint fit: the candidate as the matrix fitted it
                pass
        for k in ("fit", "ctx"):
            r.pop(k, None)
    if b.declared and r.get("flows"):
        r = boundary.apply(r, stocks, run, opts, final=False)
    return r


def _identify(stocks: list[dict], run: dict, opts: dict | None = None) -> dict:
    opts = options(opts)
    keep = opts.pop("candidates", False)                 # the bench grades every candidate
    has_eras = len({e.get("label") or e.get("start") for e in opts.get("eras") or [] if e}) >= 2
    inputs = opts.get("inputs") or None if opts.get("inputs_judge") else None
    best, tried, candidates = None, [], []
    extra = known_flows(opts["known"], [s["id"] for s in stocks], run["t"]) if opts.get("known") else []
    for v in opts.pop("variants", None) or VARIANTS:
        if v.get("split_eras") and not has_eras:
            continue
        runs = [(v["name"], one(stocks, run, {**opts, **v}))]
        if opts.get("products") and opts.get("products_guard", True) and any(f.get("product") for f in runs[0][1]["flows"]):
            # (products) the same candidate without products beside it: a product of levels is a
            # loop that can run away (realistic models: the judge's runs explode), so the judge decides
            runs.append((v["name"] + ", no products", one(stocks, run, {**opts, **v, "products": False})))
        for name, r in runs:
            e = judge(r["flows"] + extra if r["flows"] else [], stocks, run, injections=opts.get("injections"), inputs=inputs)
            tried.append({"name": name, "error": e})
            if keep:
                candidates.append({"name": name, "error": e, "flows": r["flows"]})
            if best is None or e < best[1]:
                best = (r, e, name)
    r = best[0]
    r["chosen"], r["tried"] = best[2], tried
    if keep:
        r["candidates"] = candidates
    return r


def identify(stocks: list[dict], run: dict, opts: dict | None = None) -> dict:
    """The answer above with its numbers refitted by instrumental variables where the levels carry
    measurement error (eiv.py), then kept inside the announced boundary (boundary.py: the guard and
    moves where one is declared, each outside flow priced as a boundary claim where none is)."""
    from .eiv import apply

    r = apply(_identify(stocks, run, dict(opts or {})), stocks, run, opts)
    return boundary.apply(r, stocks, run, opts)


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
    from . import oefit

    o, cap = _capmin.offer(stocks, run, opts)
    r = _guarded(oefit.refit, _identify_linear(stocks, run, o, *args, **kw), stocks, run, o, cap)
    # (2026-10-22, port-matrix_v2, docs/research/fixes/port-matrix_v2.md) kalman_lna's post-passes, copied at 9d3ca8e
    # (fix ledger types 2, 3, 6, 7, 11, 12, 15): each stock's row read off the data (sparse linear, or linear plus one
    # floored term on a declared side; derived columns, a hidden integrator, a capped move) and the flows of the stocks
    # whose rows the answer misses rebuilt from the rows where that wins by BIC (rows.py), then a counted stock driven
    # towards a target read off another stock written as a controller where it beats its outside flows (tracker.py)
    from . import dead, rows, tracker

    # (matrix_v2) the controller is read before the rows as well as after them: the matrix's answer draws a
    # controller's stock with proxies the rows would otherwise rebuild as a hidden stage (308 none-short: a delayed
    # inflow beside the controller, two flows on ready's one declared inflow)
    r = _guarded(tracker.revise, _capmin.restore(r, cap), stocks, run, opts)
    r = _guarded(rows.revise, r, stocks, run, opts, cap)
    r = _guarded(tracker.revise, r, stocks, run, opts)
    # (port-matrix_v2) a move that is 0 on every nonnegative state is no flow (dead.py; ledger type 17's exact case)
    return dead.apply(r, stocks, run, opts)


def _guarded(stage, r: dict, *args) -> dict:
    """(port-matrix_v2; fix ledger type 10, refit-guard structures 3bf52d6 and its widening engine_forms 104ee76) a
    later pass that fails on the numbers (an SVD that does not converge, a float error) keeps its input."""
    try:
        return stage(r, *args)
    except (np.linalg.LinAlgError, FloatingPointError, ValueError, ZeroDivisionError, OverflowError):
        return r
