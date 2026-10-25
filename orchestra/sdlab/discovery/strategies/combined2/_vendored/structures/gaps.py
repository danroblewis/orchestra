# Vendored for combined2 from sdlab/discovery/strategies/structures/gaps.py at commit 7e0a2bf (HEAD ebe9a4f); imports
# rewritten to these copies, otherwise unchanged (CLAUDE.md invariant 11). Re-vendor rather than edit.
"""Goal gaps over several stocks: b's outside inflow (u - X_1 - ... - X_k) / tau, the goal u a
measured input (or a constant), floored at 0 as a whole.

Each stock alone explains none of such an inflow (its stocks add up to the gap only together, and
where the goal falls below them the floor holds the inflow at 0), so neither the stepwise search nor
a stock's own regression finds it one term at a time. Here every gap up to `most` stocks is offered
as a block: the shared-time form (one number) and the free form (one number per stock read, and the
goal's), added to the current model with b's other outside-inflow terms, and the stepwise search is
run again from the best block when it lowers BIC.
"""

from __future__ import annotations

from itertools import combinations

from .fit import Fit, Problem, fit, search
from .terms import Term


def blocks(S: int, m: int, b: int, most: int = 3) -> list[list[Term]]:
    out = []
    for k in range(1, min(most, S) + 1):
        for G in combinations(range(S), k):
            gaps = [Term("gap", dst=b, x=(j,)) for j in G]
            out.append([Term("in", dst=b)] + gaps)
            for u in range(S, S + m):
                out.append([Term("goal", dst=b, x=(u,) + G)])
                out.append([Term("link", dst=b, x=(u,))] + gaps)
    return out


def gap_stage(p: Problem, lib: list[Term], cur: Fit, S: int, m: int, most: int = 3) -> Fit:
    best = None
    for b in range(S):
        keep = [t for t in cur.terms if not (t.pooled and t.dst == b)]
        for blk in blocks(S, m, b, most):
            g = fit(p, keep + blk)
            if best is None or g.bic < best.bic:
                best = g
    if best is None or best.bic >= cur.bic - 1e-9:
        return cur
    g = search(p, lib + [t for t in best.terms if t.kind == "goal"], best.terms)
    return g if g.bic < cur.bic else cur
