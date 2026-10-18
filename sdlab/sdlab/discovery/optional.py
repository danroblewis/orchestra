"""Optional packages a few research strategies need (the `research` extra in pyproject.toml).

    from ..optional import require
    cma = require("cma")

A strategy that needs one imports it only when it runs, through require(), so every other strategy
(and the page) works without them; a missing one raises MissingExtra, which the bench and the ladder
report as skipped.
"""

from __future__ import annotations

import importlib

HINT = "uv sync --extra research"


class MissingExtra(ImportError):
    """An optional package a strategy needs is not installed."""


def require(name: str):
    """The module `name`, or MissingExtra saying how to install it."""
    try:
        return importlib.import_module(name)
    except ImportError as e:
        raise MissingExtra(f"this strategy needs the optional package `{name}`: run `{HINT}`") from e
