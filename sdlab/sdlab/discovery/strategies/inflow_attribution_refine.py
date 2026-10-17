"""Inflow attribution as a refinement of the main line's chosen model only: its flagged rows repaired,
and the judge keeps the repaired model only if it rates it better (inflow_attribution.py)."""

from .inflow_attribution import identify as _identify


def identify(stocks, run, opts=None):
    return _identify(stocks, run, {**(opts or {}), "ia_refine": True})
