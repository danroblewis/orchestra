"""lna_products: lna with product columns, so a move can be scaled by a linear effect of a third
stock (rate k x a x c / mean(c)), chosen by the same counting-noise likelihood and BIC as every
other flow.

PySINDy's verdict (docs/research/pysindy.md) was "reject as a strategy; carry the product terms
forward", and effect_hats / symbolic fit effect curves by least squares, which on the ladder's noisy
runs of the linear effect (017) read the effect as links and drains. Here the product terms sit in
lna's likelihood, where the move's draw leaving a and arriving in b is what tells a move scaled by c
from a drain of a and a link into b. Noise-free runs, and runs with fewer than three stocks, are
lna's (there is nothing for a third stock to scale). lna's guard (the matrix's model is kept when
lna's is judged much worse) is applied to lna's own reading and then to the result.
"""

from __future__ import annotations

import math

from ...identify import identify as _matrix
from ...identify import judge
from ..lna import GUARD
from ..lna import identify as _lna
from .run import discover


def identify(stocks: list[dict], run: dict, opts: dict | None = None) -> dict:
    opts = dict(opts or {})
    base = _matrix(stocks, run, dict(opts))
    found = discover(stocks, run, {k: v for k, v in opts.items() if k != "candidates"}, base)
    if found is None:
        return _lna(stocks, run, opts)
    if not found.get("products"):
        return _lna(stocks, run, opts)          # no product kept: lna's own reading
    theirs = judge(base["flows"], stocks, run, injections=opts.get("injections"))
    for flows in (found.pop("lna_flows"), found["flows"]):     # lna's guard on lna's reading, then on this
        mine = judge(flows, stocks, run, injections=opts.get("injections"))
        if not math.isfinite(mine) or (math.isfinite(theirs) and mine > GUARD * theirs):
            return {**base, "lna": {"judged": {"lna": mine, "matrix": theirs}}}
    found["judged"] = {"lna": mine, "matrix": theirs}
    return found
