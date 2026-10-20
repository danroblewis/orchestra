"""Shared noise: the matrix method, with moves, links and co-flows told apart by which stocks'
unexplained changes share draws.

The shared library (identify.py, matrix.py, shared_noise.py) is pinned, so this package carries its
own copies, from commit 7b9dd2f (last changed in 04d2896): identify.py, matrix.py and noise.py (from
shared_noise.py). Changed in the copies: the noise analysis reads a row's numbers off every column
the row may take, the stocks' levels and then the measured inputs (a number on an input is an outside
inflow of that row's stock); the shared module looked every reader up among the stocks only and
crashed (KeyError) on any case with a measured input."""

from __future__ import annotations

import os

from .identify import VARIANTS
from .identify import identify as _identify

# the experiment's settings (SDLAB_SHARED_NOISE="noise_misfit=1,..." overrides, for iterating)
# (v5, the recorded result; the v3/v4 guards: noise_misfit, noise_swap, noise_one_sided)
SETTINGS: dict = {"shared_noise": True}
for _kv in filter(None, os.environ.get("SDLAB_SHARED_NOISE", "").split(",")):
    _k, _v = _kv.split("=")
    SETTINGS[_k] = float(_v) if "." in _v else bool(int(_v)) if _v in ("0", "1") else _v


def identify(stocks: list[dict], run: dict, opts: dict | None = None) -> dict:
    opts = dict(opts or {})
    opts.setdefault("variants", [{**v, **SETTINGS} for v in VARIANTS])
    return _identify(stocks, run, opts)
