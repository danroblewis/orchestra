"""numopt (its own copy, numopt.py beside this file, of sdlab/discovery/numopt.py at aac65a0, with the run's measured inputs passed through) with CMA-ES (the `cma` package) as the optimiser."""

from .numopt import identify_with
from ...optional import require


def _identify(stocks: list[dict], run: dict, opts: dict | None = None) -> dict:
    require("cma")                          # optional: uv sync --extra research
    return identify_with("cma", stocks, run, opts)


def identify(stocks: list[dict], run: dict, opts: dict | None = None) -> dict:
    """The answer above with its numbers refitted by instrumental variables where the levels carry
    measurement error (eiv.py, a copy of e8edf28's), then kept inside the announced boundary
    (boundary.py, a copy of matrix's at 723f72c; docs/research/declared-boundary.md): the guard and
    the moves where one is declared, each outside flow priced as a boundary claim where none is."""
    from . import boundary
    from .eiv import apply

    r = apply(_identify(stocks, run, dict(opts or {})), stocks, run, opts)
    return boundary.apply(r, stocks, run, opts)


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
    return _capmin.restore(r, cap)
