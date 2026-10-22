"""engine_forms: kalman_lna's model with each stock's exchange re-read in the forms the engine can
now write (docs/research/engine_forms.md).

The base is a copy of kalman_lna (as at commit 6a93270, in _kalman/; its own copies of combined,
lna and the rest inside it), so changing kalman_lna never changes this strategy (sdlab/CLAUDE.md
invariant 11). Its answer is then read again stock by stock (judge.py): x's flows to and from the
outside and the moves into it are replaced by one of the forms of forms.py where that form fits
x's one-step change clearly better for its numbers (BIC, every inflow piece counted):

- a linear exchange that runs both ways (an input that changes sign; a stock below 0), written as
  an inflow and a drain shifted by the same constant, or as one two-way flow for a signed stock;
- a drain at MIN(a x level, capacity), capacity a linear function of other stocks or inputs;
- an inflow that is a table of a stock or an input, optionally times an input (a dead zone; an
  admission gate), beside the stock's linear flows.

Where the base read the levels as noisy reports (kalman_lna's filter chosen), its answer is kept:
one-step changes of noisy levels are not the flows.
"""

from __future__ import annotations

import numpy as np

from ._kalman import boundary
from ._kalman import identify as base
from .judge import improve
from .steps import build


def _identify(stocks: list[dict], run: dict, opts: dict | None = None) -> dict:
    opts = dict(opts or {})
    r = base(stocks, run, opts)
    if (r.get("kalman") or {}).get("reading"):
        return r          # the base read the levels as noisy reports: one-step changes of them are not the flows
    st = build(stocks, run, opts)
    if st is None:
        return r
    trace: list[str] = []
    b = boundary.Boundary(run)
    ids, inputs = [s["id"] for s in stocks], set(opts.get("inputs") or {})
    flows = improve(list(r.get("flows") or []), st, trace=trace,
                    outside=lambda fl: len(boundary.violations(fl, ids, b, inputs)))
    return {**r, "flows": flows, "engine_forms": {"trace": trace}}


def identify(stocks: list[dict], run: dict, opts: dict | None = None) -> dict:
    """The answer above with its numbers refitted by instrumental variables where the levels carry
    measurement error (eiv.py), then kept inside the announced boundary (_kalman/boundary.py: the guard
    and the moves where one is declared, each outside flow priced as a boundary claim where none is;
    the base's search and the forms pass are inside it too)."""
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
    from . import tidy

    r = _identify_linear(stocks, run, o, *args, **kw)
    r = _guarded("oefit", lambda: oefit.refit(r, stocks, run, o, cap), r)
    r = _guarded("tidy", lambda: tidy.apply(r, run, o), r)   # negligible terms dropped, before the MIN is written back (tidy.py, k8s-307)
    from . import controller, reread

    r = _capmin.restore(r, cap)
    r = _guarded("reread", lambda: reread.apply(r, stocks, run, opts), r)        # exact rows read again where the answer misses them (k8s-309)
    from . import pool

    r = _guarded("pool", lambda: pool.apply(r, stocks, run, opts), r)            # a move the declared boundary forces across units, from its two rows (k8s-316)
    r = _guarded("controller", lambda: controller.apply(r, stocks, run, opts), r)  # count stocks driven to a quantized target (k8s-308)
    from . import hidden

    r = _guarded("hidden", lambda: hidden.apply(r, stocks, run, opts), r)      # a row reading a hidden integrator, written as a hidden stock (k8s-310)
    from . import delay

    return _guarded("delay", lambda: delay.apply(r, stocks, run, opts), r)    # a stock fed from outside through a hidden DELAY1 stage (k8s-312); last


def _guarded(name: str, step, r: dict) -> dict:
    """A later pass whose linear algebra fails numerically (LAPACK's SVD not converging on a run that blows up:
    k8s-312 counts-long on the Mac, job 316) keeps its input, and says so in the trace (fix-ledger type 10, the
    refit-guard of structures 3bf52d6). Only numerical failures are caught; any other error still raises."""
    try:
        return step()
    except (np.linalg.LinAlgError, FloatingPointError) as e:
        import traceback

        where = next((f"{fr.filename.rsplit('/', 1)[-1]}:{fr.lineno}" for fr in reversed(traceback.extract_tb(e.__traceback__))
                      if "engine_forms" in fr.filename), "?")
        note = f"{name}: {type(e).__name__} at {where} ({e}); its input kept"
        ef = dict(r.get("engine_forms") or {})
        ef["trace"] = list(ef.get("trace") or []) + [note]
        return {**r, "engine_forms": ef, "guarded": list(r.get("guarded") or []) + [note]}
