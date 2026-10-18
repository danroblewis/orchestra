"""numopt (sdlab/discovery/numopt.py) with CMA-ES (the `cma` package) as the optimiser."""

from ..numopt import identify_with
from ..optional import require


def identify(stocks: list[dict], run: dict, opts: dict | None = None) -> dict:
    require("cma")                          # optional: uv sync --extra research
    return identify_with("cma", stocks, run, opts)
