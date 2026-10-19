"""Experiment mass_balance with the balance tried on every candidate of the main line ("mb_all")."""

from ._vendored.mass_balance import identify as _identify


def identify(stocks: list[dict], run: dict, opts: dict | None = None) -> dict:
    return _identify(stocks, run, {"mb_all": True, **(opts or {})})
