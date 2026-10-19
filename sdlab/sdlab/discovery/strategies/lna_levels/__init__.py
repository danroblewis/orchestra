"""lna_levels: lna, with each outside inflow's pieces offered as a few recurring levels, and a
stock's growth with itself beside an inflow offered back as inflow pieces (levels.py).

From the regime-models and inflow-innovations ideas (docs/research/regime-models.md,
inflow-innovations.md; never built on the old bench): an unannounced square wave is a two-state
recurring regime, two numbers rather than one per piece, so the pieces both cost less (BIC) and are
each measured from every step at their level. Measured on the ladder in docs/research/revisit.md.
Noise-free runs are lna's (the matrix's reading). lna's guard is applied to lna's own reading and
then to the result: where lna would return the matrix's model, so does this.
"""

from __future__ import annotations

import math

from ...identify import identify as _matrix
from ...identify import judge
from ..lna import GUARD
from .run import discover


def identify(stocks: list[dict], run: dict, opts: dict | None = None) -> dict:
    opts = dict(opts or {})
    base = _matrix(stocks, run, dict(opts))
    found = discover(stocks, run, {k: v for k, v in opts.items() if k != "candidates"}, base)
    if found is None:
        return base
    theirs = judge(base["flows"], stocks, run, injections=opts.get("injections"))
    # lna's guard on lna's own reading first: where lna would keep the matrix's model, so does this
    # (levels refine a reading lna trusts; they do not rescue one it rejects)
    for flows in (found.pop("lna_flows"), found["flows"]):
        mine = judge(flows, stocks, run, injections=opts.get("injections"))
        if not math.isfinite(mine) or (math.isfinite(theirs) and mine > GUARD * theirs):
            return {**base, "lna": {"judged": {"lna": mine, "matrix": theirs}, "nll": found["nll"], "dispersion": found["dispersion"]}}
    found["judged"] = {"lna": mine, "matrix": theirs}
    return found
