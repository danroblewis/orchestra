"""numopt (sdlab/discovery/numopt.py) with CMA-ES (the `cma` package) as the optimiser."""

from ..numopt import identify_with


def identify(stocks: list[dict], run: dict, opts: dict | None = None) -> dict:
    return identify_with("cma", stocks, run, opts)
