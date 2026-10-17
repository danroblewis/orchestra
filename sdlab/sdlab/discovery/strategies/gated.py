"""The main line with a behaviour-consistency gate before the judge (docs/research/behaviour-consistency.md).

Every candidate of identify() is first run freely from observed, empty and high states, with its
own and with mean outside inflows (gate.check); one whose stocks run off beyond a generous multiple
of their observed range is not judged. A rejected candidate whose culprit coefficient (from the
linearisation where it fails) is in one of its rows is refitted once with that coefficient bounded
at 0 (scipy lsq_linear on the row's single steps, with its inflow pieces), and the refit joins the
candidates. The judge then chooses among those that pass; if none passes, among all.

opts: "gate" (gate.check's opts, e.g. {"tests": ("observed",)}), "repair" (default True).
"""

from __future__ import annotations

from itertools import pairwise

import numpy as np
from scipy.optimize import lsq_linear

from ..flows import read_flows
from ..gate import check, choose
from ..identify import VARIANTS, judge
from ..matrix import identify_one, known_flows


def refit(stocks: list[dict], run: dict, r: dict, c: dict) -> dict | None:
    """Candidate r with row c["row"] refitted, its number on c["level"] bounded at 0 (on the side
    that pushed the growth); None when that number is not in the row (or eras split the rows)."""
    if r.get("eras") or not r.get("matrix"):
        return None
    ids = [s["id"] for s in stocks]
    row = next((x for x in r["matrix"] if x["id"] == c["row"]), None)
    if row is None or c["level"] not in row["coef"] or np.sign(row["coef"][c["level"]]) != np.sign(c["k"]):
        return None
    t = run["t"]
    lv = np.nan_to_num(np.array([np.asarray(run["levels"].get(i, [0] * len(t)), dtype=float) for i in ids]))
    prev, dy = lv[:, :-1], np.diff(lv, axis=1)
    T = prev.shape[1]
    y = dy[ids.index(c["row"])]
    levels = list(row["coef"])
    cuts = row.get("cuts")
    cols = [prev[ids.index(j)] for j in levels]
    pieces = list(pairwise(cuts)) if cuts else []
    for a, b in pieces:
        x = np.zeros(T)
        x[a:b] = 1.0
        cols.append(x)
    X = np.array(cols).T
    lb, ub = np.full(X.shape[1], -np.inf), np.full(X.shape[1], np.inf)
    q = levels.index(c["level"])
    if c["k"] > 0:
        ub[q] = 0.0
    else:
        lb[q] = 0.0
    scale = np.maximum(1e-9, np.abs(X).max(axis=0))
    fit = lsq_linear(X / scale, y, bounds=(lb * scale, ub * scale))
    beta = fit.x / scale
    coef = {j: float(b) for j, b in zip(levels, beta[: len(levels)]) if abs(b) > 1e-12}
    inflow = [{"from": t[a + 1], "to": t[b], "value": float(v)} for (a, b), v in zip(pieces, beta[len(levels):])]
    rows = [{"id": x["id"], "coef": coef if x["id"] == c["row"] else x["coef"], "inflow": inflow if x["id"] == c["row"] else x["inflow"]} for x in r["matrix"]]
    flows = read_flows(stocks, rows, prev)
    matrix = [{**x, "coef": coef, "coefL": [coef], "inflow": inflow} if x["id"] == c["row"] else x for x in r["matrix"]]
    return {**r, "flows": flows, "matrix": matrix, "refit": {**c, "bounded": 0.0}}


def identify(stocks: list[dict], run: dict, opts: dict | None = None) -> dict:
    opts = dict(opts or {})
    gate_opts = opts.pop("gate", None)
    repair = opts.pop("repair", True)
    has_eras = len({e.get("label") or e.get("start") for e in opts.get("eras") or [] if e}) >= 2
    extra = known_flows(opts["known"], [s["id"] for s in stocks], run["t"]) if opts.get("known") else []
    with_extra = lambda flows: flows + extra if flows else []
    cands: list[tuple[str, dict]] = []
    for v in opts.pop("variants", None) or VARIANTS:
        if v.get("split_eras") and not has_eras:
            continue
        cands.append((v["name"], identify_one(stocks, run, {**opts, **v})))
    repaired = []
    if repair:
        seen = set()
        for name, r in cands:
            key = repr(r["flows"])
            if key in seen or not r["flows"]:
                continue
            seen.add(key)
            v = check(with_extra(r["flows"]), stocks, run, gate_opts)
            if not v["ok"] and v["culprit"]:
                r2 = refit(stocks, run, r, v["culprit"])
                if r2 is not None:
                    repaired.append((f"{name}, {v['culprit']['row']} on {v['culprit']['level']} bounded", r2))
    cands += repaired
    ch = choose([(n, with_extra(r["flows"])) for n, r in cands], stocks, run, judge, gate_opts)
    r = cands[ch["best"]][1]
    r["chosen"] = cands[ch["best"]][0]
    r["tried"] = [{"name": n, "error": e if e is not None else float("inf"), "gate": "pass" if v["ok"] else [f"{x['test']}/{x['inflows']}: {x['stock']}" for x in v["reasons"]]}
                  for (n, _), e, v in zip(cands, ch["errors"], ch["verdicts"])]
    r["gate"] = {"candidates": len(cands), "passed": ch["passed"], "repaired": len(repaired),
                 "rejected": [{"name": n, "reasons": v["reasons"], "culprit": v["culprit"]} for (n, _), v in zip(cands, ch["verdicts"]) if not v["ok"]]}
    return r
