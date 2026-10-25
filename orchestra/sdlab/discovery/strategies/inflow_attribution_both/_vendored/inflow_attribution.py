"""Inflow attribution: every candidate's rows tested by counting noise and partial-model simulation, a
flagged row refitted with its drain measured within stretches and its inflow recovered with the drain
held (sdlab/discovery/attribution.py); the judge chooses among the repaired candidates (and, with
opts["ia_originals"], the unrepaired ones too). docs/research/inflow-attribution.md.

opts["ia_refine"]: repair only the main line's chosen model (a refinement of its choice).
"""

from __future__ import annotations

from orchestra.sdlab.discovery.attribution import Data, repair, to_flows
from orchestra.sdlab.discovery.identify import VARIANTS, identify as main_line, judge
from orchestra.sdlab.discovery.matrix import identify_one, known_flows


def identify(stocks: list[dict], run: dict, opts: dict | None = None) -> dict:
    opts = dict(opts or {})
    keep = opts.pop("candidates", False)
    with_originals = opts.pop("ia_originals", False)
    refine = opts.pop("ia_refine", False)
    ids = [s["id"] for s in stocks]
    extra = known_flows(opts["known"], ids, run["t"]) if opts.get("known") else []
    has_eras = len({e.get("label") or e.get("start") for e in opts.get("eras") or [] if e}) >= 2
    if refine:
        base = main_line(stocks, run, opts)
        variants = [v for v in VARIANTS if v["name"] == base["chosen"]]
    else:
        variants = [v for v in VARIANTS if not (v.get("split_eras") and not has_eras)]
    best, tried, candidates = None, [], []

    def consider(name, r):
        nonlocal best
        e = judge(r["flows"] + extra if r["flows"] else [], stocks, run)
        tried.append({"name": name, "error": e})
        if keep:
            candidates.append({"name": name, "error": e, "flows": r["flows"]})
        if best is None or e < best[1]:
            best = (r, e, name)

    for v in variants:
        r = identify_one(stocks, run, {**opts, **v})
        if not r.get("flows"):
            consider(v["name"], r)
            continue
        d = Data(stocks, run, opts).with_eras(opts.get("eras") if r.get("eras") else None)
        rows, report = repair(r["matrix"], d, opts)
        if with_originals or refine or not any(x["replaced"] for x in report):
            consider(v["name"], r)
        if any(x["replaced"] for x in report):
            fixed = {**r, "flows": to_flows(rows, d, opts.get("tol", 0.003)), "matrix": [{k: x for k, x in row.items()} for row in rows], "attribution": report}
            consider(v["name"] + ", inflows attributed", fixed)
    r = best[0]
    r["chosen"], r["tried"] = best[2], tried
    if keep:
        r["candidates"] = candidates
    return r
