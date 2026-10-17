"""The matrix method, then its model's numbers (and optional effects and co-flows, chosen by forward
selection) fitted by multi-step error with scipy least_squares, Jacobian by finite differences
(sdlab/discovery/numopt.py)."""

from ..numopt import identify_with


def identify(stocks: list[dict], run: dict, opts: dict | None = None) -> dict:
    return identify_with("fd", stocks, run, opts)
