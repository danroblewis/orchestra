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

from ...identify import identify as _matrix
from ...identify import judge
from .run import discover

GUARD = 4.0          # the matrix's model is kept when the likelihood's is judged this much worse
MISFIT = None        # (tried: 0.3) fall back also when a stock's changes spread this much beyond
                     # counting noise (a share of its counting variance); on the examples it removed
                     # the gains (print-shop, supply) and none of the losses, so it is off


def identify(stocks: list[dict], run: dict, opts: dict | None = None) -> dict:
    opts = dict(opts or {})
    base = _matrix(stocks, run, dict(opts))
    found = discover(stocks, run, {k: v for k, v in opts.items() if k != "candidates"}, base)
    if found is None:
        return base
    mine = judge(found["flows"], stocks, run, injections=opts.get("injections"))
    theirs = judge(base["flows"], stocks, run, injections=opts.get("injections"))
    found["judged"] = {"lna": mine, "matrix": theirs}
    if (MISFIT is not None and found["misfit"] > MISFIT) or not math.isfinite(mine) or (math.isfinite(theirs) and mine > GUARD * theirs):
        return {**base, "lna": {k: found[k] for k in ("judged", "nll", "dispersion", "misfit")}}
    return found
