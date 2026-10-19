"""lna_loops: lna, with feedback the data cannot rule out kept rather than priced away.

lna drops a flow when keeping it does not pay the BIC price (log T / 2 per number). A link that
closes a loop (B's level drives A's inflow while A feeds B) is often a small number with a standard
error larger than itself on a few hundred noisy steps: BIC drops it, and the model is the loop's
equivalent without it. Here, after lna's search, every loop-closing link (outside -> a reading b,
where a moves into b) that is not in the model is offered back, fitted by the same likelihood, and
kept when its likelihood gain is above `price` (default 0: kept whenever its maximum-likelihood
number is above zero). This is the "Bayesian structure / complexity budget" idea: a prior that
favours closing a loop over BIC's Occam price, for one kind of term only.

The cost is complexity (an extra flow where the truth has none, at a number within its standard
error of zero); docs/research/revisit.md measures both. Verdict there: do not adopt. A stage on
lna's hooks (run.py): lna's data, search, budget, fallbacks and guard are lna's own.
"""

from __future__ import annotations

from .. import lna
from .run import PRICE, close_loops, stage  # noqa: F401  (close_loops: the stage's step, for tests)


def identify(stocks: list[dict], run: dict, opts: dict | None = None) -> dict:
    opts = dict(opts or {})
    price = float(opts.pop("loop_price", PRICE))
    state: dict = {}
    r = lna.identify(stocks, run, opts, hooks=stage(state, price))
    if r.get("method") == "lna":
        r["loops_closed"] = state.get("loops_closed", [])
    return r
