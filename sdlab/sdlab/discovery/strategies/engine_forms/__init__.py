"""engine_forms: kalman_lna's model with each stock's exchange re-read in the forms the engine can
now write (docs/research/engine_forms.md).

The base is a copy of kalman_lna (as at commit 6a93270, in _kalman/; its own copies of combined,
lna and the rest inside it), so changing kalman_lna never changes this strategy (sdlab/CLAUDE.md
invariant 11). Its answer is then read again stock by stock (judge.py): x's flows to and from the
outside and the moves into it are replaced by one of the forms of forms.py where that form fits
x's one-step change clearly better for its numbers (BIC, every inflow piece counted):

- a linear exchange that runs both ways (an input that changes sign; a stock below 0), written as
  an inflow and a drain shifted by the same constant, or as one two-way flow for a signed stock;
- a drain at MIN(a x level, capacity), capacity a linear function of other stocks or inputs;
- an inflow that is a table of a stock or an input, optionally times an input (a dead zone; an
  admission gate), beside the stock's linear flows.

Where the base read the levels as noisy reports (kalman_lna's filter chosen), its answer is kept:
one-step changes of noisy levels are not the flows.
"""

from __future__ import annotations

from ._kalman import boundary
from ._kalman import identify as base
from .judge import improve
from .steps import build


def _identify(stocks: list[dict], run: dict, opts: dict | None = None) -> dict:
    opts = dict(opts or {})
    r = base(stocks, run, opts)
    if (r.get("kalman") or {}).get("reading"):
        return r          # the base read the levels as noisy reports: one-step changes of them are not the flows
    st = build(stocks, run, opts)
    if st is None:
        return r
    trace: list[str] = []
    b = boundary.Boundary(run)
    ids, inputs = [s["id"] for s in stocks], set(opts.get("inputs") or {})
    flows = improve(list(r.get("flows") or []), st, trace=trace,
                    outside=lambda fl: len(boundary.violations(fl, ids, b, inputs)))
    return {**r, "flows": flows, "engine_forms": {"trace": trace}}


def identify(stocks: list[dict], run: dict, opts: dict | None = None) -> dict:
    """The answer above with its numbers refitted by instrumental variables where the levels carry
    measurement error (eiv.py), then kept inside the announced boundary (_kalman/boundary.py: the guard
    and the moves where one is declared, each outside flow priced as a boundary claim where none is;
    the base's search and the forms pass are inside it too)."""
    from .eiv import apply

    return boundary.apply(apply(_identify(stocks, run, dict(opts or {})), stocks, run, opts), stocks, run, opts)
