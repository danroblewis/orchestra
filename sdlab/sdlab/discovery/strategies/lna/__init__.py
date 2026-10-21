"""lna: flows chosen by the likelihood of the per-step changes under counting noise (the linear noise
approximation), all rows fitted together with each flow a shared column.

The averages of the changes give only the linear system (one matrix); the covariance of the changes
tells a move (its draw leaves the source as it arrives) from a link (it does not), a co-flow (it
mirrors at the ratio `per`) from an independent drain, births from deaths (the mean is their
difference, the variance their sum), and a goal gap from an inflow beside a drain. Noise-free data
has no covariance to read: there the matrix method's reading is returned unchanged. A model the
likelihood found is kept unless the matrix's model behaves clearly better in the judge (a guard
against a model that runs away).

The declared boundary (boundary.py, a copy of matrix's; docs/research/declared-boundary.md): where a
case declares one, the search offers outside flows (inflows, outflows, links, drains, growth, gaps)
only on the sides and of the kinds declared, and holds any other at 0; the matrix's model is guarded
before it is judged; and the answer goes through the guard and the paired-move pass. Where none is
declared, each outside flow of the answer is a boundary claim, priced and listed (boundary.apply).
"""

from __future__ import annotations

import math

from ...identify import identify as _matrix
from ...simulate import behaviour_error
from . import boundary
from .run import discover

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


def _identify(stocks: list[dict], run: dict, opts: dict | None = None, hooks: dict | None = None) -> dict:
    """hooks: stages a variant adds (run.HOOKS); none for lna itself."""
    opts = dict(opts or {})
    base = boundary.apply(_matrix(stocks, run, dict(opts)), stocks, run, opts, final=False)
    found = discover(stocks, run, {k: v for k, v in opts.items() if k != "candidates"}, base, hooks)
    if found is None:
        return base
    mine = judge(found["flows"], stocks, run, opts)
    theirs = judge(base["flows"], stocks, run, opts)
    found["judged"] = {"lna": mine, "matrix": theirs}
    if (MISFIT is not None and found["misfit"] > MISFIT) or not math.isfinite(mine) or (math.isfinite(theirs) and mine > GUARD * theirs):
        return {**base, "lna": {k: found[k] for k in ("judged", "nll", "dispersion", "misfit")}}
    return found


def identify(stocks: list[dict], run: dict, opts: dict | None = None, hooks: dict | None = None) -> dict:
    """The answer above with its numbers refitted by instrumental variables where the levels carry
    measurement error (eiv.py), then kept inside the announced boundary (boundary.py)."""
    from .eiv import apply

    r = apply(_identify(stocks, run, dict(opts or {}), hooks), stocks, run, opts)
    return boundary.apply(r, stocks, run, opts, searched=r.get("method") == "lna")   # lna's own reading: its search tried the moves and priced the claims
