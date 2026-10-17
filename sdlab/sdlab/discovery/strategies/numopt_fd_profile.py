"""numopt_fd with the found outside inflows of every stock a chosen term touches re-measured at
every evaluation (what the stock's one-step change leaves over in each piece): the inflow ablation
the effect mechanism test needs (an effect replacing links changes its source's balance)."""

from ..numopt import identify_with


def identify(stocks: list[dict], run: dict, opts: dict | None = None) -> dict:
    opts = dict(opts or {})
    opts["numopt"] = {"inflows": "profile", **(opts.get("numopt") or {})}
    return identify_with("fd", stocks, run, opts)
