"""Ablation of the matrix method's last form choice: a row's changing inflow is kept when its mean is
clearly one way against its own standard error (opts["pieces_gate"] = "noise"), not against the spread
of the pieces' values (docs/research/inflow-attribution.md)."""

from ..identify import identify as _identify


def identify(stocks, run, opts=None):
    return _identify(stocks, run, {**(opts or {}), "pieces_gate": "noise"})
