"""Schedules: censored's model, then its structure searched again with every number refitted jointly
across rows and announced eras.

The main line fits each stock's row alone, and with announced eras each era's numbers alone. Where
an era is short or quiet its rows are nearly collinear, and the main line splits a move into a
drain plus a link, or adds a loop, that only that era uses (157: A -> B read as A -> B 0.15 plus a
drain of A 0.15 in the first era, 0 after). A constant on a move is likewise pushed to the ends of
the move, as a larger inflow into its source and a constant drain of its destination (158). Both
are the same model one flow longer.

Here the model censored chooses (a copy of censored at aad5c7b, `_vendored/censored`) is the start
of a greedy search (search.py): drop a flow, one number for all eras, numbers per era, a constant
on a move (replacing a constant flow at either end), and merging an inflow's adjacent pieces. Each
candidate's numbers are refitted together (refit.py: one least squares over all rows, a move's
number shared by its two rows, numbers per era group, the inflow pieces profiled out), and the one-
step BIC in the engine's form (with a price per flow) decides. The result is kept only if it
behaves on the data no worse than `judge_slack` times censored's model by the main line's judge.
"""

from __future__ import annotations

import math

import numpy as np

from ...matrix import configurations, injected
from ._vendored.censored import identify as censored
from ._vendored.censored import judge
from ._vendored.censored import onestep
from .refit import Context
from .search import search

DEFAULTS = {"margin": 2.0, "flow_price": 0.5, "budget": 60.0, "judge_slack": 1.5}


def identify(stocks: list[dict], run: dict, opts: dict | None = None) -> dict:
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
    flows, taken = search(flows0, ctx, floor, spans, o["margin"], o["flow_price"], o["budget"], scale)
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
