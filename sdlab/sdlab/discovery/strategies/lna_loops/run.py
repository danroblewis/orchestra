"""The loop stage as a hook on lna's discover (lna/run.py HOOKS): after lna's search, every
loop-closing link (outside -> a reading b, where a moves into b) not in the model is offered back,
fitted by the same likelihood, and kept when its likelihood gain is above `price`. No search code
is copied: lna's data, budget, stride and measured inputs are lna's own."""

from __future__ import annotations

import numpy as np

from ..lna.atoms import Atom
from ..lna.fit import OutOfTime, fit

PRICE = 0.0


def close_loops(cur, d, price: float = PRICE):
    """(the model with the loop-closing links that pay `price`, their descriptions)."""
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
            added.append((src, dst))
    return cur, added


def stage(state: dict, price: float = PRICE) -> dict:
    """{after_search} for the loop stage; `state["loops_closed"]` lists the links kept."""

    def after_search(cur, d, ctx):
        try:
            g, added = close_loops(cur, d, price)
        except OutOfTime:                # past lna's budget: lna's reading stands
            state["loops_out_of_time"] = True
            return cur
        ids = ctx["ids"]
        state["loops_closed"] = [f"outside -> {ids[s]} reading {ids[t]}" for s, t in added]
        return g

    return {"after_search": after_search}
