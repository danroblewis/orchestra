"""master_eq: per-region transition probabilities fitted to counted levels (docs/research/master_eq.md)."""

from __future__ import annotations

from .run import identify as _identify
__all__ = ["identify"]


def identify(stocks: list[dict], run: dict, opts: dict | None = None) -> dict:
    """The answer above with its numbers refitted by instrumental variables where the levels carry
    measurement error (eiv.py)."""
    from .eiv import apply

    return apply(_identify(stocks, run, dict(opts or {})), stocks, run, opts)
