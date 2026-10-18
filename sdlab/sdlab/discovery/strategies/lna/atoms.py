"""Flow atoms: the smallest flows a model is made of, each with one number.

    in      outside -> s              theta (a constant, over a piece of steps)
    out     s -> outside              theta x s
    move    a -> b                    theta x a
    link    outside -> b              theta x a   (nothing leaves a)
    grow    outside -> a              theta x a   (a stock that grows with itself: births)
    drain   c -> outside              theta x a   (c drains faster when a is high)
    a move may carry `uses` [(c, per)]: each unit moved also uses up per of c (a co-flow)

An atom's number may hold in one era only (`era`), and an inflow over a span of steps (`span`).
"""

from __future__ import annotations

from dataclasses import dataclass, replace

import numpy as np


@dataclass(frozen=True)
class Atom:
    kind: str
    src: int | None = None
    dst: int | None = None
    driver: int | None = None
    uses: tuple = ()                 # ((stock index, per), ...)
    era: int | None = None           # index into the configurations, or None: every step
    span: tuple | None = None        # (a, b): steps a..b-1 (an inflow piece)

    def key(self) -> tuple:
        """The atom without its era or span (one flow of the model)."""
        return (self.kind, self.src, self.dst, self.driver, self.uses)

    def with_(self, **kw) -> "Atom":
        return replace(self, **kw)


def stoich(atoms: list[Atom], S: int) -> np.ndarray:
    V = np.zeros((S, len(atoms)))
    for f, a in enumerate(atoms):
        if a.src is not None:
            V[a.src, f] -= 1
        if a.dst is not None:
            V[a.dst, f] += 1
        for c, per in a.uses:
            V[c, f] -= per
    return V


def features(atoms: list[Atom], prev: np.ndarray, cfg: np.ndarray | None) -> np.ndarray:
    S, T = prev.shape
    Z = np.empty((len(atoms), T))
    for f, a in enumerate(atoms):
        z = np.ones(T) if a.driver is None else np.maximum(prev[a.driver], 0.0)
        if a.era is not None and cfg is not None:
            z = np.where(cfg == a.era, z, 0.0)
        if a.span is not None:
            m = np.zeros(T)
            m[a.span[0]:a.span[1]] = 1.0
            z = z * m
        Z[f] = z
    return Z


def superset(S: int, unit: list[str], final: set[int], group: list, allow_links: bool = True) -> list[Atom]:
    """Every atom between the stocks the page allows (same unit for moves; groups as the matrix
    reads them: a stock affects another only in its own group, or when either has none)."""
    def may(j, s):
        return j == s or not group[j] or not group[s] or group[j] == group[s]

    out = []
    for s in range(S):
        out.append(Atom("in", dst=s))
        if s not in final:
            out.append(Atom("out", src=s, driver=s))
        out.append(Atom("grow", dst=s, driver=s))
    for a in range(S):
        for b in range(S):
            if a == b or not may(a, b):
                continue
            if unit[a] == unit[b] and a not in final:
                out.append(Atom("move", src=a, dst=b, driver=a))
            if allow_links:
                out.append(Atom("link", dst=b, driver=a))
            if b not in final:
                out.append(Atom("drain", src=b, driver=a))
    return out
