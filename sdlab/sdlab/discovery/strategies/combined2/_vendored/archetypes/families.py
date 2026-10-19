# Vendored for combined2 from sdlab/discovery/strategies/archetypes/families.py at commit 3c3e009 (HEAD ebe9a4f); imports
# rewritten to these copies, otherwise unchanged (CLAUDE.md invariant 11). Re-vendor rather than edit.
"""The archetypes as whole structures (each fitted as it is, no search inside it), for one or two
measured stocks and for every pair of stocks:

- exponential: each stock's own growth or drain (by the sign of its mean change)
- logistic: each stock's growth and crowding
- competition: logistic, and each stock crowded by the other (Lotka-Volterra competition)
- predation (both ways round): the prey's growth, crowding and loss to the predator; the predator's
  drain and its gain from the prey, with and without the predator's own crowding
- generalised Lotka-Volterra: every monomial of each stock's per-capita rate, signed by regression
- moves: a linear move, a Bass move (innovation and imitation), an SI move (imitation only), each way
- linear compartments: every stock's drain, constant inflow, and linear moves between them

A structure the search composed from the whole library is chosen from many more possibilities than
one of these, so it pays for that choice (search.search: `extra`).
"""

from __future__ import annotations

import numpy as np

from .terms import Term


def growth(i: int) -> Term:
    return Term(None, i, (i,))


def crowd(i: int, j: int) -> Term:
    return Term(i, None, tuple(sorted((i, j))))


def families(m: int, dy_mean: np.ndarray, glv: list[Term]) -> dict[str, list[Term]]:
    out: dict[str, list[Term]] = {}
    out["exponential"] = [growth(i) if dy_mean[i] >= 0 else Term(i, None, (i,)) for i in range(m)]
    out["logistic"] = [x for i in range(m) for x in (growth(i), crowd(i, i))]
    if glv:
        out["generalised Lotka-Volterra"] = list(glv)
    out["linear compartments"] = ([Term(None, i, ()) for i in range(m)] + [Term(i, None, (i,)) for i in range(m)]
                                  + [Term(j, i, (j,)) for j in range(m) for i in range(m) if i != j])
    for i in range(m):
        for j in range(i + 1, m):
            out[f"competition {i}-{j}"] = out["logistic"] + [crowd(i, j), crowd(j, i)]
            for prey, pred in ((i, j), (j, i)):
                base = [growth(prey), crowd(prey, prey), crowd(prey, pred), Term(pred, None, (pred,)), Term(None, pred, tuple(sorted((prey, pred))))]
                out[f"predation {pred}>{prey}"] = base
                out[f"predation {pred}>{prey}, crowded"] = base + [crowd(pred, pred)]
            for a, b in ((i, j), (j, i)):
                out[f"move {a}>{b}"] = [Term(a, b, (a,))]
                out[f"Bass {a}>{b}"] = [Term(a, b, (a,)), Term(a, b, tuple(sorted((a, b))))]
                out[f"SI {a}>{b}"] = [Term(a, b, tuple(sorted((a, b))))]
    seen, uniq = set(), {}
    for k, v in out.items():
        key = frozenset(v)
        if key not in seen:
            seen.add(key)
            uniq[k] = list(dict.fromkeys(v))
    return uniq
