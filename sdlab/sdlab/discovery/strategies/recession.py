"""The matrix method plus recession drains (sdlab/discovery/recession.py) as extra candidates.

Every candidate of the main line is entered as it is and, where some row's outside inflow has quiet
stretches whose fit differs from the row's own, again with those rows' levels fitted on the quiet steps
and the inflow measured with them fixed. The judge chooses among all of them, as in identify().
"""

from __future__ import annotations

import json
import os

from ..identify import VARIANTS, judge
from ..matrix import identify_one, known_flows
from ..recession import apply


# the recession options (recession.py); SDLAB_RECESSION (JSON) overrides them for bench ablations
DEFAULTS: dict = {"recession_piece": 2, "recession_trim": 1}


def identify(stocks: list[dict], run: dict, opts: dict | None = None) -> dict:
    opts = {**DEFAULTS, **json.loads(os.environ.get("SDLAB_RECESSION") or "{}"), **(opts or {})}
    has_eras = len({e.get("label") or e.get("start") for e in opts.get("eras") or [] if e}) >= 2
    extra = known_flows(opts["known"], [s["id"] for s in stocks], run["t"]) if opts.get("known") else []
    best, tried = None, []
    for v in opts.pop("variants", None) or VARIANTS:
        if v.get("split_eras") and not has_eras:
            continue
        r = identify_one(stocks, run, {**opts, **v})
        cands = [(r, v["name"])]
        # with announced eras, a candidate whose numbers are shared across eras has pieces standing in
        # for the eras' changes, and its "quiet" steps would come from one era: split-era candidates only
        split_only = opts.get("recession_split_only") and has_eras and not v.get("split_eras")
        q = None if split_only else apply(stocks, run, r, {**opts, **v})
        if q is not None:
            # replace: the quiet test alone decides (the judge never sees the row's biased drain)
            cands = cands[:0] if opts.get("recession_replace") else cands
            cands.append((q, v["name"] + ", recession drains"))
        for c, name in cands:
            e = judge(c["flows"] + extra if c["flows"] else [], stocks, run)
            tried.append({"name": name, "error": e})
            if best is None or e < best[1]:
                best = (c, e, name)
    r = best[0]
    r["chosen"], r["tried"] = best[2], tried
    return r
