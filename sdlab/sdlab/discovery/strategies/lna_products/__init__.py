"""lna_products: lna with product columns, so a move can be scaled by a linear effect of a third
stock (rate k x a x c / mean(c)), chosen by the same counting-noise likelihood and BIC as every
other flow.

PySINDy's verdict (docs/research/pysindy.md) was "reject as a strategy; carry the product terms
forward", and effect_hats / symbolic fit effect curves by least squares, which on the ladder's noisy
runs of the linear effect (017) read the effect as links and drains. Here the product terms sit in
lna's likelihood, where the move's draw leaving a and arriving in b is what tells a move scaled by c
from a drain of a and a link into b. A stage on lna's hooks (run.py): lna's data, search, budget
and fallbacks are lna's own. Noise-free runs, and runs with fewer than three stocks or more than
lna's scratch size, are lna's. lna's guard (the matrix's model is kept when lna's is judged much
worse) is applied to the result and to lna's own reading.
"""

from __future__ import annotations

from ._vendored.lna import boundary
from ._vendored import lna
from ._vendored.lna_levels import own_reading_guard
from .run import stage


def _identify(stocks: list[dict], run: dict, opts: dict | None = None) -> dict:
    opts = dict(opts or {})
    state: dict = {}
    r = lna.identify(stocks, run, opts, hooks=stage(state))
    if not state.get("products"):
        return r                          # no product kept: lna's own reading, under lna's guard
    r = own_reading_guard(r, state, stocks, run, opts)
    if r.get("method") == "lna":
        r["products"], r["product_gain"] = state["products"], state.get("product_gain")
    return r


def identify(stocks: list[dict], run: dict, opts: dict | None = None) -> dict:
    """The answer above with its numbers refitted by instrumental variables where the levels carry
    measurement error (eiv.py), then kept inside the announced boundary (the lna copy's boundary.py,
    docs/research/declared-boundary.md: the guard and paired moves where one is declared, each outside
    flow priced as a boundary claim where none is)."""
    from .eiv import apply

    r = apply(_identify(stocks, run, dict(opts or {})), stocks, run, opts)
    return boundary.apply(r, stocks, run, opts, searched=r.get("method") == "lna")   # lna's own reading: its search tried the moves and priced the claims


# A capacity limit offered to the fit (capmin.py, docs/research/k8s-306-s1.md, 2026-10-21): identify above
# runs with the regime-clipped series MIN(X, theta x Y) as one more measured input where the data show a
# limit, and every term that reads it is written back as MIN(a x X, a theta x Y).
from . import capmin as _capmin  # noqa: E402

_identify_linear = identify


def identify(stocks: list[dict], run: dict, opts: dict | None = None, *args, **kw) -> dict:  # noqa: F811
    """(2026-10-21, k8s-307, docs/research/k8s-307-c1.md) Between the fit and the MIN written back, where the
    levels carry measurement error, the numbers are refitted and the structure revised on the output error
    and judged on a Kalman likelihood (oefit.py, a copy of combined2's: the model run through the whole
    record against the measured levels)."""
    from . import oefit

    o, cap = _capmin.offer(stocks, run, opts)
    r = oefit.refit(_identify_linear(stocks, run, o, *args, **kw), stocks, run, o, cap)
    return _capmin.restore(r, cap)
