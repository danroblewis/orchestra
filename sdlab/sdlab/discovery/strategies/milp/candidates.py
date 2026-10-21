"""The candidate flows, from the stocks and the announced boundary (the same rules for every case).

- a move i -> j between measured stocks (i not final: nothing leaves a counter), at a rate
  proportional to i;
- an outside outflow from i (where the boundary declares one; with no boundary declared, from any
  stock that is not final, as a boundary claim), proportional to i;
- an outside inflow into j (where declared; undeclared: into any stock, as a claim): a "measured" side
  reads the measured inputs only; an "estimate" side reads a constant, the inputs, and the other
  measured stocks' levels (links);
- a capacity-limited flow from i (a move, or an outside outflow where one is allowed) at
  MIN(a x i, b x Y), Y another measured stock (not a counter: a final stock only records) or an input:
  the demand of the source, or what Y can take.

Every number is non-negative (rates are non-negative and every reader is), so nothing is ever a
negative flow; conservation holds by construction (a move's amount leaves i and enters j).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .program import Column
from .steps import Steps

GRID = 8            # thresholds a MIN flow's program chooses among (quantiles of source / capacity)
PIECES = 100         # an estimated inflow's constant may step at one of about this many evenly spaced change points
                     # (found by the final local search on every step, refined to the step; not in the program,
                     # whose sample of steps sees too little of each stretch)
PIECE_MIN = 5        # ... at least this many steps apart and from the ends
PIECE_PRICE = 2.0    # a step pays this many log T (its size and its place)
NEG_PRICE = 0.5      # a negative term (a goal gap) pays this many log T beyond its number: a drain or a move reads the same
ZOOM = 12            # thresholds around a MIN's refitted one when the program is solved again


@dataclass
class Term:
    src: str | None          # None: outside
    dst: str | None
    reader: str | None       # a stock, an input, or None (the constant)
    ub: float                # big-M: the largest the number may be
    neg: bool = False        # read with a negative number (a goal gap's own level: c - k x level)
    pieces: bool = False     # an estimated inflow's constant, which may step at unannounced change points


@dataclass
class MinFlow:
    src: str
    dst: str | None
    cap: str                 # the capacity's reader (a stock or an input)


class Boundary:
    def __init__(self, run: dict):
        self.declared = bool(run.get("boundary_declared"))
        raw = run.get("boundary") or {}
        # (2026-10-21) an "input" side is searched as "measured"; __init__.fixed_inputs sets it at 1 x the input
        self.sides = {s: {side: {"measured" if k == "input" else k for k in e.get(side) or []} for side in ("in", "out")} for s, e in raw.items()}

    def kinds(self, stock: str, side: str, final: bool) -> set:
        if self.declared:
            return (self.sides.get(stock) or {}).get(side) or set()
        if side == "out" and final:
            return set()
        return {"estimate"}

    def claim(self) -> bool:
        """An outside flow is a boundary claim (priced) when no boundary is declared."""
        return not self.declared


def build(st: Steps, b: Boundary) -> tuple[list[Term], list[MinFlow]]:
    ids, inputs = st.ids, sorted(st.inputs)
    room = {s: float(np.max(st.dy[k] + st.L[k], initial=0.0)) for k, s in enumerate(ids)}   # most a stock can take in a step
    terms: list[Term] = []

    def mean(x: str) -> float:
        return max(1e-9, float(np.mean(np.abs(st.series(x)))))

    for i in ids:
        if i in st.final:
            continue
        for j in ids:
            if j != i:
                terms.append(Term(i, j, i, 1.0))
    for i in ids:
        if b.kinds(i, "out", i in st.final):
            terms.append(Term(i, None, i, 1.0))
    for j in ids:
        kinds = b.kinds(j, "in", j in st.final)
        if not kinds:
            continue
        cap = 4.0 * max(room[j], 1e-9)
        readers: list[str | None] = list(inputs)
        if "estimate" in kinds:
            readers = [None] + readers + [s for s in ids if s != j]
        for r in readers:
            terms.append(Term(None, j, r, cap / (1.0 if r is None else mean(r)), pieces=r is None))
        if "estimate" in kinds:                    # a goal gap: c - k x a stock's level
            terms += [Term(None, j, r, cap / mean(r), neg=True) for r in ids]
    mins: list[MinFlow] = []
    for i in ids:
        out = bool(b.kinds(i, "out", i in st.final))
        if i in st.final and not out:
            continue
        x = st.series(i)
        targets = [j for j in ids if j != i and i not in st.final] + ([None] if out else [])
        for y in [s for s in ids if s != i and s not in st.final] + inputs:      # a counter is a record, not a capacity
            yv = st.series(y)
            pos = yv[yv > 1e-12]
            if len(pos) < 2 or np.ptp(yv) <= 0:
                continue
            for j in targets:
                mins.append(MinFlow(i, j, y))
    return terms, mins


def declared_sides(st: Steps, b: Boundary) -> list[tuple]:
    """The outside flows the declared boundary gives: (None, stock) inflows and (stock, None) outflows.
    A given, not a choice (the user, 2026-10-21): they are always in the model; only their form and
    numbers are found."""
    if not b.declared:
        return []
    out = [(None, s) for s in st.ids if b.kinds(s, "in", s in st.final)]
    return out + [(s, None) for s in st.ids if b.kinds(s, "out", s in st.final)]


def piece_places(st: Steps) -> list[int]:
    """The steps an estimated inflow's constant may step at (its pieces)."""
    every = max(PIECE_MIN, st.T // PIECES)
    return list(range(every, st.T - PIECE_MIN + 1, every))


def targets(st: Steps, b: Boundary, src: str) -> list:
    """Where a flow from src may go: another measured stock (src not final), or outside where allowed."""
    out = [j for j in st.ids if j != src and src not in st.final]
    return out + ([None] if b.kinds(src, "out", src in st.final) else [])


def thresholds(st: Steps, mf: MinFlow, around: float | None = None) -> np.ndarray:
    """The thresholds theta = b / a the program may choose for a MIN flow: quantiles of src / cap over
    the steps (a theta beyond them is one regime only: a plain term), or a finer grid around one."""
    x, y = st.series(mf.src), st.series(mf.cap)
    ok = (y > 1e-12) & (x > 1e-12)
    if ok.sum() < 4:
        return np.array([])
    r = x[ok] / y[ok]
    if around is not None and around > 0:
        return around * np.exp(np.linspace(-0.25, 0.25, ZOOM))
    return np.unique(np.quantile(r, np.linspace(0.03, 0.97, GRID)))


def columns(st: Steps, terms: list[Term], mins: list[MinFlow], claim: bool, zoom: dict | None = None) -> list[Column]:
    """The program's columns: every term, and each MIN flow at each of its thresholds (zoom: a MIN flow's
    refitted theta, to choose again among a finer grid around it beside the coarse one)."""
    out = []
    eras = len(st.era_starts)
    for t in terms:
        f = -st.series(t.reader) if t.neg else st.series(t.reader)
        cl = (t.src, t.dst) if claim and (t.src is None or t.dst is None) else None
        out.append(Column(t.src, t.dst, f, t.ub, 1 + (NEG_PRICE if t.neg else 0.0), None, cl, ("neg" if t.neg else "term", t.reader)))
        if eras > 1 and not t.neg:
            base = len(out) - 1
            for e in range(1, eras):
                out.append(Column(t.src, t.dst, f * (st.era == e), t.ub, 1, None, cl, ("era", t.reader, e), signed=True, base=base))
    for mf in mins:
        x, y = st.series(mf.src), st.series(mf.cap)
        key = (mf.src, mf.dst, mf.cap)
        ths = thresholds(st, mf)
        if zoom and key in zoom:
            ths = np.unique(np.concatenate([ths, thresholds(st, mf, zoom[key])]))
        for th in ths:
            out.append(Column(mf.src, mf.dst, np.minimum(x, th * y), 1.0, 2, ("min",) + key,
                              (mf.src, None) if claim and mf.dst is None else None, ("min", mf.cap, float(th))))
    return out
