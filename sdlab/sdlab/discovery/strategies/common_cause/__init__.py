"""Independent systems under a common cause (see docs/research/common_cause.md).

earned_pieces (the matrix's candidates, rows reselected, conservation decided jointly), with:

- exact.py: noise-free data fitted with a floor at float precision;
- (to come) cross-links tested against shared change places.
"""

from __future__ import annotations

from ...identify import VARIANTS, judge
from ...matrix import identify_one
from ..earned_pieces import refit
from .exact import floored, make_scan, scale_of


def identify(stocks: list[dict], run: dict, opts: dict | None = None) -> dict:
    opts = dict(opts or {})
    ids = [s["id"] for s in stocks]
    scale = scale_of(run, ids)
    exact = opts.pop("exact", True)
    if exact and "scan" not in opts:
        opts["scan"] = make_scan(scale, opts.get("min_piece", 5))
    has_eras = len({e.get("label") or e.get("start") for e in opts.get("eras") or [] if e}) >= 2
    best, tried = None, []
    with floored(scale) if exact else _null():
        for v in opts.pop("variants", None) or VARIANTS:
            if v.get("split_eras") and not has_eras:
                continue
            r = identify_one(stocks, run, {**opts, **v, "keep_fit": True, "keep_rows": True})
            if r.get("flows") is not None and r.get("fit"):
                r = refit(stocks, r, opts)
            e = judge(r["flows"], stocks, run, injections=opts.get("injections"))
            tried.append({"name": v["name"], "error": e})
            if best is None or e < best[1]:
                best = (r, e, v["name"])
    r = best[0]
    for k in ("fit", "ctx", "raw_rows"):
        r.pop(k, None)
    r["chosen"], r["tried"] = best[2], tried
    return r


class _null:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False
