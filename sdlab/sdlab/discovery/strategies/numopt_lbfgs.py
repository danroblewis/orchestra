"""numopt (sdlab/discovery/numopt.py) with scipy L-BFGS-B on the sum of squares (gradient by finite
differences) as the optimiser."""

from ..numopt import identify_with


def identify(stocks: list[dict], run: dict, opts: dict | None = None) -> dict:
    return identify_with("lbfgs", stocks, run, opts)
