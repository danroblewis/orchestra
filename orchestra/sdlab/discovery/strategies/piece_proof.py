"""The main line's candidates (identify.VARIANTS), chosen by a judge the candidates' own outside-inflow
pieces cannot fool (sdlab/discovery/judges.py; docs/research/inflow-conditioned-judge.md).

opts["judge"] names the judge (default JUDGE); opts["variants"] replaces the candidate list, as in
identify.
"""

from __future__ import annotations

from ..identify import VARIANTS
from ..judges import choose
from ..matrix import identify_one, known_flows

JUDGE = "common"


def identify(stocks: list[dict], run: dict, opts: dict | None = None) -> dict:
    opts = dict(opts or {})
    judge = opts.pop("judge", JUDGE)
    has_eras = len({e.get("label") or e.get("start") for e in opts.get("eras") or [] if e}) >= 2
    extra = known_flows(opts["known"], [s["id"] for s in stocks], run["t"]) if opts.get("known") else []
    results, names = [], []
    for v in opts.pop("variants", None) or VARIANTS:
        if v.get("split_eras") and not has_eras:
            continue
        results.append(identify_one(stocks, run, {**opts, **v}))
        names.append(v["name"])
    best, errors = choose([r["flows"] for r in results], stocks, run, judge, extra=extra)
    r = results[best]
    r["chosen"], r["judge"] = names[best], judge
    r["tried"] = [{"name": n, "error": e} for n, e in zip(names, errors)]
    return r
