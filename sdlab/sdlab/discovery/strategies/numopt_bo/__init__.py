"""numopt (its own copy, numopt.py beside this file, of sdlab/discovery/numopt.py at aac65a0, with the run's measured inputs passed through) with Bayesian optimisation (a Gaussian process on log error,
expected improvement) as the optimiser; fits of more than `bo_max` numbers are skipped."""

from .numopt import identify_with


def identify(stocks: list[dict], run: dict, opts: dict | None = None) -> dict:
    return identify_with("bo", stocks, run, opts)
