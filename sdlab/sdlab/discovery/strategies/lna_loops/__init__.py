"""lna_loops: lna, with feedback the data cannot rule out kept rather than priced away.

lna drops a flow when keeping it does not pay the BIC price (log T / 2 per number). A link that
closes a loop (B's level drives A's inflow while A feeds B) is often a small number with a standard
error larger than itself on a few hundred noisy steps: BIC drops it, and the model is the loop's
equivalent without it. Here, after lna's search, every loop-closing link (outside -> a reading b,
where a moves into b) that is not in the model is offered back, fitted by the same likelihood, and
kept when its likelihood gain is above `price` (default 0: kept whenever its maximum-likelihood
number is above zero). This is the "Bayesian structure / complexity budget" idea: a prior that
favours closing a loop over BIC's Occam price, for one kind of term only.

The cost is complexity (an extra flow where the truth has none, at a number within its standard
error of zero); docs/research/revisit.md measures both.
"""

from __future__ import annotations

import math

import numpy as np

from ...identify import identify as _matrix
from ...identify import judge
from ..lna import GUARD
from ..lna.atoms import Atom
from ..lna.fit import fit
from .run import discover

PRICE = 0.0


def close_loops(price: float = PRICE):
    def finish(cur, d, unit, final, group):
        live = [(a, th) for a, th in zip(cur.atoms, cur.theta) if th > 0]
        moves = {(a.src, a.dst) for a, _ in live if a.kind == "move" and a.era is None}
        have = {(a.dst, a.driver) for a, _ in live if a.kind in ("link", "grow")} | {(a.dst, a.src) for a, _ in live if a.kind == "move"}
        added = []
        for src, dst in sorted(moves):
            if (src, dst) in have:          # a already reads b (a link, or a move back from b)
                continue
            cand = Atom("link", dst=src, driver=dst)
            g = fit(cur.atoms + [cand], d, np.append(cur.theta, 1e-3), tau=cur.tau)
            if g.theta[-1] > 0 and cur.nll - g.nll > price:
                cur = g
                added.append(f"outside -> {src} reading {dst}")
        return cur, {"loops_closed": added}
    return finish


def identify(stocks: list[dict], run: dict, opts: dict | None = None) -> dict:
    opts = dict(opts or {})
    price = float(opts.pop("loop_price", PRICE))
    base = _matrix(stocks, run, dict(opts))
    found = discover(stocks, run, {k: v for k, v in opts.items() if k != "candidates"}, base, finish=close_loops(price))
    if found is None:
        return base
    mine = judge(found["flows"], stocks, run, injections=opts.get("injections"))
    theirs = judge(base["flows"], stocks, run, injections=opts.get("injections"))
    found["judged"] = {"lna": mine, "matrix": theirs}
    if not math.isfinite(mine) or (math.isfinite(theirs) and mine > GUARD * theirs):
        return {**base, "lna": {k: found[k] for k in ("judged", "nll", "dispersion")}}
    return found
