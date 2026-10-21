"""master_eq: per-region transition probabilities fitted to counted levels (docs/research/master_eq.md)."""

from __future__ import annotations

from .run import identify as _identify
__all__ = ["identify"]


def identify(stocks: list[dict], run: dict, opts: dict | None = None) -> dict:
    """The answer above with its numbers refitted by instrumental variables where the levels carry
    measurement error (eiv.py), then kept inside the announced boundary (boundary.py: the guard and
    the moves where one is declared, each outside flow priced as a boundary claim where none is; the
    search itself is inside it: the main line's rows and ties, the master equation's term pool)."""
    from . import boundary
    from .eiv import apply

    return boundary.apply(apply(_identify(stocks, run, dict(opts or {})), stocks, run, opts), stocks, run, opts)
