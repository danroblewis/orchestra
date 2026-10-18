"""lna: flows chosen by the likelihood of the per-step changes under counting noise (the linear noise
approximation), all rows fitted together with each flow a shared column.

The averages of the changes give only the linear system (one matrix); the covariance of the changes
tells a move (its draw leaves the source as it arrives) from a link (it does not), a co-flow (it
mirrors at the ratio `per`) from an independent drain, and births from deaths (the mean is their
difference, the variance their sum). Noise-free data has no covariance to read: there the matrix
method's reading is returned unchanged.
"""

from __future__ import annotations

from ...identify import identify as _matrix
from .run import discover


def identify(stocks: list[dict], run: dict, opts: dict | None = None) -> dict:
    opts = dict(opts or {})
    base = _matrix(stocks, run, dict(opts))
    found = discover(stocks, run, opts, base)
    return found if found is not None else base
