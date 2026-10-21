"""lna: flows chosen by the likelihood of the per-step changes under counting noise (the linear noise
approximation), all rows fitted together with each flow a shared column.

The averages of the changes give only the linear system (one matrix); the covariance of the changes
tells a move (its draw leaves the source as it arrives) from a link (it does not), a co-flow (it
mirrors at the ratio `per`) from an independent drain, births from deaths (the mean is their
difference, the variance their sum), and a goal gap from an inflow beside a drain. Noise-free data
has no covariance to read: there the matrix method's reading is returned unchanged. A model the
likelihood found is kept unless the matrix's model behaves clearly better in the judge (a guard
against a model that runs away).
"""

from __future__ import annotations

import math

from sdlab.discovery.identify import identify as _matrix
from sdlab.discovery.simulate import behaviour_error
from sdlab.discovery.strategies.gap_prior import boundary
from sdlab.discovery.strategies.gap_prior._vendored.lna.run import discover

GUARD = 4.0          # the matrix's model is kept when the likelihood's is judged this much worse
MISFIT = None        # (tried: 0.3) fall back also when a stock's changes spread this much beyond
                     # counting noise (a share of its counting variance); on the examples it removed
                     # the gains (print-shop, supply) and none of the losses, so it is off


def judge(flows: list[dict], stocks: list[dict], run: dict, opts: dict, horizons=(5, 20, 100)) -> float:
    """The main line's judge (identify.judge), with the measured inputs the flows may read."""
    hs = [h for h in horizons if h < len(run["t"]) / 4]
    if not flows or not hs:
        return float("inf")
    ids = [s["id"] for s in stocks]
    kw = {"inputs": opts["inputs"]} if opts.get("inputs") else {}
    return sum(behaviour_error(flows, ids, run["t"], run["levels"], horizon=h, injections=opts.get("injections"), **kw) for h in hs) / len(hs)


def _inside_main_line(main, stocks: list[dict], run: dict, opts: dict, judge_of) -> dict:
    """(the declared boundary, boundary.py) The main line chosen among its candidates kept inside the
    announced boundary: every candidate guarded (an undeclared outside flow becomes its best-priced
    alternative), then judged again with judge_of(flows), the lowest error kept. Without this the main
    line could choose a candidate that only an undeclared outside flow made fit, and the guard would
    leave little of it (055#6 counts-short: only outside -> B, dropped, nothing left to search from)."""
    r = main(stocks, run, {**opts, "candidates": True})
    best = None
    for c in r.pop("candidates", None) or []:
        if not c.get("flows"):
            continue
        flows = boundary.apply({"flows": c["flows"]}, stocks, run, opts, final=False)["flows"]
        e = judge_of(flows) if flows else float("inf")
        if best is None or e < best[0]:
            best = (e, flows, c["name"])
    if best is None:
        return boundary.apply(r, stocks, run, opts, final=False) if r.get("flows") else r
    return {**r, "flows": best[1], "chosen": best[2], "boundary_main_line": "candidates guarded, then judged"}


def identify(stocks: list[dict], run: dict, opts: dict | None = None, hooks: dict | None = None) -> dict:
    """hooks: stages a variant adds (run.HOOKS); none for lna itself."""
    opts = dict(opts or {})
    if boundary.Boundary(run).declared:      # (gap_prior's copy) the main line inside the announced boundary
        base = _inside_main_line(_matrix, stocks, run, dict(opts), lambda fl: judge(fl, stocks, run, opts))
    else:
        base = _matrix(stocks, run, dict(opts))
    found = discover(stocks, run, {k: v for k, v in opts.items() if k != "candidates"}, base, hooks)
    if found is None:
        return base
    mine = judge(found["flows"], stocks, run, opts)
    theirs = judge(base["flows"], stocks, run, opts)
    found["judged"] = {"lna": mine, "matrix": theirs}
    if (MISFIT is not None and found["misfit"] > MISFIT) or not math.isfinite(mine) or (math.isfinite(theirs) and mine > GUARD * theirs):
        return {**base, "lna": {k: found[k] for k in ("judged", "nll", "dispersion", "misfit")}}
    return found
