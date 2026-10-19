# Vendored for combined2 from sdlab/discovery/strategies/common_cause/__init__.py at commit 3f5f064 (HEAD ebe9a4f); imports
# rewritten to these copies, otherwise unchanged (CLAUDE.md invariant 11). Re-vendor rather than edit.
"""Independent systems under a common cause (see docs/research/common_cause.md).

earned_pieces (the matrix's candidates, rows reselected, conservation decided jointly), with:

- exact.py: noise-free data fitted with a floor at float precision;
- _vendored/: private copies of the shared matrix and stepwise that take the floored fit as an
  argument (the shared modules are never patched);
- places.py: every row offered pieces at the change places other rows earned, priced as values
  only (a common cause), so a cross-link must explain what they do not.
"""

from __future__ import annotations

from sdlab.discovery.identify import VARIANTS, judge
from sdlab.discovery.strategies.combined2._vendored.common_cause._vendored.matrix import PLAIN, identify_one
from .exact import make_scan, ops, scale_of
from .refit import refit


def identify(stocks: list[dict], run: dict, opts: dict | None = None) -> dict:
    opts = dict(opts or {})
    ids = [s["id"] for s in stocks]
    scale = scale_of(run, ids)
    exact = opts.pop("exact", True)
    if exact and "scan" not in opts:
        opts["scan"] = make_scan(scale, opts.get("min_piece", 5))
    has_eras = len({e.get("label") or e.get("start") for e in opts.get("eras") or [] if e}) >= 2
    best, tried = None, []
    # exact: the floored fit, stepwise and PELT (exact.py), passed to the private copy of the matrix
    ops_ = ops(scale) if exact else PLAIN
    for v in opts.pop("variants", None) or VARIANTS:
        if v.get("split_eras") and not has_eras:
            continue
        r = identify_one(stocks, run, {**opts, **v, "keep_fit": True, "keep_rows": True}, ops_)
        if r.get("flows") is not None and r.get("fit"):
            r = refit(stocks, r, opts, ops_)
        e = judge(r["flows"], stocks, run, injections=opts.get("injections"))
        tried.append({"name": v["name"], "error": e})
        if best is None or e < best[1]:
            best = (r, e, v["name"])
    r = best[0]
    for k in ("fit", "ctx", "raw_rows"):
        r.pop(k, None)
    r["chosen"], r["tried"] = best[2], tried
    return r
