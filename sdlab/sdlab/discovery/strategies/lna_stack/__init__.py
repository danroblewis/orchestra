"""lna_stack: lna with the stages built when past ideas were revisited on the ladder
(docs/research/revisit.md) that are recommended, in one model: pulses found first and taken out
(lna_pulses), moves scaled by a third stock (lna_products), inflow pieces as recurring levels
(lna_levels), and, on noise-free runs, ties written the way SD models write them (gap_prior: goal
gaps and co-flows, kept when they behave as the original) and pulses re-measured on the matrix's
model. Each stage is imported from its own package, unchanged, so this strategy shows whether they
compose. lna_loops is left out: its passes are on cells the data cannot decide, and it can make a
noisy chain behave much worse (revisit.md).
"""

from __future__ import annotations

import math

import numpy as np

from ...identify import identify as _matrix
from ...identify import judge
from ..gap_prior import conventions
from ..impulses import _flows as pulse_flows
from ..impulses import find_pulses
from ..lna import GUARD
from ..lna_pulses import _not_injected, remeasure
from .run import discover


def identify(stocks: list[dict], run: dict, opts: dict | None = None) -> dict:
    opts = dict(opts or {})
    ids = [s["id"] for s in stocks]
    T = len(run["t"]) - 1
    inj = opts.get("injections")
    base = _matrix(stocks, run, dict(opts))
    rest = {k: v for k, v in opts.items() if k != "candidates"}
    found = _not_injected(find_pulses(stocks, run, opts), run, inj)
    r, pulses = None, {}
    for _ in range(3):                 # lna with the pulses taken out; the pulses measured again on its model
        known = None
        if found:
            known = np.zeros((len(ids), T))
            for i, a in found.items():
                known[ids.index(i)] = a
        r = discover(stocks, run, rest, base, known=known)
        if r is None or not found:
            break
        r["flows"], pulses = remeasure(r["flows"], ids, run, found, inj)
        same = pulses.keys() == found.keys() and all(np.array_equal(pulses[i] != 0, found[i] != 0) for i in pulses)
        found = pulses
        if same:
            break
    if r is not None and found and not pulses:
        r = discover(stocks, run, rest, base)          # the pulses did not hold up: without them
    if r is not None:
        flows = r["flows"] + [g for i, a in pulses.items() for g in pulse_flows(i, a, run["t"])]
        mine = judge(flows, stocks, run, injections=inj)
        theirs = judge(base["flows"], stocks, run, injections=inj)
        if not math.isfinite(mine) or (math.isfinite(theirs) and mine > GUARD * theirs):
            return {**base, "lna": {"judged": {"lna": mine, "matrix": theirs}}}
        r["flows"] = flows
        r["pulses"] = {i: int((a != 0).sum()) for i, a in pulses.items()}
        return r
    # no counting noise: the matrix's reading, pulses re-measured on it, ties written as SD writes them
    out = dict(base)
    if found:
        flows, pulses = remeasure(base["flows"], ids, run, found, inj)
        if pulses:
            out["flows"] = flows + [g for i, a in pulses.items() for g in pulse_flows(i, a, run["t"])]
            out["pulses"] = {i: int((a != 0).sum()) for i, a in pulses.items()}
    return conventions(out, stocks, run, opts)
