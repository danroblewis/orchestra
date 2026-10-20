"""numopt (its own copy, numopt.py beside this file, of sdlab/discovery/numopt.py at aac65a0, with the run's measured inputs passed through) with CMA-ES (the `cma` package) as the optimiser."""

from .numopt import identify_with
from ...optional import require


def _identify(stocks: list[dict], run: dict, opts: dict | None = None) -> dict:
    require("cma")                          # optional: uv sync --extra research
    return identify_with("cma", stocks, run, opts)


def identify(stocks: list[dict], run: dict, opts: dict | None = None) -> dict:
    """The answer above with its numbers refitted by instrumental variables where the levels carry
    measurement error (eiv.py, a copy of e8edf28's)."""
    from .eiv import apply

    return apply(_identify(stocks, run, dict(opts or {})), stocks, run, opts)
