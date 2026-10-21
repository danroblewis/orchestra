"""Shared noise: the matrix method, with moves, links and co-flows told apart by which stocks'
unexplained changes share draws.

The shared library (identify.py, matrix.py, shared_noise.py) is pinned, so this package carries its
own copies, from commit 7b9dd2f (last changed in 04d2896): identify.py, matrix.py and noise.py (from
shared_noise.py). Changed in the copies: the noise analysis reads a row's numbers off every column
the row may take, the stocks' levels and then the measured inputs (a number on an input is an outside
inflow of that row's stock); the shared module looked every reader up among the stocks only and
crashed (KeyError) on any case with a measured input. And residuals far below counting noise of the
flows' sizes (noise-free data: the fitted dispersion under its plausible floor, 0.25) decide no move
or link; the empty covariances had been read as "link" and split noise-free moves in two."""

from __future__ import annotations

import os

from .identify import VARIANTS
from .identify import identify as _base_identify

# the experiment's settings (SDLAB_SHARED_NOISE="noise_misfit=1,..." overrides, for iterating)
# (v5, the recorded result; the v3/v4 guards: noise_misfit, noise_swap, noise_one_sided)
SETTINGS: dict = {"shared_noise": True}
for _kv in filter(None, os.environ.get("SDLAB_SHARED_NOISE", "").split(",")):
    _k, _v = _kv.split("=")
    SETTINGS[_k] = float(_v) if "." in _v else bool(int(_v)) if _v in ("0", "1") else _v


def _identify(stocks: list[dict], run: dict, opts: dict | None = None) -> dict:
    opts = dict(opts or {})
    opts.setdefault("variants", [{**v, **SETTINGS} for v in VARIANTS])
    return _base_identify(stocks, run, opts)


def identify(stocks: list[dict], run: dict, opts: dict | None = None) -> dict:
    """The answer above with its numbers refitted by instrumental variables where the levels carry
    measurement error (eiv.py, a copy of e8edf28's), then kept inside the announced boundary
    (boundary.py, a copy of matrix's: the guard where one is declared, each outside flow priced as a
    boundary claim where none is)."""
    from . import boundary
    from .eiv import apply

    r = apply(_identify(stocks, run, dict(opts or {})), stocks, run, opts)
    return boundary.apply(r, stocks, run, opts)


# A capacity limit offered to the fit (capmin.py, docs/research/k8s-306-s1.md, 2026-10-21): identify above
# runs with the regime-clipped series MIN(X, theta x Y) as one more measured input where the data show a
# limit, and every term that reads it is written back as MIN(a x X, a theta x Y).
from . import capmin as _capmin  # noqa: E402

_identify_linear = identify


def identify(stocks: list[dict], run: dict, opts: dict | None = None, *args, **kw) -> dict:  # noqa: F811
    return _capmin.wrap(_identify_linear, stocks, run, opts, *args, **kw)
