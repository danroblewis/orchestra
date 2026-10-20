"""numopt (its own copy, numopt.py beside this file, of sdlab/discovery/numopt.py at aac65a0, with the run's measured inputs passed through) with Bayesian optimisation (a Gaussian process on log error,
expected improvement) as the optimiser; fits of more than `bo_max` numbers are skipped."""

from .numopt import identify_with


def _identify(stocks: list[dict], run: dict, opts: dict | None = None) -> dict:
    return identify_with("bo", stocks, run, opts)


def identify(stocks: list[dict], run: dict, opts: dict | None = None) -> dict:
    """The answer above with its numbers refitted by instrumental variables where the levels carry
    measurement error (eiv.py, a copy of e8edf28's)."""
    from .eiv import apply

    return apply(_identify(stocks, run, dict(opts or {})), stocks, run, opts)
