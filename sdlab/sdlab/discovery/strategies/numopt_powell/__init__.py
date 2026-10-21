"""numopt (its own copy, numopt.py beside this file, of sdlab/discovery/numopt.py at aac65a0, with the run's measured inputs passed through) with scipy's Powell (derivative-free line searches) as the
optimiser."""

from .numopt import identify_with


def _identify(stocks: list[dict], run: dict, opts: dict | None = None) -> dict:
    return identify_with("powell", stocks, run, opts)


def identify(stocks: list[dict], run: dict, opts: dict | None = None) -> dict:
    """The answer above with its numbers refitted by instrumental variables where the levels carry
    measurement error (eiv.py, a copy of e8edf28's), then kept inside the announced boundary
    (boundary.py, a copy of matrix's at 723f72c; docs/research/declared-boundary.md): the guard and
    the moves where one is declared, each outside flow priced as a boundary claim where none is."""
    from . import boundary
    from .eiv import apply

    r = apply(_identify(stocks, run, dict(opts or {})), stocks, run, opts)
    return boundary.apply(r, stocks, run, opts)
