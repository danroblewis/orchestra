"""numopt (sdlab/discovery/numopt.py) with scipy's Nelder-Mead (derivative-free simplex) as the
optimiser."""

from ..numopt import identify_with


def identify(stocks: list[dict], run: dict, opts: dict | None = None) -> dict:
    return identify_with("nm", stocks, run, opts)
