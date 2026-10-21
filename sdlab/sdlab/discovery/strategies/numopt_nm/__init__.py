"""numopt (its own copy, numopt.py beside this file, of sdlab/discovery/numopt.py at aac65a0, with the run's measured inputs passed through) with scipy's Nelder-Mead (derivative-free simplex) as the
optimiser."""

from .numopt import identify_with


def _identify(stocks: list[dict], run: dict, opts: dict | None = None) -> dict:
    return identify_with("nm", stocks, run, opts)


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
    return _capmin.wrap(_identify_linear, stocks, run, opts, *args, **kw)
