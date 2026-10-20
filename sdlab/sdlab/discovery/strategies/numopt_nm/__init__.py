"""numopt (its own copy, numopt.py beside this file, of sdlab/discovery/numopt.py at aac65a0, with the run's measured inputs passed through) with scipy's Nelder-Mead (derivative-free simplex) as the
optimiser."""

from .numopt import identify_with


def identify(stocks: list[dict], run: dict, opts: dict | None = None) -> dict:
    return identify_with("nm", stocks, run, opts)
