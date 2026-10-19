"""matrix_v2: the matrix method with the fixes other strategies proposed for it, each an option
(docs/research/matrix_v2.md; queue item 6).

The shared library's matrix method (sdlab/discovery/identify.py, matrix.py, flows.py, regression.py)
is pinned, so this package carries its own copies (matrix.py, flows.py, regression.py, and identify()
below, from commit aad5c7b) and changes those. With every option off it is the matrix.

  option          fix                                                          proposed by
  rss_floor       every BIC's rss floored at the data's rounding               earned_pieces
  pelt_mult 2     inflow changes priced at 2 log n (PELT), not 1               censored (re-cut)
  white           a constant inflow kept unless its residuals are not white    earned_pieces
  pool            pieces pooled into a few values and re-cut (case 027)        effect_hats
  tie_se          conservation's tie tested with both rows' standard errors    earned_pieces
  falling_inflow  a negative cross reading read as a falling inflow (a gap)    censored (links)
  gap_inflow      a gap over several stocks as one floored linear inflow       structures
  pair_moves      a drain and a link at one level paired into a move           effect_hats
  products        a x c columns, c = a or the destination allowed              structures
  inputs_judge    the judge steps every candidate with the measured inputs     earned_pieces, censored

Options come from opts, then the SDLAB_MATRIX_V2 environment variable (JSON; for ablations only:
the ladder's result store keys results by the code, not the environment).
"""

from __future__ import annotations

import json
import os

from ...simulate import behaviour_error
from .matrix import identify_one, known_flows

# (the defaults: the combination chosen by the ablation in docs/research/matrix_v2.md)
OPTIONS: dict = {
    "rss_floor": False,
    "pelt_mult": 1,
    "white": False,
    "pool": False,
    "tie_se": False,
    "falling_inflow": False,
    "gap_inflow": False,
    "pair_moves": False,
    "products": False,
    "inputs_judge": False,
}

# each combination of: forward or backward search; outside inflows that change or stay constant;
# trusting the receivers or the rows where stocks are seen receiving more than a stock's own row
# says it loses; and (with announced eras) numbers per configuration (identify.VARIANTS)
VARIANTS: list[dict] = []
for search in ({"name": "forward"}, {"name": "backward", "backward_max": 20}):
    for inflow in ({"name": "changing inflows"}, {"name": "constant inflows", "changes": False}):
        for recv in ({"name": "trust receivers"}, {"name": "trust rows", "trust_receivers": False}):
            for era in ({"name": ""}, {"name": ", numbers per era", "split_eras": True}):
                VARIANTS.append({**search, **inflow, **recv, **era, "name": f"{search['name']}, {inflow['name']}, {recv['name']}{era['name']}"})


def judge(flows: list[dict], stocks: list[dict], run: dict, horizons=(5, 20, 100), injections: list[dict] | None = None,
          inputs: dict | None = None) -> float:
    """identify.judge: runs from many moments in the data over 5, 20 and 100 steps; with inputs (the
    option inputs_judge) every run reads the measured inputs the flows read."""
    hs = [h for h in horizons if h < len(run["t"]) / 4]
    if not flows or not hs:
        return float("inf")
    ids = [s["id"] for s in stocks]
    return sum(behaviour_error(flows, ids, run["t"], run["levels"], horizon=h, injections=injections, inputs=inputs) for h in hs) / len(hs)


def options(opts: dict | None) -> dict:
    env = json.loads(os.environ.get("SDLAB_MATRIX_V2") or "{}")
    return {**OPTIONS, **(opts or {}), **env}


def identify(stocks: list[dict], run: dict, opts: dict | None = None) -> dict:
    opts = options(opts)
    keep = opts.pop("candidates", False)                 # the bench grades every candidate
    has_eras = len({e.get("label") or e.get("start") for e in opts.get("eras") or [] if e}) >= 2
    inputs = opts.get("inputs") or None if opts.get("inputs_judge") else None
    best, tried, candidates = None, [], []
    extra = known_flows(opts["known"], [s["id"] for s in stocks], run["t"]) if opts.get("known") else []
    for v in opts.pop("variants", None) or VARIANTS:
        if v.get("split_eras") and not has_eras:
            continue
        r = identify_one(stocks, run, {**opts, **v})
        e = judge(r["flows"] + extra if r["flows"] else [], stocks, run, injections=opts.get("injections"), inputs=inputs)
        tried.append({"name": v["name"], "error": e})
        if keep:
            candidates.append({"name": v["name"], "error": e, "flows": r["flows"]})
        if best is None or e < best[1]:
            best = (r, e, v["name"])
    r = best[0]
    r["chosen"], r["tried"] = best[2], tried
    if keep:
        r["candidates"] = candidates
    return r
