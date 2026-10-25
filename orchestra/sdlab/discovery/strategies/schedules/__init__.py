"""Schedules: censored's model, then its structure searched again with every number refitted jointly
across rows and announced eras.

The main line fits each stock's row alone, and with announced eras each era's numbers alone. Where
an era is short or quiet its rows are nearly collinear, and the main line splits a move into a
drain plus a link, or adds a loop, that only that era uses (157: A -> B read as A -> B 0.15 plus a
drain of A 0.15 in the first era, 0 after). A constant on a move is likewise pushed to the ends of
the move, as a larger inflow into its source and a constant drain of its destination (158). Both
are the same model one flow longer.

Here the model censored chooses (a copy of censored at 2dee420, `_vendored/censored`), a lean copy
(every pieced inflow one piece) and its flows linear in their numbers start a beam search (search.py):
drop a flow; one number for all eras or numbers per era; a constant on a move in place of the
constant flows at its ends (158); a move from a drain and a link; a drain on another level as a
falling inflow; a new move; a co-flow on a move; outside flows as one-step pulses on a fixed period,
which may top their stock up to a level (159); inflow pieces merged and cut. Each candidate's numbers
are refitted together (refit.py: one least squares over all rows, a move's number shared by its
two rows, numbers per era group, the inflow pieces profiled out, steps where a stock's outflows are
cut short left out), and the one-step BIC in the engine's form (with a price per flow) decides. The
result is kept only if it behaves on the data no worse than `judge_slack` times censored's model by
the main line's judge.
"""

from __future__ import annotations

import math

import numpy as np

from ...matrix import configurations, injected
from . import boundary
from ._vendored.censored import identify as censored
from ._vendored.censored import judge
from ._vendored.censored import onestep
from .refit import Context
from .search import restore, search

DEFAULTS = {"margin": 2.0, "flow_price": 0.5, "budget": 60.0, "judge_slack": 1.5}


def _sides(flows: list[dict], ids: list[str]) -> set:
    """The (stock, side) pairs the flows' outside ends reach, as the scorer reads them (boundary.ends)."""
    return {x for e in boundary.ends(flows, ids) for x in e}


def _identify(stocks: list[dict], run: dict, opts: dict | None = None) -> dict:
    opts = dict(opts or {})
    o = {k: opts.pop(k, v) for k, v in DEFAULTS.items()}
    r0 = censored(stocks, run, opts)
    ids = [s["id"] for s in stocks]
    t = run["t"]
    flows0 = list(r0.get("flows") or [])
    lv = onestep.levels(stocks, run)
    if lv.shape[1] < 30 or not ids or not flows0:
        return r0
    prev, dy = lv[:, :-1], np.diff(lv, axis=1)
    if opts.get("injections"):
        inj = injected(opts["injections"], ids, t)[:, 1:]
        prev, dy = prev + inj, dy - inj
    T = prev.shape[1]
    mi = onestep.model_inputs(opts.get("inputs"), ids, t)
    in_names, in_rows = onestep.input_rows(opts.get("inputs"), ids, t, T)
    names, X = (ids + in_names, np.vstack([prev, in_rows])) if in_rows.shape[0] and in_rows.shape[1] == T else (ids, prev)
    conf = configurations(opts.get("eras"), t)
    spans = conf[2] if conf else None
    ctx = Context(ids, t, prev, dy, names, X, mi, spans)
    floor = T * ((1e-4 * dy.std(axis=1)) ** 2 + 1e-8)
    res = dy - onestep.changes(flows0, ids, t, prev, mi)
    scale = np.sqrt((res ** 2).mean(axis=1)) + 1e-4 * dy.std(axis=1) + 1e-9
    # the search stays inside the announced boundary (boundary.py): a step that puts an outside flow on
    # an undeclared side, or of an undeclared kind, is not offered (no restriction when none is declared)
    bd = boundary.Boundary(run)
    in_set = set((opts.get("inputs") or {}).keys())
    # and a declared side keeps its outside flow (it exists: it may change form, never vanish; 305's
    # retries -> outside, dropped with its pieces before its proportional form was tried)
    start, restored = flows0, []
    if bd.declared:          # a declared outflow to outside the start lacks is put back first (search.restore)
        start, restored = restore(flows0, ctx, floor, o["flow_price"], scale, {x for x in ids if bd.may(x, "out", "estimate")})
    sides0 = {x for x in _sides(start, ids) if bd.may(*x)}
    inside = (lambda fl: not boundary.violations(fl, ids, bd, in_set) and sides0 <= _sides(fl, ids)) if bd.declared else None
    flows, taken = search(start, ctx, floor, spans, o["margin"], o["flow_price"], o["budget"], scale, inside=inside)
    if restored and not taken:
        flows, taken = start, restored
    else:
        taken = restored + taken
    if not taken:
        return {**r0, "schedules": []}
    inputs = mi and mi["values"]
    e0 = judge(flows0, stocks, run, injections=opts.get("injections"), inputs=inputs)
    e1 = judge(flows, stocks, run, injections=opts.get("injections"), inputs=inputs)
    if math.isfinite(e0) and not (e1 <= o["judge_slack"] * e0 + 1e-12):
        return {**r0, "schedules": taken, "schedules_rejected": {"judge": e1, "censored": e0}}
    for f in flows:
        f.pop("free_c", None)
    return {**r0, "flows": flows, "schedules": taken, "judge": {"schedules": e1, "censored": e0}}


def identify(stocks: list[dict], run: dict, opts: dict | None = None) -> dict:
    """The answer above with its numbers refitted by instrumental variables where the levels carry
    measurement error (eiv.py), then kept inside the announced boundary (boundary.py,
    docs/research/declared-boundary.md: the guard and moves where one is declared, each outside flow
    priced as a boundary claim where none is)."""
    from .eiv import apply

    return boundary.apply(apply(_identify(stocks, run, dict(opts or {})), stocks, run, opts), stocks, run, opts)


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
