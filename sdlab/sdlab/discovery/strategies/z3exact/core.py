"""The class and the exact search of z3exact: a copy of sdlab/ladder/z3_ident.py (the harness's
identifiability instrument) as committed with this file (first copied at c291f87; the two were edited
together while docs/research/z3.md was written), without its hidden-stock test. Strategies are isolated
(CLAUDE.md rule 11): changing the harness's copy never changes this one.

Original docstring:
Identifiability proofs with Z3 (docs/research/z3.md, experiment A): on noise-free data, does exactly
one structure in a linear model class fit every one-step change within the data's own precision?

    problem = prepare(stocks, run, opts)            # what a page gets, as runner.discover passes it
    found = enumerate_structures(problem, ...)      # every irreducible structure that fits, smallest first

**The class.** Each measured stock's one-step change is a sum of terms, each a number times a column:
a measured stock's level, a measured input (aligned as the shared matrix method aligns it: the step from
t[i] to t[i+1] reads the levels at t[i] and the inputs at t[i+1]), or a constant; with announced eras,
every column is split per era (each era its own numbers, each era's term its own term). A
term is either a *move* between two stocks of the same unit (one number: what one loses the other gains;
its sign gives the direction) or an *outside* term on one stock. An outside term on stock s reading
column j is allowed only where the boundary lets it be: with a declared boundary, on a side of s whose
kinds hold the column's kind ("measured" for an input, "estimate" for a constant or a level); with none
declared, everywhere. An announced injection is added at the start of its step (as matrix.py does).

**Fitting within epsilon, exactly.** The levels are parsed as the decimals they were written as
(Fraction of their repr), the changes and inputs are exact rationals, and Z3 works over the reals
(linear real arithmetic, exact). The data are rounded to d decimals (d read from the data: the most
decimals any level has), so the true model's residual on a step of stock s is at most
2h + h * sum_j |A_sj| over the stock columns (h = half a unit of the d-th decimal; A_sj the true net
number of column j in the row of s), plus a float slack (1e-9 of the largest level). The tolerance
uses NORM_MARGIN (2) x the least-squares row's sum in place of the true one (`tolerances`), so it is a
fixed number per stock and the constraints stay linear.

**Speed** (three devices, none of which changes what fits): lazy rows (Z3 starts from no steps; a
candidate structure is checked exactly on every step, and the worst steps it misses join the search
when no numbers of that structure fit them all); a verification LP per candidate (HiGHS in floats, its
numbers then checked exactly in rationals; only a borderline answer goes to Z3's exact LP); and the
bounds of every net number implied by the data (two LPs per stock and column, widened by 1e-7), added
as constraints, with "some term must reach (s, j)" wherever the interval excludes 0.

**Structures.** A structure is the set of included terms (a move's pair and column; an outside term's
stock and column). Adding a term with a number of 0 always fits, so structures are counted *irreducible*:
the search asks for the smallest fitting size k* (Z3 Solver with an at-most-k cardinality constraint, k
= 0, 1, ...), then enumerates: find one, block it and every superset of it (a clause: not all of these
terms), ask again, up to sizes k* + slack. The verdict is about size k*: "identifiable" when exactly one
structure of the smallest size fits; "not identifiable" with each that fits; "unknown (timeout)" when Z3
runs out of time; "outside the class" when nothing fits (a nonlinear truth, a floor that binds,
sub-steps, unannounced changes).

**Same-row relabelings are not structures here.** Terms on one stock's row reading one column are one
term: a gap inflow (c - kA) and an inflow c plus a drain kA, or births and deaths of one stock, are the
same structure (their numbers are not separable by any data); `relabelings` lists, for a structure, the
rows where the boundary allows such a split (both sides declared with the column's kind).

This module is the harness's instrument (it never reads the truth: `prepare` takes what a page gets).
The strategy z3exact carries its own copy of the class and search (strategies are isolated).
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from fractions import Fraction

import numpy as np
import z3

FLOAT_SLACK = 1e-9            # of the largest level: the engine's float arithmetic
NORM_MARGIN = 2.0             # the tolerance allows twice the least-squares row's sum of |numbers| on levels
INPUT_DIGITS = 9              # measured inputs are read to this many significant digits (their rounding joins the tolerance)
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


def _kind_sides(boundary: dict | None, declared: bool, stock: str, kind: str) -> tuple:
    """The sides an outside term of this column kind may be on."""
    want = "measured" if kind == "input" else "estimate"
    if not declared:
        return ("in", "out")
    e = (boundary or {}).get(stock) or {}
    return tuple(side for side in ("in", "out") if want in (e.get(side) or []))


MOVE_CLASSES = ("ends", "any")


def prepare(stocks: list[dict], run: dict, opts: dict | None = None, moves: str = "ends") -> Problem:
    """The class and the exact data for what a page gets (stocks, run, opts as runner.discover builds them).
    moves: "ends" (a move's rate reads the level of one of its two stocks: SD's usual drain or transfer)
    or "any" (a move's rate may read any column: every linear system's decompositions)."""
    if moves not in MOVE_CLASSES:
        raise ValueError(f"moves: one of {MOVE_CLASSES}")
    opts = opts or {}
    ids = [s["id"] for s in stocks]
    units = {s["id"]: s.get("unit") for s in stocks}
    t = list(run["t"])
    raw = {i: [float("nan") if v is None else float(v) for v in run["levels"].get(i, [])] for i in ids}
    decimals = _decimals(v for i in ids for v in raw[i])
    inputs = {k: [float(x) for x in v] for k, v in (opts.get("inputs") or {}).items() if k not in ids}
    eras = opts.get("eras") or []
    starts = sorted(float(e["start"]) for e in eras)[1:] if len(eras) > 1 else []
    era_of = lambda time_: sum(1 for s in starts if time_ >= s)
    inj = {}
    for j in opts.get("injections") or []:
        if j.get("stock") in ids and j["t"] in t:
            inj[(j["stock"], t.index(j["t"]))] = inj.get((j["stock"], t.index(j["t"])), Fraction(0)) + Fraction(float(j["amount"]))
    cols = []
    for e in (range(len(starts) + 1) if starts else [None]):     # announced eras: every number may change at each
        cols += [Column(i, "stock", era=e, unit=units[i]) for i in ids] + [Column(k, "input", era=e) for k in sorted(inputs)]
        cols.append(Column("1", "const", era=e))
    keep = [i for i in range(len(t) - 1)
            if all(not math.isnan(raw[s][i]) and not math.isnan(raw[s][i + 1]) for s in ids)
            and all(i + 1 < len(v) and not math.isnan(v[i + 1]) for v in inputs.values())]
    L = {s: [_frac(v, decimals) if not math.isnan(v) else Fraction(0) for v in raw[s]] for s in ids}
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
    for a_i, a in enumerate(ids):
        for b in ids[a_i + 1:]:
            if units[a] == units[b]:
                terms += [Term("move", c, a, b) for c, col in enumerate(cols) if moves == "any" or col.name in (a, b) and col.kind == "stock"]
    for s in ids:
        for c, col in enumerate(cols):
            sides = _kind_sides(run.get("boundary"), declared, s, col.kind)
            if sides:
                terms.append(Term("outside", c, s, sides=sides))
    top = max([abs(v) for s in ids for v in raw[s] if not math.isnan(v)] or [1.0])
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


def _q(f: Fraction):
    return z3.RealVal(f"{f.numerator}/{f.denominator}")


ADD_ROWS = 8                  # the worst missed steps reported per stock


def _violated(p: Problem, kv: dict, rows: set) -> list[int]:
    """The steps outside rows where these numbers ({term: Fraction}) miss a stock's tolerance (or drive
    a one-sided outside flow below 0), the worst first, up to ADD_ROWS per stock. Floats pick the steps
    that could miss (within a millionth of the tolerance); only those are decided in rationals."""
    out: list[int] = []
    X, Y = _floats(p)
    for r, sid in enumerate(p.ids):
        net = {}
        for m, v in kv.items():
            sg = _contrib(p, p.terms[m], sid)
            if sg and v:
                net[p.terms[m].col] = net.get(p.terms[m].col, Fraction(0)) + sg * v
        sided = {side: [(p.terms[m].col, v) for m, v in kv.items() if v and p.terms[m].kind == "outside"
                        and p.terms[m].a == sid and p.terms[m].sides == (side,)] for side in ("in", "out")}
        eps = float(p.eps[r])
        fmiss = np.abs(Y[r] - sum((float(a) * X[:, c] for c, a in net.items()), np.zeros(X.shape[0]))) - eps
        for side, sign in (("in", 1.0), ("out", -1.0)):
            if sided[side]:
                fmiss = np.maximum(fmiss, -sign * sum((float(a) * X[:, c] for c, a in sided[side]), np.zeros(X.shape[0])) - eps)
        bad = []
        for i in np.flatnonzero(fmiss > -1e-6 * eps).tolist():
            if i in rows:
                continue
            miss = abs(p.dY[r][i] - sum((a * p.X[c][i] for c, a in net.items()), Fraction(0))) - p.eps[r]
            for side, sign in (("in", 1), ("out", -1)):
                if sided[side]:
                    miss = max(miss, -sign * sum((a * p.X[c][i] for c, a in sided[side]), Fraction(0)) - p.eps[r])
            if miss > 0:
                bad.append((miss, i))
        out += [i for _, i in sorted(bad, reverse=True)[:ADD_ROWS]]
    return sorted(set(out))


def _floats(p: Problem):
    """The data as floats (steps x columns, stocks x steps), computed once per problem."""
    got = getattr(p, "_float_cache", None)
    if got is None:
        got = (np.array([[float(v) for v in row] for row in p.X]).T.reshape(p.steps, len(p.cols)),
               np.array([[float(v) for v in row] for row in p.dY]).reshape(len(p.ids), p.steps))
        p._float_cache = got
    return got


BOUND_WIDEN = 1e-7            # the LP bounds are widened by this (relative, + absolute on the scale of 1), far above float error


def net_bounds(p: Problem) -> dict[tuple[int, int], tuple[float | None, float | None]]:
    """Per (stock row, column), the interval its net number must lie in for the row to fit every step
    within its tolerance (two LPs each, HiGHS, widened by BOUND_WIDEN); None for an unbounded side
    (columns collinear to the data's precision). Implied by the fit, so adding them as constraints cuts
    the search without changing what fits; a pair whose interval excludes 0 is forced (some term must
    reach it)."""
    from scipy.optimize import linprog
    if not p.steps:
        return {}
    X, Y = _floats(p)
    J = X.shape[1]
    out = {}
    for r in range(len(p.ids)):
        eps = float(p.eps[r])
        A = np.vstack([X, -X])
        b = np.concatenate([Y[r] + eps, -Y[r] + eps])
        for c in range(J):
            got = []
            for sign in (1.0, -1.0):
                cost = np.zeros(J)
                cost[c] = sign
                lp = linprog(cost, A_ub=A, b_ub=b, bounds=[(None, None)] * J, method="highs")
                got.append(sign * float(lp.fun) if lp.status == 0 else None)
                if lp.status == 2:                # infeasible: the row fits nothing linear
                    got = None
                    break
            if got is None:
                break
            lo, hi = got
            w = lambda v: BOUND_WIDEN * (1 + abs(v))
            out[(r, c)] = (None if lo is None else lo - w(lo), None if hi is None else hi + w(hi))
    return out


def _outward(v: float, up: bool) -> Fraction:
    """A short rational at or beyond v (a bound widened, never narrowed, to keep Z3's rationals small)."""
    q = Fraction(int(np.ceil(v * 1e9)) if up else int(np.floor(v * 1e9)), 10 ** 9)
    return q


class Search:
    """The Z3 encoding of a Problem: a Boolean per term (included), a real number per term (0 unless
    included), the net numbers' implied bounds (net_bounds) and "some term reaches (s, j)" where a bound
    excludes 0. The data's steps are not in Z3 (its exact simplex on hundreds of rows with large rationals
    does not honour the timeout): each candidate structure is verified on every step outside Z3
    (`verify`), and a structure that does not fit is excluded exactly (that set of terms, not its
    supersets), so Z3 is asked again."""

    def __init__(self, p: Problem):
        self.p = p
        self.s = z3.Solver()
        self.inc = [z3.Bool(f"b{i}") for i in range(len(p.terms))]
        self.k = [z3.Real(f"k{i}") for i in range(len(p.terms))]
        for b, k in zip(self.inc, self.k):
            self.s.add(z3.Implies(z3.Not(b), k == 0))
        self.verifies = 0
        self.undecided = 0
        self.rejected = 0
        self.limits: dict = {}
        self.bounds: dict = {}
        self.forced: list = []
        self.rows: set = set()

    def add_bounds(self) -> None:
        """The implied bounds of the net numbers (net_bounds) and the forced terms, as constraints."""
        p = self.p
        self.bounds = net_bounds(p)
        for (r, c), (lo, hi) in self.bounds.items():
            parts = [(m, sg) for m, t in enumerate(p.terms) if t.col == c and (sg := _contrib(p, t, p.ids[r]))]
            net = z3.Sum([self.k[m] if sg > 0 else -self.k[m] for m, sg in parts]) if parts else z3.RealVal(0)
            if lo is not None:
                self.s.add(net >= _q(_outward(lo, False)))
            if hi is not None:
                self.s.add(net <= _q(_outward(hi, True)))
            if (lo is not None and lo > 0) or (hi is not None and hi < 0):    # forced: some term reaching (r, c) is included
                self.forced.append((r, c))
                self.s.add(z3.Or([self.inc[m] for m, _ in parts] or [z3.BoolVal(False)]))

    def _check(self, k: int, timeout_ms: float):
        """At most k terms, as an assumption (no push: Z3's push propagates without a timeout)."""
        if k not in self.limits:
            self.limits[k] = z3.Bool(f"atmost{k}")
            self.s.add(z3.Implies(self.limits[k], z3.AtMost(*self.inc, k)))
        self.s.set("timeout", max(1, int(timeout_ms)))
        got = self.s.check(self.limits[k])
        model = self.s.model() if got == z3.sat else None
        return got, model

    def verify(self, support: list[int]) -> dict | None:
        """Numbers for this structure that fit every step ({term: Fraction}, checked exactly), or None.
        A float LP (HiGHS) minimises the largest miss beyond the tolerance; its numbers are checked in
        rationals, and if they miss by a hair, the LP is solved again inside a slightly smaller tolerance
        (an interior point). Still unproven although the LP's miss is within a thousandth of the
        tolerance: counted as undecided (and treated as not fitting)."""
        self.verifies += 1
        tight = float(min(self.p.eps))
        for shrink in (0.0, 1e-6, 1e-3):
            got = _lp_numbers(self.p, support, shrink)
            if got is None:
                return None
            t, kv = got
            if not _violated(self.p, kv, set()):
                return kv
            if t > 1e-3 * tight:
                return None
        self.undecided += 1
        return None

    def find(self, k: int, deadline: float):
        """(z3 result, (support, numbers)) for a structure of at most k terms that fits every step."""
        while True:
            left = (deadline - time.perf_counter()) * 1000
            if left <= 0:
                return z3.unknown, None
            got, model = self._check(k, left)
            if got != z3.sat:
                return got, None
            sup = [i for i, b in enumerate(self.inc) if z3.is_true(model.eval(b, model_completion=True))]
            kv = {m: _frac_of(model.eval(self.k[m], model_completion=True)) for m in sup}
            if not _violated(self.p, kv, set()):
                return z3.sat, (sup, kv)
            ok = self.verify(sup)
            if ok is not None:
                return z3.sat, (sup, ok)
            self.rejected += 1
            self.exclude(sup)

    def exclude(self, support: list[int]) -> None:
        """Exclude exactly this set of terms (it does not fit; a superset still may)."""
        on = set(support)
        self.s.add(z3.Or([z3.Not(self.inc[i]) for i in support] + [self.inc[i] for i in range(len(self.inc)) if i not in on]))

    def block(self, support: list[int]) -> None:
        """Exclude this set of terms and every superset of it."""
        self.s.add(z3.Or([z3.Not(self.inc[i]) for i in support]) if support else z3.BoolVal(False))


def _lp_numbers(p: Problem, support: list[int], shrink: float = 0.0):
    """(t, {term: Fraction}): the structure's numbers minimising t, the largest miss beyond each stock's
    tolerance over every step (t <= 0: it fits), with one-sided outside rates kept at or above -eps."""
    from scipy.optimize import linprog
    X, Y = _floats(p)
    n, m = X.shape[0], len(support)
    rows, rhs = [], []
    for r, sid in enumerate(p.ids):
        D = np.zeros((n, m))
        for j, ti in enumerate(support):
            sg = _contrib(p, p.terms[ti], sid)
            if sg:
                D[:, j] = sg * X[:, p.terms[ti].col]
        eps = float(p.eps[r]) * (1 - shrink)
        rows += [np.hstack([D, -np.ones((n, 1))]), np.hstack([-D, -np.ones((n, 1))])]
        rhs += [Y[r] + eps, -Y[r] + eps]
        for side, sign in (("in", 1.0), ("out", -1.0)):
            js = [j for j, ti in enumerate(support) if p.terms[ti].kind == "outside" and p.terms[ti].a == sid and p.terms[ti].sides == (side,)]
            if js:
                E = np.zeros((n, m + 1))
                for j in js:
                    E[:, j] = -sign * X[:, p.terms[support[j]].col]
                rows.append(E)
                rhs.append(np.full(n, eps))
    cost = np.zeros(m + 1)
    cost[-1] = 1.0
    lp = linprog(cost, A_ub=np.vstack(rows), b_ub=np.concatenate(rhs), bounds=[(None, None)] * (m + 1), method="highs")
    if lp.status != 0:
        return None
    return float(lp.x[-1]), {ti: Fraction(float(v)) for ti, v in zip(support, lp.x[:-1])}


def _frac_of(v) -> Fraction:
    if z3.is_rational_value(v):
        return Fraction(v.numerator_as_long(), v.denominator_as_long())
    return Fraction(v.as_decimal(20).rstrip("?"))          # an algebraic number (not expected in LRA)


def enumerate_structures(p: Problem, slack: int = 1, cap: int = 20, budget: float = 120.0, max_size: int | None = None) -> dict:
    """Every irreducible fitting structure of the smallest size k* up to k* + slack, smallest first:
    {status, k_min, structures: [[term index]], at_min, seconds, checks, complete}. status: "identifiable",
    "not identifiable", "outside the class", "unknown (timeout)"."""
    began = time.perf_counter()
    left = lambda: budget - (time.perf_counter() - began)
    out = {"structures": [], "k_min": None, "checks": 0, "complete": False}
    if p.steps < 3:
        return {**out, "status": "unknown (too few steps)", "seconds": 0.0}
    deadline = began + budget
    sr = Search(p)
    out["build_seconds"] = round(time.perf_counter() - began, 3)
    out["numbers"] = []
    top = len(p.terms) if max_size is None else min(max_size, len(p.terms))
    if sr.verify(list(range(len(p.terms)))) is None and not sr.undecided:
        # every structure is a subset of all the terms (the others at 0): if all of them cannot fit, nothing can
        return {**out, "status": "outside the class", "seconds": round(time.perf_counter() - began, 3), "complete": True,
                "verifies": sr.verifies, "rejected": sr.rejected, "undecided": sr.undecided}
    sr.add_bounds()
    k = 0
    while k <= top:
        if left() <= 0:
            return {**out, "status": "unknown (timeout)", "seconds": round(time.perf_counter() - began, 3)}
        got, _ = sr.find(k, deadline)
        out["checks"] += 1
        if got == z3.unknown:
            return {**out, "status": "unknown (timeout)", "seconds": round(time.perf_counter() - began, 3), "at_k": k,
                    "verifies": sr.verifies, "rejected": sr.rejected, "undecided": sr.undecided}
        if got == z3.sat:
            break
        k += 1
    else:
        return {**out, "status": "outside the class", "seconds": round(time.perf_counter() - began, 3), "complete": True}
    out["k_min"] = k
    exhausted = {}                         # size: its enumeration finished (Z3 said no more)
    for size in range(k, min(top, k + slack) + 1):
        exhausted[size] = False
        while len(out["structures"]) < cap and left() > 0:
            got, found = sr.find(size, deadline)
            out["checks"] += 1
            if got == z3.unknown:
                break
            if got != z3.sat:
                exhausted[size] = True
                break
            sup = sorted(found[0])
            out["structures"].append(sup)
            out["numbers"].append({m: float(v) for m, v in found[1].items()})
            sr.block(sup)
        if not exhausted[size]:
            break
    at_min = [s for s in out["structures"] if len(s) == k]
    out.update(at_min=len(at_min), complete=all(exhausted.values()), exhausted=exhausted, verifies=sr.verifies, rejected=sr.rejected, undecided=sr.undecided)
    status = ("not identifiable" if len(at_min) > 1 else "identifiable" if exhausted.get(k) else "unknown (timeout)")
    out.update(status=status, seconds=round(time.perf_counter() - began, 3))
    return out


def refit(p: Problem, support: list[int]) -> tuple[np.ndarray, float]:
    """Least-squares numbers of a structure on the one-step changes (all rows jointly), and the largest
    absolute residual."""
    S, n = len(p.ids), p.steps
    X = np.array([[float(v) for v in row] for row in p.X]) if p.X and n else np.zeros((len(p.cols), 0))
    Y = np.array([[float(v) for v in row] for row in p.dY])
    if not support:
        return np.zeros(0), float(np.abs(Y).max()) if Y.size else 0.0
    D = np.zeros((S * n, len(support)))
    for m, i in enumerate(support):
        t = p.terms[i]
        for r, sid in enumerate(p.ids):
            sg = _contrib(p, t, sid)
            if sg:
                D[r * n:(r + 1) * n, m] = sg * X[t.col]
    k, *_ = np.linalg.lstsq(D, Y.reshape(-1), rcond=None)
    return k, float(np.abs(Y.reshape(-1) - D @ k).max())


def relabelings(p: Problem, support: list[int]) -> list[str]:
    """Rows where an outside term could be split into an inflow and an outflow on the same column
    (both sides allowed for its kind): the numbers of such a split are never separable."""
    return [p.terms[i].key(p.cols) for i in support if p.terms[i].kind == "outside" and len(p.terms[i].sides) == 2]


def describe(p: Problem, support: list[int], k: np.ndarray | None = None) -> str:
    parts = []
    for m, i in enumerate(support):
        t = p.terms[i]
        parts.append(t.key(p.cols) + (f" = {k[m]:.6g}" if k is not None and len(k) > m else ""))
    return "; ".join(parts) if parts else "(no terms)"

