"""The model class of z3robust: a copy of z3exact's core.py at commit 45bfaac (sdlab branch; the file last
changed at 3de470a), only its class (Column, Term, Problem, prepare, the boundary rule, the exact data and
the rounding tolerance), without z3exact's exact search. Strategies are isolated (CLAUDE.md rule 11):
changing z3exact never changes this copy.

The class (z3exact's, docs/research/z3.md): each measured stock's one-step change is a sum of terms, each a
number times a column (a measured level, a measured input, or a constant; per announced era each its own
column). A term is a move between two stocks of one unit (one number, two rows; "ends": it reads one of
its two stocks) or an outside term on one stock, allowed only where the declared boundary allows it
("kinds": a declared side whose kinds hold the column's kind; "sides": any declared side). An offered
capacity series MIN(X, theta Y) (capmin.py) reads like a level, only in the rows of the flow it limits.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from fractions import Fraction

import numpy as np

FLOAT_SLACK = 1e-9            # of the largest level: the engine's float arithmetic
NORM_MARGIN = 2.0             # the tolerance allows twice the least-squares row's sum of |numbers| on levels
INPUT_DIGITS = 9              # measured inputs are read to this many significant digits (their rounding joins the tolerance)
MAX_TERMS = 600               # a class with more candidate terms is not searched (its LPs alone take minutes)
MAX_DECIMALS = 9              # more decimals than this: raw floats (h from FLOAT_SLACK alone)


@dataclass
class Column:
    name: str                 # a stock id, an input name, or "1" (a constant)
    kind: str                 # "stock", "input", "const"
    era: int | None = None    # with announced eras: the era it holds in (0 elsewhere), each era its own number
    unit: str | None = None


@dataclass
class Term:
    kind: str                 # "move" or "outside"
    col: int
    a: str                    # move: the first stock of the pair (ids order); outside: the stock
    b: str | None = None      # move: the second stock
    sides: tuple = ()         # outside: the sides it may be on ("in", "out")

    def key(self, cols: list[Column]) -> str:
        c = cols[self.col]
        what = c.name + ("" if c.era is None else f"@era{c.era}")
        return f"move {self.a}~{self.b} [{what}]" if self.kind == "move" else f"outside {self.a} [{what}]"


@dataclass
class Problem:
    ids: list[str]
    cols: list[Column]
    terms: list[Term]
    X: list[list[Fraction]]   # columns x steps (exact)
    dY: list[list[Fraction]]  # stocks x steps (exact)
    h: Fraction               # half a unit of the data's last decimal (0 for raw floats)
    slack: Fraction
    decimals: int | None
    eps: list = field(default_factory=list)   # per stock: the fit's tolerance on every step
    era_starts: list = field(default_factory=list)
    declared: bool = False
    note: str = ""

    @property
    def steps(self) -> int:
        return len(self.dY[0]) if self.dY else 0


def _decimals(values) -> int | None:
    """The most decimals any value has (None: more than MAX_DECIMALS, raw floats)."""
    most = 0
    for v in values:
        if v is None or math.isnan(v):
            continue
        for d in range(MAX_DECIMALS + 1):
            if round(v, d) == v:
                most = max(most, d)
                break
        else:
            return None
    return most


def _frac(v: float, decimals: int | None) -> Fraction:
    return Fraction(repr(round(v, decimals))) if decimals is not None else Fraction(v)


BOUNDARY_RULES = ("kinds", "sides")


def _kind_sides(boundary: dict | None, declared: bool, stock: str, kind: str, rule: str = "kinds") -> tuple:
    """The sides an outside term reading a column of this kind may be on. "kinds": a declared side whose
    kinds hold the column's ("measured" for an input, "estimate" for a constant or a level), as the
    case writes it and matrix's boundary.py enforces it; "sides": any declared side, whatever the
    column, as the scorer judges it (score.py, "The boundary": stock and side only; some cases declare
    "estimate" for a flow that reads an input, e.g. 204's valve, 106's hiring)."""
    if not declared:
        return ("in", "out")
    e = (boundary or {}).get(stock) or {}
    if rule == "sides":
        return tuple(side for side in ("in", "out") if e.get(side))
    want = {"measured", "input"} if kind == "input" else {"estimate"}      # (2026-10-21) an "input" side reads its input
    return tuple(side for side in ("in", "out") if want & set(e.get(side) or []))


MOVE_CLASSES = ("ends", "any")


def prepare(stocks: list[dict], run: dict, opts: dict | None = None, moves: str = "ends", boundary: str = "kinds",
            pooled: bool = False, skip=frozenset()) -> Problem:
    """The class and the exact data for what a page gets (stocks, run, opts as runner.discover builds them).
    moves: "ends" (a move's rate reads the level of one of its two stocks: SD's usual drain or transfer)
    or "any" (a move's rate may read any column: every linear system's decompositions)."""
    if moves not in MOVE_CLASSES:
        raise ValueError(f"moves: one of {MOVE_CLASSES}")
    if boundary not in BOUNDARY_RULES:
        raise ValueError(f"boundary: one of {BOUNDARY_RULES}")
    opts = opts or {}
    # (z3robust, k8s-308 port) skip: stocks whose changes a rule outside the class explains (a whole-unit
    # controller, post/quantized.py): their rows and every term on them are left out (milp takes them out of its
    # program the same way); their levels stay columns the other rows may read
    every = [s["id"] for s in stocks]
    ids = [i for i in every if i not in skip]
    units = {s["id"]: s.get("unit") for s in stocks}
    t = list(run["t"])
    raw = {i: [float("nan") if v is None else float(v) for v in run["levels"].get(i, [])] for i in every}
    decimals = _decimals(v for i in every for v in raw[i])
    inputs = {k: [float(x) for x in v] for k, v in (opts.get("inputs") or {}).items() if k not in every}
    eras = opts.get("eras") or []
    starts = sorted(float(e["start"]) for e in eras)[1:] if len(eras) > 1 else []
    era_of = lambda time_: sum(1 for s in starts if time_ >= s)
    inj = {}
    for j in opts.get("injections") or []:
        if j.get("stock") in every and j["t"] in t:
            inj[(j["stock"], t.index(j["t"]))] = inj.get((j["stock"], t.index(j["t"])), Fraction(0)) + Fraction(float(j["amount"]))
    cols = []
    for e in (range(len(starts) + 1) if starts else [None]):     # announced eras: every number may change at each
        cols += [Column(i, "stock", era=e, unit=units[i]) for i in every] + [Column(k, "input", era=e) for k in sorted(inputs)]
        cols.append(Column("1", "const", era=e))
    if starts and pooled:     # (z3robust) with eras, also every column over the whole run (era None): a number that
        # does not change at an era is one term, and an era's change is a term of its own on top of it
        cols += [Column(i, "stock", era=None, unit=units[i]) for i in every] + [Column(k, "input", era=None) for k in sorted(inputs)]
        cols.append(Column("1", "const", era=None))
    keep = [i for i in range(len(t) - 1)
            if all(not math.isnan(raw[s][i]) and not math.isnan(raw[s][i + 1]) for s in every)
            and all(i + 1 < len(v) and not math.isnan(v[i + 1]) for v in inputs.values())]
    # (z3robust) reported with gaps (samples missing from t): a change over several steps is not a one-step
    # change, so only the steps of the commonest spacing are kept
    if len(t) > 2:
        dts = np.round(np.diff(np.asarray(t, dtype=float)), 9)
        vals, counts = np.unique(dts, return_counts=True)
        step = vals[int(np.argmax(counts))]
        keep = [i for i in keep if dts[i] == step]
    L = {s: [_frac(v, decimals) if not math.isnan(v) else Fraction(0) for v in raw[s]] for s in every}
    in_dec = {k: max(0, INPUT_DIGITS - 1 - int(np.floor(np.log10(max(1e-12, max(abs(x) for x in v if not math.isnan(x)) if any(not math.isnan(x) for x in v) else 1.0)))))
              for k, v in inputs.items()}
    X: list[list[Fraction]] = [[] for _ in cols]
    dY: list[list[Fraction]] = [[] for _ in ids]
    for i in keep:
        era = era_of(t[i + 1])
        for c, col in enumerate(cols):
            if col.era is not None and col.era != era:
                X[c].append(Fraction(0))
            elif col.kind == "stock":
                X[c].append(L[col.name][i] + inj.get((col.name, i + 1), Fraction(0)))
            elif col.kind == "input":
                X[c].append(_frac(inputs[col.name][i + 1], in_dec[col.name]))
            else:
                X[c].append(Fraction(1))
        for r, s in enumerate(ids):
            dY[r].append(L[s][i + 1] - L[s][i] - inj.get((s, i + 1), Fraction(0)))
    declared = bool(run.get("boundary_declared"))
    terms: list[Term] = []
    # (strategy copy only, 2026-10-21; docs/research/k8s-306-r3-six.md) an offered capacity series m = MIN(X, theta Y)
    # (capmin.py) is X's level clipped to the capacity: in the "ends" class a move X -> R may read it as it reads
    # X, and only the rows capmin allows (X and its receiver, or X alone for an outflow) read it at all; an
    # outside term reading it is judged as one reading a level, not a measured input
    from . import capmin as _cm
    lim = {k: v for k, v in ((k, _cm.readers(k, opts)) for k in inputs) if v is not None}
    # (z3robust, port-z3robust 2026-10-22) a final stock (a counter: a running total) is never a reader: its level
    # is a trend that runs away off the run (structures 824f241, fix ledger type 11), and on noise-free data its
    # columns' huge t values crowded the true terms out of the screened candidates (k8s-310: queue -> retries)
    counters = {s["id"] for s in stocks if s.get("final")}
    reader = {c: not (col.kind == "stock" and col.name in counters) for c, col in enumerate(cols)}
    for a_i, a in enumerate(ids):
        for b in ids[a_i + 1:]:
            if units[a] == units[b]:
                terms += [Term("move", c, a, b) for c, col in enumerate(cols)
                          if reader[c] and (col.name not in lim or set(lim[col.name]) == {a, b})
                          and (moves == "any" or col.name in (a, b) and col.kind == "stock" or set(lim.get(col.name) or ()) == {a, b})]
    for s in ids:
        for c, col in enumerate(cols):
            if not reader[c] or col.name in lim and tuple(lim[col.name]) != (s,):
                continue
            sides = _kind_sides(run.get("boundary"), declared, s, "stock" if col.name in lim else col.kind, boundary)
            if sides:
                terms.append(Term("outside", c, s, sides=sides))
    top = max([abs(v) for s in every for v in raw[s] if not math.isnan(v)] or [1.0])
    h = Fraction(1, 2 * 10 ** decimals) if decimals is not None else Fraction(0)
    slack = Fraction(FLOAT_SLACK) * Fraction(max(1.0, top))
    h_in = {k: Fraction(1, 2 * 10 ** d) for k, d in in_dec.items()}
    eps = tolerances(X, dY, cols, h, slack, h_in)
    return Problem(ids, cols, terms, X, dY, h, slack, decimals, eps,
                   [float(e["start"]) for e in sorted(eras, key=lambda e: float(e["start"]))] if eras else [],
                   declared, "" if len(keep) == len(t) - 1 else f"{len(t) - 1 - len(keep)} steps left out (missing values)")


def tolerances(X: list, dY: list, cols: list[Column], h: Fraction, slack: Fraction, h_in: dict | None = None) -> list[Fraction]:
    """Per stock, the tolerance on every step's residual: 2h (its two rounded levels) + h x NORM_MARGIN x
    sum_j |A_sj| over the stock columns (the rounding of the levels the row reads), with A_s the
    least-squares net numbers of the stock's row on every column, + the float slack. It holds for the
    true row whenever sum_j |A_true,sj| <= NORM_MARGIN x the least-squares one (on noise-free data the
    least-squares row is the true row up to the rounding, unless columns are collinear). Measured inputs are
