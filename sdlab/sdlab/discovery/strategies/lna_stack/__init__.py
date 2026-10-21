"""lna_stack: lna with the stages built when past ideas were revisited on the ladder
(docs/research/revisit.md) that are recommended, in one model: pulses found first and taken out
(lna_pulses), moves scaled by a third stock (lna_products), inflow pieces as recurring levels
(lna_levels), and, on noise-free runs, ties written the way SD models write them (gap_prior: goal
gaps and co-flows, kept when they behave as the original) and pulses re-measured on the matrix's
model. Each stage is its own package's hooks on lna (lna/run.py HOOKS), unchanged, so this strategy shows
whether they compose; lna's data, stride, measured inputs and budget are lna's own (one budget for
all of its searches). lna_loops is left out: its passes are on cells the data cannot decide, and it can make a
noisy chain behave much worse (revisit.md).
"""

from __future__ import annotations

import math

import numpy as np

from ...identify import identify as _matrix
from ._vendored.lna import boundary
from ._vendored.gap_prior import conventions
from ._vendored.impulses import _flows as pulse_flows
from ._vendored.impulses import find_pulses
from ._vendored.lna import GUARD, judge
from ._vendored.lna_pulses import _not_injected, remeasure
from ._vendored.lna_pulses.run import Budget
from .run import hooks


def inside_pulses(found: dict[str, np.ndarray], run: dict) -> dict[str, np.ndarray]:
    """(the declared boundary) Pulses are outside flows: a burst into a stock only where the case
    declares an estimated outside inflow there, one out of it only where it declares an estimated
    outflow; with no boundary declared, every pulse (each a boundary claim, priced at the end)."""
    b = boundary.Boundary(run)
    if not b.declared:
        return found
    out = {}
    for stock, a in found.items():
        if not b.may(stock, "in", "estimate"):
            a = np.where(a > 0, 0.0, a)
        if not b.may(stock, "out", "estimate"):
            a = np.where(a < 0, 0.0, a)
        if a.any():
            out[stock] = a
    return out


def _identify(stocks: list[dict], run: dict, opts: dict | None = None) -> dict:
    opts = dict(opts or {})
    ids = [s["id"] for s in stocks]
    T = len(run["t"]) - 1
    inj = opts.get("injections")
    base = _matrix(stocks, run, dict(opts))
    rest = {k: v for k, v in opts.items() if k != "candidates"}
    budget = Budget(opts)
    found = inside_pulses(_not_injected(find_pulses(stocks, run, opts), run, inj), run)
    r, state, pulses = None, {}, {}
    for _ in range(3):                 # lna with the pulses taken out; the pulses measured again on its model
        known = None
        if found:
            known = np.zeros((len(ids), T))
            for i, a in found.items():
                known[ids.index(i)] = a
        st: dict = {}
        got = budget.discover(stocks, run, rest, base, hooks(st, known))
        if got is None:                # no counting noise (the first search), or out of time on a later one: the last kept
            break
        r, state = got, st
        if not found:
            break
        r["flows"], pulses = remeasure(r["flows"], ids, run, found, inj)
        same = pulses.keys() == found.keys() and all(np.array_equal(pulses[i] != 0, found[i] != 0) for i in pulses)
        found = pulses
        if same:
            break
    if r is not None and found and not pulses:
        st = {}
        got = budget.discover(stocks, run, rest, base, hooks(st, None))     # the pulses did not hold up: without them
        if got is not None:
            r, state = got, st
    if r is not None:
        extra = [g for i, a in pulses.items() for g in pulse_flows(i, a, run["t"])]
        flows = r["flows"] + extra
        theirs = judge(boundary.apply(base, stocks, run, opts, final=False)["flows"], stocks, run, opts)   # judged inside the declared boundary; returned as it is (eiv, then the final guard)
        # lna's guard on lna's own reading (pulses out) first, then on the result: where lna would
        # keep the matrix's model, so does this
        for fl in (state["lna_flows"] + extra, flows):
            mine = judge(fl, stocks, run, opts)
            if not math.isfinite(mine) or (math.isfinite(theirs) and mine > GUARD * theirs):
                return {**base, "lna": {"judged": {"lna": mine, "matrix": theirs}}}
        r["flows"] = flows
        r["pulses"] = {i: int((a != 0).sum()) for i, a in pulses.items()}
        r["levels"] = {ids[s]: len(g) for s, g in (state.get("levels") or {}).items()}
        r["products"] = state.get("products") or []
        return r
    # no counting noise: the matrix's reading, pulses re-measured on it, ties written as SD writes them
    out = dict(base)
    if found:
        flows, pulses = remeasure(base["flows"], ids, run, found, inj)
        if pulses:
            out["flows"] = flows + [g for i, a in pulses.items() for g in pulse_flows(i, a, run["t"])]
            out["pulses"] = {i: int((a != 0).sum()) for i, a in pulses.items()}
    return conventions(out, stocks, run, opts)


def identify(stocks: list[dict], run: dict, opts: dict | None = None) -> dict:
    """The answer above with its numbers refitted by instrumental variables where the levels carry
    measurement error (eiv.py), then kept inside the announced boundary (the lna copy's boundary.py,
    docs/research/declared-boundary.md: the guard and paired moves where one is declared, each outside
    flow priced as a boundary claim where none is)."""
    from .eiv import apply

    r = apply(_identify(stocks, run, dict(opts or {})), stocks, run, opts)
    return boundary.apply(r, stocks, run, opts, searched=r.get("method") == "lna")   # lna's own reading: its search tried the moves and priced the claims


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
    r = oefit.refit(_identify_linear(stocks, run, o, *args, **kw), stocks, run, o, cap)
    return _capmin.restore(r, cap)
