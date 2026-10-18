"""numopt (sdlab/discovery/numopt.py) with Bayesian optimisation (a Gaussian process on log error,
expected improvement) as the optimiser; fits of more than `bo_max` numbers are skipped."""

from ..numopt import identify_with


def identify(stocks: list[dict], run: dict, opts: dict | None = None) -> dict:
    return identify_with("bo", stocks, run, opts)
