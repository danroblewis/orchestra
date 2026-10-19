# Vendored for combined2 from sdlab/discovery/strategies/archetypes/terms.py at commit 3c3e009 (HEAD 05ae898); imports
# rewritten to these copies, otherwise unchanged (CLAUDE.md invariant 11). Re-vendor rather than edit.
"""The term library: every flow a number theta >= 0 times a monomial of the measured levels (degree
0, 1 or 2), with a route (from, to; None is outside). These are the classic SD forms:

- in(i, ())       a constant outside inflow into i
- in(i, (i,))     growth: i's own births, theta x i
- in(i, (j,))     a link: outside -> i reading another stock j
- in(i, (i, j))   a gain proportional to i and to j (a predator fed by its prey; j = i: positive crowding)
- out(i, (i,))    a drain proportional to i
- out(i, (i, j))  a loss proportional to i and to j (crowding by j; j = i: logistic crowding)
- move(j -> i, (j,))     a move at a rate per unit of j (a transition, a delay's outflow)
- move(j -> i, (j, i))   a move proportional to j and i (infection S x I, imitation N x A in Bass)

A signed generalised Lotka-Volterra row (X_i (r_i + sum_j a_ij X_j)) is the in/out pair of each
monomial; the library holds both, so the sign is chosen by which one the search keeps.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class Term:
    src: int | None          # the stock it leaves (None: outside)
    dst: int | None          # the stock it enters (None: outside)
    mono: tuple              # stock indices multiplied (empty: a constant)

    @property
    def kind(self) -> str:
        if self.src is None:
            return "in"
        return "out" if self.dst is None else "move"

    def name(self, ids: list[str]) -> str:
        a = "outside" if self.src is None else ids[self.src]
        b = "outside" if self.dst is None else ids[self.dst]
        m = " x ".join(ids[i] for i in self.mono) or "1"
        return f"{a} -> {b} [{m}]"


def library(m: int, moves: bool = True, links: bool = True) -> list[Term]:
    out: list[Term] = []
    for i in range(m):
        out.append(Term(None, i, ()))
        out.append(Term(None, i, (i,)))
        out.append(Term(i, None, (i,)))
        for j in range(m):
            out.append(Term(None, i, tuple(sorted((i, j)))))
            out.append(Term(i, None, tuple(sorted((i, j)))))
            if j != i and links:
                out.append(Term(None, i, (j,)))
    if moves:
        for j in range(m):
            for i in range(m):
                if i != j:
                    out.append(Term(j, i, (j,)))
                    out.append(Term(j, i, tuple(sorted((i, j)))))
    return list(dict.fromkeys(out))


def arrays(terms: list[Term]) -> tuple[np.ndarray, ...]:
    """(src, dst, a, b) as int arrays, -1 for outside / no factor."""
    src = np.array([-1 if t.src is None else t.src for t in terms], dtype=np.int64)
    dst = np.array([-1 if t.dst is None else t.dst for t in terms], dtype=np.int64)
    a = np.array([t.mono[0] if len(t.mono) > 0 else -1 for t in terms], dtype=np.int64)
    b = np.array([t.mono[1] if len(t.mono) > 1 else -1 for t in terms], dtype=np.int64)
    return src, dst, a, b


def features(terms: list[Term], X: np.ndarray) -> np.ndarray:
    """Each term's monomial on levels X (stocks x states): terms x states."""
    out = np.ones((len(terms), X.shape[1]))
    for k, t in enumerate(terms):
        for i in t.mono:
            out[k] *= X[i]
    return out


def effect_on(terms: list[Term], m: int) -> np.ndarray:
    """stocks x terms: +1 where a term enters a stock, -1 where it leaves it."""
    E = np.zeros((m, len(terms)))
    for k, t in enumerate(terms):
        if t.src is not None:
            E[t.src, k] -= 1
        if t.dst is not None:
            E[t.dst, k] += 1
    return E
