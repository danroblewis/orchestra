"""Ablation of `gated`: the gate without its "high" test (runs from 5 x the observed maxima), which
judges behaviour far outside anything the data visit (docs/research/behaviour-consistency.md)."""

from __future__ import annotations

from ._vendored.gated import identify as _gated


def identify(stocks: list[dict], run: dict, opts: dict | None = None) -> dict:
    return _gated(stocks, run, {**(opts or {}), "gate": {"tests": ("observed", "empty")}})
