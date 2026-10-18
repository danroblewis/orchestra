"""Shared noise: the matrix method, with moves, links and co-flows told apart by which stocks'
unexplained changes share draws (sdlab/discovery/shared_noise.py)."""

from __future__ import annotations

import os

from ..identify import VARIANTS
from ..identify import identify as _identify

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
