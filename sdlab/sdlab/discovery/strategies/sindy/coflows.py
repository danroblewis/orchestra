"""Co-flows on rows the answer does not reproduce are dropped before the exact re-read (port-sindy, 2026-10-22,
docs/research/fixes/port-sindy.md).

sindy reads a product term in a third stock's row as a co-flow (`uses`: the flow takes `per` of that stock for
each unit it moves; term_flows.py). On exact data the rows a co-flow is written into are often the rows sindy's
linear library cannot reproduce at all (a quantized controller, a floored gap, a hidden leak: k8s 309-311, where
`retries -> queue` took 0.19 ready per unit and `queue -> inflight` 4.08 mem per unit). Such a co-flow is not
evidence of anything: it is the row's misfit spread over a product. The later passes copied from engine_forms
(reread.py, hidden.py, controller.py) read a row again only from the flows whose ends are on it, so a co-flow
left on that row stays in its change and keeps every re-read from reproducing it.

Here, only where the data are exact (some moving row is reproduced to its rounding by a linear set: on data
with noise nothing changes), each co-flow on a stock whose row the answer does not reproduce is removed. The
flow it rides on is kept. A row the answer reproduces keeps its co-flows (016-coflow and the other co-flow
cases). Reads only the levels, inputs and the answer's flows.
"""

from __future__ import annotations

import copy

import numpy as np

from . import boundary as _boundary
from .hidden import _change
from .reread import _quantum, _Rows


def apply(result: dict, stocks: list[dict], run: dict, opts: dict | None) -> dict:
    if not isinstance(result, dict) or not result.get("flows"):
        return result
    if not any(f.get("uses") for f in result["flows"]):
        return result
    opts = opts or {}
    data = _boundary.Data(stocks, run, opts)
    if not data.usable:
        return result
    ids = data.ids
    t = [float(x) for x in run["t"]]
    at = {x: i for i, x in enumerate(t)}
    ins = []
    for name, v in (opts.get("inputs") or {}).items():
        if name in ids or str(name).startswith("capmin__"):
            continue
        v = np.asarray(v, dtype=float)
        if len(v) != len(t):
            continue
        ins.append((name, np.array([v[at[float(x)]] for x in data.tt])))
    try:
        resid = data.dy - _change(result["flows"], data, dict(ins))
    except Exception:                                     # noqa: BLE001  (a flow the simulator cannot evaluate)
        return result
    names = ids + [n for n, _ in ins] + ["1"]
    Z = np.vstack([data.L] + [u[None, :] for _, u in ins] + [np.ones((1, data.T))])
    levels = np.array([np.asarray(run["levels"][i], dtype=float) for i in ids])
    rows = _Rows(data, Z, names, _quantum(levels))
    exact_any, bad = False, set()
    for i, s in enumerate(ids):
        e = rows.exact(data.dy[i])
        if e is not None and np.any(np.abs(data.dy[i]) > rows.tol(data.dy[i])):
            exact_any = True
        if float(np.sqrt(np.mean(resid[i] ** 2))) > 2 * rows.tol(data.dy[i], None if e is None else e[1]):
            bad.add(s)
    if not exact_any or not bad:
        return result
    flows, dropped = copy.deepcopy(result["flows"]), []
    for f in flows:
        uses = f.get("uses") or []
        keep = [u for u in uses if u.get("stock") not in bad]
        if len(keep) < len(uses):
            dropped += [f"{f.get('from') or 'outside'} -> {f.get('to') or 'outside'} uses {u.get('stock')}" for u in uses if u not in keep]
            if keep:
                f["uses"] = keep
            else:
                f.pop("uses", None)
    if not dropped:
        return result
    return {**result, "flows": flows, "coflows_dropped": dropped}
