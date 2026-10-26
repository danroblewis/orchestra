"""The form of a whole flow whose truth switches regime (score.py; kubernetes 306, 2026-10-21).

A whole flow (sim.py: an expression rate, a two-way flow, a rate reading an auxiliary or a switch) is
compared by its amount on the run's states, as relative rms error within rel. For a truth whose rate
switches regime (min, max, if_then_else, or a comparison), that check alone lets one linear rate stand
in for both regimes: on 306, dispatch = min(0.6 x queue, 40 x ready) is matched within 7% by
0.0176 x queue + 0.497 x inflight (inflight holds what was dispatched), on the demand steps and on
the capped steps alike. So the form is checked as well (the user's case says "recovered as a MIN of
the queue and ready, not one rate of one stock"):

- regimes(): every step's regime, the branch the truth's rate takes at each min / max / if_then_else /
  comparison, on the run's states;
- slopes(): the flows' amount's slope in every measured stock and input, at every step (central
  differences of the same amounts the scorer compares);
- form(): in every regime that holds on at least max(MIN_STEPS, MIN_SHARE x steps) steps, the median
  slope of the found flows in each stock or input is a part of the flow, compared with the truth's
  median slope there as the scorer compares a linear number (_close: rel, or the floor over the mean
  level it reads); a slope the truth does not have in that regime is an extra part, wrong when its
  size (|slope| x mean level) is above the spurious threshold. The median keeps a found switch a few
  steps from the truth's from counting.

A truth with no regime is not checked here (its amount check is unchanged).
"""

from __future__ import annotations

import math

import numpy as np

from ..sdtruth import _Program
from ..sdtruth_expr import COMPARE, compile_expr, parse

MIN_STEPS = 10
MIN_SHARE = 0.05


def _switches(node) -> list:
    """The regime nodes of an expression tree: min / max / if_then_else calls and comparisons."""
    out = []
    kind = node[0]
    if kind == "call" and node[1] in ("min", "max", "if_then_else"):
        out.append(node)
    if kind == "bin" and node[1] in COMPARE:
        out.append(node)
    kids = [node[1]] if kind == "neg" else [node[2], node[3]] if kind == "bin" else list(node[2]) if kind == "call" and node[1] not in ("flow", "lookup") else \
        [node[2][0]] if kind == "call" and node[1] == "lookup" else []
    for k in kids:
        out += _switches(k)
    return out


def _branch(node):
    """fn(view, fl) -> the branch the node takes (the argument min / max picks, or the condition's truth)."""
    if node[0] == "bin":
        a, b, cmp = compile_expr(node[2]), compile_expr(node[3]), COMPARE[node[1]]
        return lambda view, fl: int(bool(cmp(a(view, fl), b(view, fl))))
    args = [compile_expr(a) for a in node[2]]
    if node[1] == "if_then_else":
        return lambda view, fl: int(bool(args[0](view, fl)))
    pick = min if node[1] == "min" else max
    return lambda view, fl: pick(range(len(args)), key=lambda i: args[i](view, fl))


def regimes(flows: list[dict], data: dict, states: list[dict]) -> np.ndarray | None:
    """Every step's regime (an int per distinct combination of branches) of these truth flows; None
    when none of their rates switches regime."""
    t = data["t"]
    counters = data.get("counters") or {}
    names = set(states[0]) if states else set()
    plans = []
    for f in flows:
        aux = (f.get("whole") or {}).get("auxiliaries") or {}
        segs = f.get("byTime") or [{"from": -math.inf, "to": math.inf, "rate": f.get("rate")}]
        per = []
        for g in segs:
            r = g.get("rate") or {}
            per.append([_branch(n) for n in _switches(parse(r["expr"]))] if r.get("form") == "expr" else [])
        if any(per):
            prog = _Program({"stocks": [{"id": n} for n in sorted(names)], "auxiliaries": aux, "flows": []})
            plans.append((segs, per, prog))
    if not plans:
        return None
    sigs = []
    for i, state in enumerate(states):
        step = t[i + 1]
        fl = {fid: float(v[i + 1]) for fid, v in counters.items() if i + 1 < len(v)}
        sig = []
        for segs, per, prog in plans:
            k = next((n for n, g in enumerate(segs) if g["from"] <= step <= g["to"]), len(segs) - 1)
            view = dict(state)
            prog.auxiliaries(view)
            sig.append((k, tuple(b(view, fl) for b in per[k])))
        sigs.append(tuple(sig))
    ids = {s: n for n, s in enumerate(dict.fromkeys(sigs))}
    return np.array([ids[s] for s in sigs])


def slopes(amounts, states: list[dict], names: list[str], means: dict) -> dict[str, np.ndarray] | None:
    """d amount / d x at every step for every x in names; amounts(states) -> np.ndarray | None."""
    out = {}
    for x in names:
        h = 1e-3 * max(1.0, abs(means.get(x, 0.0)))
        up = amounts([{**s, x: s.get(x, 0.0) + h} for s in states])
        dn = amounts([{**s, x: s.get(x, 0.0) - h} for s in states])
        if up is None or dn is None:
            return None
        out[x] = (up - dn) / (2 * h)
    return out


def form(true_amounts, found_amounts, regime: np.ndarray, states: list[dict], names: list[str], close, tol: dict,
         means: dict, scale: float) -> dict:
    """{ok, error, regimes: [{steps, parts: {x: [true, found, ok]}}]}; close(true, found, x) -> (ok, err)."""
    st = slopes(true_amounts, states, names, means)
    sf = slopes(found_amounts, states, names, means)
    if st is None or sf is None:
        return {"ok": False, "error": math.inf, "regimes": []}
    need = max(MIN_STEPS, MIN_SHARE * len(regime))
    ok, worst, rows = True, 0.0, []
    for r in sorted(set(regime.tolist())):
        m = regime == r
        if m.sum() < need:
            continue
        row = {"steps": int(m.sum()), "parts": {}}
        for x in names:
            gt, gf = float(np.median(st[x][m])), float(np.median(sf[x][m]))
            if abs(gt) * max(means.get(x, 0.0), 1e-9) > 1e-9 * scale:
                o, e = close(gt, gf, x)
            elif gf == 0.0:
                continue
            else:
                size = abs(gf) * means.get(x, 0.0)
                o, e = size <= tol["spurious"] * scale, size / max(1e-9, scale)
            row["parts"][x] = [gt, gf, bool(o)]
            ok, worst = ok and o, max(worst, e)
        rows.append(row)
    return {"ok": ok, "error": worst, "regimes": rows}
