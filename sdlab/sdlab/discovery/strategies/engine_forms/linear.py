"""Writing a stock's linear exchange with the outside as flows (engine_forms).

A fit gives the stock's change as c + sum k_j z_j (z_j a stock's level or an input). SD Lab's
found flows are floored at 0, so the exchange is cut into an inflow (the positive numbers) and a
drain (the negative ones). When either part would go below 0 on the run's states (an input that
changes sign, a level read below 0), the same constant s is added to both, enough to keep both
above 0: the stock's change is unchanged and neither flow is ever floored (the one-way form of a
two-way flow). A stock that itself goes below 0 (a signed stock) gets one two-way flow instead,
since a found model's levels are floored at 0 anyway (sdlab/discovery/simulate.py) and the shift
would not help it.
"""

from __future__ import annotations

import numpy as np

from .steps import Steps

ONE = "1"


def _rate(c: float, terms: dict[str, float]) -> dict:
    terms = {z: k for z, k in terms.items() if k != 0}
    if not terms:
        return {"form": "constant", "value": float(c)}
    return {"form": "linear", "c": float(c), "terms": [{"stock": z, "k": float(k)} for z, k in terms.items()]}


def _flow(src, dst, rate: dict, **extra) -> dict:
    return {"from": src, "to": dst, "ratio": 1, "rate": rate, **extra, "engine_forms": True}


def parts(coef: dict[str, float], st: Steps) -> tuple[float, dict, float, dict]:
    """(inflow constant, inflow terms, drain constant, drain terms) of c + sum k_j z_j, the drain's
    numbers positive."""
    c = coef.get(ONE, 0.0)
    cin, cout = max(c, 0.0), max(-c, 0.0)
    tin = {z: k for z, k in coef.items() if z != ONE and k > 0}
    tout = {z: -k for z, k in coef.items() if z != ONE and k < 0}
    return cin, tin, cout, tout


def needs_shift(coef: dict[str, float], st: Steps) -> float:
    """How far below 0 the plain inflow or drain goes on the run's states (0: neither does)."""
    cin, tin, cout, tout = parts(coef, st)
    a = cin + sum(k * st.series(z) for z, k in tin.items())
    b = cout + sum(k * st.series(z) for z, k in tout.items())
    low = min(float(np.min(a)) if np.ndim(a) else float(a), float(np.min(b)) if np.ndim(b) else float(b))
    scale = float(np.sqrt(np.mean(np.asarray(a) ** 2 + np.asarray(b) ** 2))) + 1e-12
    return max(0.0, -low) if -low > 1e-3 * scale else 0.0


def nice_up(s: float) -> float:
    """s rounded up to two significant figures."""
    if s <= 0:
        return 0.0
    e = 10 ** (np.floor(np.log10(s)) - 1)
    return float(np.ceil(s / e) * e)


def write(x: str, coef: dict[str, float], st: Steps, signed: bool) -> list[dict]:
    """The flows of stock x's exchange with the outside, c + sum k_j z_j (see the module)."""
    coef = {z: float(k) for z, k in coef.items() if abs(k) > 0}
    if not coef:
        return []
    if signed:
        terms = {z: k for z, k in coef.items() if z != ONE}
        return [_flow(None, x, _rate(coef.get(ONE, 0.0), terms), two_way=True, bothWays=True)]
    cin, tin, cout, tout = parts(coef, st)
    s = nice_up(1.05 * needs_shift(coef, st))
    out = []
    if cin + s > 0 or tin:
        out.append(_flow(None, x, _rate(cin + s, tin)))
    if cout + s > 0 or tout:
        out.append(_flow(x, None, _rate(cout + s, tout)))
    return out
