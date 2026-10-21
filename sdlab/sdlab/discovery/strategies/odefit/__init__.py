"""odefit: per-step models linear in their numbers, fitted by output error (docs/research/odefit.md)."""

from __future__ import annotations

from .run import identify

__all__ = ["identify"]


# A capacity limit offered to the fit (capmin.py, docs/research/k8s-306-s1.md, 2026-10-21): identify above
# runs with the regime-clipped series MIN(X, theta x Y) as one more measured input where the data show a
# limit, and every term that reads it is written back as MIN(a x X, a theta x Y).
from . import capmin as _capmin  # noqa: E402

_identify_linear = identify


def identify(stocks: list[dict], run: dict, opts: dict | None = None, *args, **kw) -> dict:  # noqa: F811
    return _capmin.wrap(_identify_linear, stocks, run, opts, *args, **kw)
