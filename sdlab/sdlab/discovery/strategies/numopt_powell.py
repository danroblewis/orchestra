"""numopt (sdlab/discovery/numopt.py) with scipy's Powell (derivative-free line searches) as the
optimiser."""

from ..numopt import identify_with


def identify(stocks: list[dict], run: dict, opts: dict | None = None) -> dict:
    return identify_with("powell", stocks, run, opts)
