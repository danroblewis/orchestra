"""unified: one model class, one data model, one objective (docs/research/unified-design.md).

WORK IN PROGRESS. Only the objective is built (frontend.py, engine.py, kalman.py, price.py,
objective.py) for the objective test (sdlab/ladder/objective_test.py). There is no search yet:
identify() returns the main line's model (sdlab/discovery/identify.py, the shared library) unchanged,
with a note, so its ladder rows are the main line's and say nothing about this design.
"""

from __future__ import annotations

from .earned import main_line as _main_line


def _identify(stocks, run, opts=None):
    r = _main_line(stocks, run, opts)
    wip = "unified: work in progress (no search yet); this is the main line's model"
    r["note"] = f"{wip}. {r['note']}" if r.get("note") else wip
    return r


__all__ = ["identify"]


def identify(stocks: list[dict], run: dict, opts: dict | None = None) -> dict:
    """The answer above with its numbers refitted by instrumental variables where the levels carry
    measurement error (eiv.py)."""
    from .eiv import apply

    return apply(_identify(stocks, run, dict(opts or {})), stocks, run, opts)
