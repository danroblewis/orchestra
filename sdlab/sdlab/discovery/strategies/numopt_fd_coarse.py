"""numopt_fd with every outside inflow as coarse pieces with a free, priced factor per block (fitted
with the rest): the learnable-inflow ablation."""

from ..numopt import identify_with


def identify(stocks: list[dict], run: dict, opts: dict | None = None) -> dict:
    opts = dict(opts or {})
    opts["numopt"] = {"inflows": "coarse", **(opts.get("numopt") or {})}
    return identify_with("fd", stocks, run, opts)
