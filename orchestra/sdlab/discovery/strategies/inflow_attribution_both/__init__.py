"""Inflow attribution with the unrepaired candidates kept beside the repaired ones: the judge chooses
among both (inflow_attribution.py)."""

from ._vendored.inflow_attribution import identify as _identify


def identify(stocks, run, opts=None):
    return _identify(stocks, run, {**(opts or {}), "ia_originals": True})
