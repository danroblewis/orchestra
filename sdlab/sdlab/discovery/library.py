"""The candidate terms of a stock's change in a step (a SINDy library shaped by system dynamics).

A term is a tuple of stock indices: (j,) is the level of j, (i, j) the product of two levels. A
product A x C in a flow out of A is that flow sped up or slowed down by C (a linear effect of C); in
another stock's row it is a co-flow or a link that follows both. An era term (j, "@", c) is the
level of j while announced configuration c holds (its number is added to the shared one there).
The levels and products come from PySINDy's polynomial library.
"""

from __future__ import annotations

import numpy as np
import pysindy as ps

Term = tuple


def factors(term: Term) -> tuple[int, ...]:
    return term[: term.index("@")] if "@" in term else term


def era_of(term: Term) -> int | None:
    return term[term.index("@") + 1] if "@" in term else None


def build(prev: np.ndarray, products: bool, cfg: np.ndarray | None = None, n_cfg: int = 1) -> tuple[list[Term], np.ndarray]:
    """All terms over the measured levels prev (stocks x steps) and their values (terms x steps).
    Products only between stocks whose level moves (a constant level adds nothing to its partner)."""
    S = prev.shape[0]
    lib = ps.PolynomialLibrary(degree=2 if products else 1, include_bias=False).fit(prev.T)
    moves = [float(prev[j].std()) > 1e-9 * (abs(float(prev[j].mean())) + 1) for j in range(S)]
    terms: list[Term] = []
    keep = []
    for q, pw in enumerate(lib.powers_):
        t = tuple(j for j in range(S) for _ in range(int(pw[j])))
        if len(t) == 1 or all(moves[j] for j in t):
            terms.append(t)
            keep.append(q)
    vals = [v for v in np.asarray(lib.transform(prev.T)).T[keep]]
    if cfg is not None and n_cfg > 1:
        for j in range(S):
            for c in range(1, n_cfg):
                terms.append((j, "@", c))
                vals.append(np.where(cfg == c, prev[j], 0.0))
    return terms, np.array(vals)
