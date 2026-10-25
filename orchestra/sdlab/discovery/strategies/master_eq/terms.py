"""The candidate terms of a master-equation model of counted levels.

A term is one way things can change in a step: a rate (a number theta times a base: a level, an
input, the constant 1, or a product of two levels) and what each unit of it does to the stocks (its
effect vector e). The kinds:

  move     i -> j    base x_i, e = -1 on i, +1 on j  (a unit leaves i and arrives in j)
  drain    i -> out  base x_i, e = -1 on i
  input    u -> j    base u,   e = +1 on j          (arrivals at a share of a measured input)
  const    -> j      base 1,   e = +1 on j
  link     i => j    base x_i, e = +1 on j          (j gains in proportion to i, i loses nothing)
  bind     a + b -> c  base x_a x_b, e = -1 on a, -1 on b, +1 on c (c may be outside)
  catal    a -> c by b base x_a x_b, e = -1 on a, +1 on c          (b is not used up)

Moves, drains and binds take units out of their source: within a step, the units of one source
region split among them (a multinomial; fit.py's noise). Links, inputs and constants arrive as
independent counts (Poisson).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


@dataclass(frozen=True)
class Term:
    kind: str
    src: int | None = None          # the stock the base reads (a, for a bind)
    dst: int | None = None          # where the units go (None: outside)
    other: int | None = None        # bind / catal: the second level; input: the input's index
    era: tuple | None = None        # only in steps of these era labels (an era-split term; sorted)

    def key(self) -> tuple:
        return (self.kind, self.src, self.dst, self.other, self.era)


@dataclass
class Data:
    """x (n x S) the levels a step starts from (the previous levels plus the step's injections),
    d (n x S) each step's change, u (n x m) the step's inputs, era (n) each step's era label."""
    x: np.ndarray
    d: np.ndarray
    u: np.ndarray
    era: np.ndarray
    labels: list[str] = field(default_factory=list)

    @property
    def n(self) -> int:
        return self.x.shape[0]

    @property
    def S(self) -> int:
        return self.x.shape[1]


def base(t: Term, D: Data) -> np.ndarray:
    """The term's base per step (n)."""
    if t.kind in ("move", "drain", "link"):
        v = D.x[:, t.src]
    elif t.kind in ("bind", "catal"):
        v = D.x[:, t.src] * D.x[:, t.other]
    elif t.kind == "input":
        v = D.u[:, t.other]
    else:
        v = np.ones(D.n)
    if t.era is not None:
        v = v * np.isin(D.era, list(t.era))
    return v


def effect(t: Term, S: int) -> np.ndarray:
    e = np.zeros(S)
    if t.kind in ("move", "drain", "bind", "catal"):
        e[t.src] -= 1
    if t.kind == "bind":
        e[t.other] -= 1
    if t.dst is not None:
        e[t.dst] += 1
    return e


def takes_from(t: Term) -> int | None:
    """The source region whose units the term splits off (a multinomial), or None (independent arrivals)."""
    return t.src if t.kind in ("move", "drain", "bind", "catal") else None


def conservative(S: int, m: int, units: list[str], labels: list[str] | None = None) -> list[Term]:
    """Moves between stocks of one unit, drains, arrivals from each input and constant arrivals. With
    announced eras, the moves and drains one per era label (merged back later where BIC allows: an
    opening shut in some eras leaves the other moves bent around it if they cannot follow)."""
    eras = [(lab,) for lab in labels] if labels and len(labels) >= 2 else [None]
    out = []
    for i in range(S):
        out += [Term("drain", i, None, None, e) for e in eras]
        for j in range(S):
            if j != i and units[i] == units[j]:
                out += [Term("move", i, j, None, e) for e in eras]
        for k in range(m):
            out.append(Term("input", None, i, k))
        out.append(Term("const", None, i))
    return out


def extras(S: int, units: list[str], products: bool) -> list[Term]:
    """Links (a stock read without being drawn down, self-growth included) and, for few stocks,
    binds and catalysed moves."""
    out = [Term("link", i, j) for i in range(S) for j in range(S)]
    if products:
        for a in range(S):
            for b in range(a + 1, S):
                if units[a] != units[b]:
                    continue
                for c in [None] + [c for c in range(S) if c not in (a, b) and units[c] == units[a]]:
                    out.append(Term("bind", a, c, b))
                    out.append(Term("catal", a, c, b))
                    out.append(Term("catal", b, c, a))
    return out


def outside_sides(t: Term) -> list[tuple[int, str, str]]:
    """Where the term meets the outside, as the scorer reads a flow's ends (boundary.ends): (stock,
    side, kind), kind "measured" for an input's arrivals, else "estimate"; [] for a move (a bind's or
    a catalysed move's second stock is a co-flow or an effect, not an end)."""
    if t.kind == "input":
        return [(t.dst, "in", "measured")]
    if t.kind in ("const", "link"):
        return [(t.dst, "in", "estimate")]
    if t.kind in ("drain", "bind", "catal") and t.dst is None:
        return [(t.src, "out", "estimate")]
    return []


def inside(terms: list[Term], b, ids: list[str]) -> list[Term]:
    """The terms a declared boundary allows (boundary.Boundary b): an outside end only on a declared
    stock and side, of a declared kind. With nothing declared, every term."""
    return [t for t in terms if all(b.may(ids[s], side, kind) for s, side, kind in outside_sides(t))]
