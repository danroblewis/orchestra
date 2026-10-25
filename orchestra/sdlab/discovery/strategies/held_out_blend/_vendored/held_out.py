"""Candidates chosen on data they were not fitted on (experiment: held-out judge).

The same candidate ways of estimating the matrix as the main line (identify.VARIANTS), but each is
judged by blocked cross-validation (holdout.py): the run is cut into contiguous blocks, the
candidate is fitted on all but one, and run forward inside the held-out block, its outside inflows
there taken from what the fit knows (the piece in force before the block). The candidate with the
lowest held-out error is then fitted on all the data.
"""

from __future__ import annotations

import math

from orchestra.sdlab.discovery.holdout import held_out_errors
from orchestra.sdlab.discovery.identify import VARIANTS, judge
from orchestra.sdlab.discovery.matrix import identify_one

FOLDS = 5
HORIZONS = (5, 20, 100)
CAP = 1e3          # one block where a candidate runs away counts as badly as any other runaway


def score(blocks: list[dict]) -> float:
    vals = []
    for b in blocks:
        e = [min(CAP, v) for v in b["errors"].values()]
        if e:
            vals.append(sum(e) / len(e))
    return sum(vals) / len(vals) if vals else float("inf")


def identify(stocks: list[dict], run: dict, opts: dict | None = None) -> dict:
    """opts beyond identify_one's: folds, fill ("last" or "mean"), horizons, and blend: with
    blend > 0 the score is log(in-sample error) + blend x log(held-out error) (the main line's judge,
    nudged by the held-out one)."""
    opts = dict(opts or {})
    folds, fill = opts.pop("folds", FOLDS), opts.pop("fill", "last")
    horizons, blend = opts.pop("horizons", HORIZONS), opts.pop("blend", 0)
    has_eras = len({e.get("label") or e.get("start") for e in opts.get("eras") or [] if e}) >= 2
    best, tried = None, []
    for v in opts.pop("variants", None) or VARIANTS:
        if v.get("split_eras") and not has_eras:
            continue
        e = score(held_out_errors(stocks, run, {**opts, **v}, folds=folds, horizons=horizons, fill=fill))
        full = None
        if blend:
            full = identify_one(stocks, run, {**opts, **v})
            e = math.log(max(1e-9, judge(full["flows"], stocks, run))) + blend * math.log(max(1e-9, e))
        tried.append({"name": v["name"], "error": e})
        if best is None or e < best[1]:
            best = (v, e, full)
    r = best[2] or identify_one(stocks, run, {**opts, **best[0]})
    r["chosen"], r["tried"] = best[0]["name"], tried
    return r
