"""Independent systems under a common cause (see docs/research/common_cause.md).

earned_pieces (the matrix's candidates, rows reselected, conservation decided jointly), with:

- exact.py: noise-free data fitted with a floor at float precision;
- _vendored/: private copies of the shared matrix and stepwise that take the floored fit as an
  argument (the shared modules are never patched);
- places.py: every row offered pieces at the change places other rows earned, priced as values
  only (a common cause), so a cross-link must explain what they do not.
"""

from __future__ import annotations

from ...identify import VARIANTS, judge
from ._vendored.matrix import PLAIN, identify_one
from .exact import make_scan, ops, scale_of
from .refit import refit
from . import boundary, pairing


def _identify(stocks: list[dict], run: dict, opts: dict | None = None) -> dict:
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
    b = boundary.Boundary(run)
    for v in opts.pop("variants", None) or VARIANTS:
        if v.get("split_eras") and not has_eras:
            continue
        r = identify_one(stocks, run, {**opts, **v, "keep_fit": True, "keep_rows": True, "input_columns": True}, ops_)
        if r.get("flows") is not None and r.get("fit"):
            r = refit(stocks, r, opts, ops_, b)
        if r.get("flows"):
            # (pairing.py) the offered MIN series' two outside terms made the move the offer found, before
            # the guard pairs outside flows one at a time (306 counts-long: queue -> retries took the MIN)
            r = {**r, "flows": pairing.pair(r["flows"], opts)}
        own = r
        if b.declared and r.get("flows"):
            # the guard: the judge sees each candidate inside the boundary; the chosen candidate's own
            # model is returned, so the measurement-error refit (eiv.py) decides its numbers and the
            # final guard (identify) its structure (the guard's one-step least squares numbers are
            # biased by measurement error: 303 meas-long)
            r = boundary.apply({k: v for k, v in r.items() if k not in ("fit", "ctx", "raw_rows")}, stocks, run, opts, final=False)
        e = judge(r["flows"], stocks, run, injections=opts.get("injections"), inputs=opts.get("inputs"))
        tried.append({"name": v["name"], "error": e})
        if best is None or e < best[1]:
            best = (own, e, v["name"])
    r = best[0]
    for k in ("fit", "ctx", "raw_rows"):
        r.pop(k, None)
    r["chosen"], r["tried"] = best[2], tried
    return r


def identify(stocks: list[dict], run: dict, opts: dict | None = None) -> dict:
    """The answer above with its numbers refitted by instrumental variables where the levels carry
    measurement error (eiv.py, a copy of e8edf28's), then kept inside the announced boundary
    (boundary.py: the guard and the moves where one is declared, each outside flow priced as a
    boundary claim where none is; the rows, places and ties are searched inside it, refit.py)."""
    from .eiv import apply

    return boundary.apply(apply(_identify(stocks, run, dict(opts or {})), stocks, run, opts), stocks, run, opts)


# A capacity limit offered to the fit (capmin.py, docs/research/k8s-306-s1.md, 2026-10-21): identify above
# runs with the regime-clipped series MIN(X, theta x Y) as one more measured input where the data show a
# limit, and every term that reads it is written back as MIN(a x X, a theta x Y).
from . import capmin as _capmin  # noqa: E402

_identify_linear = identify


def identify(stocks: list[dict], run: dict, opts: dict | None = None, *args, **kw) -> dict:  # noqa: F811
    """(2026-10-21, k8s-307, docs/research/k8s-307-c1.md) Between the fit and the MIN written back, where the
    levels carry measurement error, the numbers are refitted and the structure revised on the output error
    and judged on a Kalman likelihood (oefit.py, a copy of combined2's: the model run through the whole
    record against the measured levels)."""
    from . import oefit

    o, cap = _capmin.offer(stocks, run, opts)
    r = oefit.refit(_identify_linear(stocks, run, o, *args, **kw), stocks, run, o, cap)
    # (2026-10-22, port-common_cause, docs/research/fixes/port-common_cause.md) the kubernetes climb's row and
    # controller passes, copied from kalman_lna at 7c3fb13 (fix ledger types 2, 3, 6, 7, 11, 12, 15): each stock's
    # row read off the data (sparse linear, or linear plus one floored term on a declared side, with derived
    # switch, ratio, capped-move, hidden-integrator and delayed-inflow columns) and the flows of the stocks the
    # answer misses rebuilt from the rows where that wins by BIC (krows.py, kalman_lna's rows.py); then a counted stock driven to a
    # target read off another stock (a controller) replaces its outside flows where it wins by BIC (tracker.py)
    from . import krows, tracker

    r = krows.revise(_capmin.restore(r, cap), stocks, run, opts, cap)
    return tracker.revise(r, stocks, run, opts)