read to INPUT_DIGITS significant digits (small rationals keep Z3's exact pivoting fast); h_in (half a unit of
an input's last digit) x NORM_MARGIN x |A_s,input| joins the tolerance."""
    if not dY or not dY[0]:
        return [2 * h + slack for _ in dY]
    M = np.array([[float(v) for v in row] for row in X]).T
    stock_cols = [c for c, col in enumerate(cols) if col.kind == "stock"]
    out = []
    for row in dY:
        a, *_ = np.linalg.lstsq(M, np.array([float(v) for v in row]), rcond=None)
        norm = float(np.abs(a[stock_cols]).sum()) if stock_cols else 0.0
        inp = sum(float(h_in[col.name]) * NORM_MARGIN * abs(float(a[c])) for c, col in enumerate(cols) if col.kind == "input" and h_in)
        out.append(2 * h + h * Fraction(max(1.0, NORM_MARGIN * norm)).limit_denominator(10 ** 6)
                   + Fraction(inp).limit_denominator(10 ** 12) + slack)
    return out


def _contrib(p: Problem, term: Term, stock: str) -> int:
    """How a term's number enters the row of a stock: +1, -1 or 0 (a move: a -> b when positive)."""
    if term.kind == "outside":
        return 1 if term.a == stock else 0
    return -1 if term.a == stock else 1 if term.b == stock else 0


def _floats(p: Problem):
    """The data as floats (steps x columns, stocks x steps), computed once per problem."""
    got = getattr(p, "_float_cache", None)
    if got is None:
        got = (np.array([[float(v) for v in row] for row in p.X]).T.reshape(p.steps, len(p.cols)),
               np.array([[float(v) for v in row] for row in p.dY]).reshape(len(p.ids), p.steps))
        p._float_cache = got
    return got
