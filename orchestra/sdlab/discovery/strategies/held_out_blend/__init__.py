"""Experiment "held-out judge", combined: the main line's in-sample judge nudged by the held-out
error (10 blocks, horizons 20 and 100; score = log in-sample + 0.1 x log held-out). See held_out.py."""

from __future__ import annotations

from ._vendored.held_out import identify as _identify


def identify(stocks: list[dict], run: dict, opts: dict | None = None) -> dict:
    return _identify(stocks, run, {"folds": 10, "horizons": (20, 100), "blend": 0.1, **(opts or {})})
