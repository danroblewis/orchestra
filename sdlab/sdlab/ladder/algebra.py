"""Proven equivalence (the user, 2026-10-21): is a found model's every net rate algebraically the truth's?

The scorer's older equivalence (score.py `_same_system`, `_same_function`) asks whether the data can tell
the found model from the truth: the same linear system while no floor binds, or the same change of every
stock on the run's states. That admits models whose equations differ where the run never went (a floored
gap seen as an inflow and a drain, a mechanism never exercised). This module asks the stronger question:
is every measured stock's net rate of change (its inflows less its outflows, a function of the stocks,
the measured inputs and the window of time) the same function as the truth's for EVERY state, not only
the run's? The answer decides "equivalent" (proven) against "fits" (the data cannot tell them apart, not
proven) in score.py.

**What is compared.** Per window where the truth's equations hold still (parts.windows), each flow's
amount is written as an expression tree (the engine's arithmetic, sdtruth.py / runner.py): a linear rate
c + sum k_j x_j floored at 0 (not a two-way flow's), an expression rate (sdtruth_expr's language: MIN,
MAX, ABS, comparisons, IF THEN ELSE, LOOKUP, products, powers, functions; auxiliaries and flow(id)
substituted), `available` (the source's level / ratio), times its effects (a table is a LOOKUP floored
at 0, a linear effect MIN(hi, MAX(lo, x / normal))). A stock's net rate is the sum of the flows into it
less ratio x the flows out of it and per x the flows that use it up. A found flow's linear numbers are
its averages over the window (form_over: byTime segments and outside inflow pieces), as the pass compares
them; a found expression segment is compared over the part of the window where it holds.

**How.** Piecewise expressions are compared region by region. The kinks (where a MIN or MAX changes
branch, a floor binds, a comparison flips, a LOOKUP passes a point) are hyperplanes in the state; the
state space (stocks >= 0 unless signed, inputs >= 0 when the run's are, each up to 100 x its largest
value on the run) is cut by them into regions, found one at a time by linear programs (scipy's HiGHS):
a region is split whenever a kink changes sign inside it. In each region every branch is fixed, so both
net rates are polynomials (sympy), compared coefficient by coefficient with the scorer's tolerance
(`close`, score.py: rel, the floor and the oracle's standard error). Two linear functions that agree on
an open region agree everywhere in it, so this is a proof, not a sample. Where coefficients differ in a
region thinner than rel of the run's range (a sliver between two kinks a tolerance apart), the region
is let off. Step functions (CEIL, FLOOR, INTEGER, MODULO, QUANTUM) are opaque atoms: the same atom on
both sides cancels, compared as a free variable (so identity is proven for every value it could take).
A region whose rates are not polynomials (a division by a stock, SQRT, EXP) is compared by sympy's
simplify of the exact difference. Before comparing, each found number within rel of a truth number is
snapped to it (and the comparison is also tried unsnapped), so a kink a tolerance away lines up.

**Not covered** (returned as not proven, with the reason): a found or true flow that touches a stock
that is not measured (hidden stocks, smoothings), a kink that is not affine in the state (MAX(0, x y - c)),
a rate form the engine does not have. The engine's sharing of a stock among its outflows (a stock cannot
give more than it holds) and stock ceilings are not modelled: rates are compared as written.

check() returns {equivalent, proven, method, regions, differences, notes}: equivalent when every stock's
net rate is identical in every window; proven when the comparison was complete (an identity, or a
difference found in some region); a difference names the window, the stock, a state in the region and
the term. bookkeeping() names how two equivalent drawings differ (a move against a link and a drain),
and whether the found drawing is the conserving one the user prefers.
"""

from __future__ import annotations

import numpy as np

from ..sdtruth_expr import COMPARE, ExprError, compile_expr, parse, text
from .parts import form_over, linear_form

OPAQUE = ("ceil", "floor", "integer", "modulo", "quantum")
SMOOTH_FN = ("sqrt", "exp", "ln", "log", "sin", "cos", "tan", "arcsin", "arccos", "arctan", "sinh", "cosh", "tanh", "power")
BOX = 100.0                  # the state space: each variable up to BOX x its largest value on the run
MAX_REGIONS = 400            # more regions than this: not proven (too many to compare)
EPS = 1e-9


class Unprovable(Exception):
    """Something the check cannot express or decide."""


# ---- expression trees (sdtruth_expr's tuples) ----

def _num(v: float) -> tuple:
    return ("num", float(v))


def _bin(op: str, a: tuple, b: tuple) -> tuple:
    return ("bin", op, a, b)


def _max0(x: tuple) -> tuple:
    return ("call", "max", [_num(0.0), x])


def _lin(c: float, ks: dict[str, float]) -> tuple:
    out = _num(c)
    for j, k in ks.items():
        out = _bin("+", out, _bin("*", _num(k), ("name", j)))
    return out


def _sub_names(node: tuple, env: dict[str, tuple]) -> tuple:
    """node with every name in env replaced by its tree (auxiliaries), recursively."""
    kind = node[0]
    if kind == "name":
        return _sub_names(env[node[1]], env) if node[1] in env else node
    if kind == "neg":
        return ("neg", _sub_names(node[1], env))
    if kind == "bin":
        return ("bin", node[1], _sub_names(node[2], env), _sub_names(node[3], env))
    if kind == "call":
        return ("call", node[1], [_sub_names(a, env) for a in node[2]])
    return node


def _sub_flows(node: tuple, flows: dict[str, tuple]) -> tuple:
    kind = node[0]
    if kind == "call" and node[1] == "flow":
        fid = node[2][0][1]
        if fid not in flows:
            raise Unprovable(f"flow({fid}) names a flow that is not compared")
        return flows[fid]
    if kind == "neg":
        return ("neg", _sub_flows(node[1], flows))
    if kind == "bin":
        return ("bin", node[1], _sub_flows(node[2], flows), _sub_flows(node[3], flows))
    if kind == "call":
        return ("call", node[1], [_sub_flows(a, flows) for a in node[2]])
    return node


def _names(node: tuple) -> set[str]:
    kind = node[0]
    if kind == "name":
        return {node[1]}
    if kind == "neg":
        return _names(node[1])
    if kind == "bin":
        return _names(node[2]) | _names(node[3])
    if kind == "call":
        return set().union(*[_names(a) for a in node[2]]) if node[2] else set()
    return set()


def _aux_trees(aux) -> dict[str, tuple]:
    raw = aux or {}
    if isinstance(raw, list):
        raw = {a["id"]: a["expr"] for a in raw}
    return {k: parse(v) for k, v in raw.items()}


def _effect_tree(e: dict) -> tuple:
    x = ("name", e.get("stock"))
    if e.get("shape") == "table" and e.get("points"):
        pts = sorted((float(a), float(b)) for a, b in e["points"])
        return _max0(("call", "lookup", [x, ("list", [list(p) for p in pts])]))
    normal = max(1e-9, float(e.get("normal") or 1))
    lo = float(e["min"]) if e.get("min") is not None else 0.0
    hi = float(e["max"]) if e.get("max") is not None else 1.0
    return ("call", "min", [_num(hi), ("call", "max", [_num(lo), _bin("/", x, _num(normal))])])


def _rate_tree(rate: dict | None, flow: dict, aux: dict[str, tuple]) -> tuple:
    """A rate as a tree, before its floor; Unprovable for a form the engine does not have."""
    r = rate or {}
    form = r.get("form")
    if form == "expr":
        try:
            return _sub_names(parse(r.get("expr")), aux)
        except ExprError as e:
            raise Unprovable(f"expression does not parse: {e}") from e
    if form == "available":
        src = r.get("stock") or flow.get("from")
        ratio = float(flow.get("ratio") or 1) or 1.0
        return _bin("/", ("name", src), _num(ratio)) if src else _num(0.0)
    lf = linear_form(r)
    if lf is None:
        raise Unprovable(f"rate form {form!r} is not one the check knows")
    return _lin(*lf)


def _amount_tree(base: tuple, flow: dict, form: str | None) -> tuple:
    """The flow's amount: its rate floored at 0 (not a two-way flow's, nor `available`'s), times its effects."""
    out = base if flow.get("two_way") or form == "available" else _max0(base)
    for e in flow.get("effects") or []:
        out = _bin("*", out, _effect_tree(e))
    return out


# ---- the models' net rates per window ----

def _seg_at(segs: list[dict], t: int) -> int:
    for i, g in enumerate(segs):
        if g["from"] <= t <= g["to"]:
            return i
    return len(segs) - 1


def _members(flows: list[dict]) -> list[dict]:
    return [m for g in flows for m in (g["merged"]["flows"] if g.get("merged") else [g])]


def _linear_segments(f: dict) -> bool:
    if f.get("inflow"):
        return True
    rates = [g.get("rate") for g in f["byTime"]] if f.get("byTime") else [f.get("rate")]
    return all(linear_form(r) is not None for r in rates)


def _net(flows: list[tuple[dict, tuple]], ids: list[str]) -> dict[str, tuple]:
    """Each measured stock's net rate: in minus ratio x out minus per x used."""
    net = {s: _num(0.0) for s in ids}
    for f, amt in flows:
        a, b = f.get("from"), f.get("to")
        if b in net:
            net[b] = _bin("+", net[b], amt)
        if a in net:
            net[a] = _bin("-", net[a], _bin("*", _num(float(f.get("ratio") or 1)), amt))
        for u in f.get("uses") or []:
            if u.get("stock") in net:
                net[u["stock"]] = _bin("-", net[u["stock"]], _bin("*", _num(float(u.get("per") or 0)), amt))
    return net


def _check_ends(flows: list[dict], known: set[str], who: str) -> None:
    for f in flows:
        if f.get("via"):
            raise Unprovable(f"{who} has a hidden stock ({f.get('from') or 'outside'} -> (hidden) -> {f.get('to')})")
        if isinstance(f.get("delay"), dict):
            raise Unprovable(f"{who} has a delay's hidden stages")
        for end in (f.get("from"), f.get("to")):
            if end and end not in known:
                raise Unprovable(f"{who} has a flow touching {end}, which is not measured")


def truth_nets(truth_flows: list[dict], ids: list[str], window: tuple[int, int], aux) -> dict[str, tuple]:
    """The truth's net rate per measured stock over a window (its rates hold still there)."""
    _check_ends(truth_flows, set(ids), "the truth")
    env = _aux_trees(aux)
    bases, forms = {}, {}
    for i, f in enumerate(truth_flows):
        segs = f.get("byTime")
        rate = segs[_seg_at(segs, window[0])]["rate"] if segs else f.get("rate")
        bases[i], forms[i] = _rate_tree(rate, f, {**env, **_aux_trees((f.get("whole") or {}).get("auxiliaries"))}), (rate or {}).get("form")
    plain = {}
    for i, f in enumerate(truth_flows):                       # flow(id) reads another flow's amount as moved
        if not _has_flow_ref(bases[i]):
            plain[f.get("id")] = _amount_tree(bases[i], f, forms[i])
    out = []
    for i, f in enumerate(truth_flows):
        base = _sub_flows(bases[i], plain) if _has_flow_ref(bases[i]) else bases[i]
        out.append((f, _amount_tree(base, f, forms[i])))
    return _net(out, ids)


def _has_flow_ref(node: tuple) -> bool:
    kind = node[0]
    if kind == "call":
        return node[1] == "flow" or any(_has_flow_ref(a) for a in node[2])
    if kind == "neg":
        return _has_flow_ref(node[1])
    if kind == "bin":
        return _has_flow_ref(node[2]) or _has_flow_ref(node[3])
    return False


def found_nets(found_flows: list[dict], ids: list[str], window: tuple[int, int], aux) -> list[tuple[tuple[int, int], dict[str, tuple]]]:
    """The found model's net rates over a window: [(sub-window, nets)], split where a found expression
    segment changes inside the window (a linear rate's numbers are its window averages, as the pass reads them)."""
    flows = _members(found_flows)
    _check_ends(flows, set(ids), "the found model")
    env = _aux_trees(aux)
    a, b = window
    cuts = {a}
    for f in flows:
        if not _linear_segments(f):
            for g in f.get("byTime") or []:
                if a < g["from"] <= b:
                    cuts.add(int(g["from"]))
    starts = sorted(cuts)
    subs = [(s, (starts[i + 1] - 1) if i + 1 < len(starts) else b) for i, s in enumerate(starts)]
    out = []
    for sa, sb in subs:
        amts = []
        for f in flows:
            if _linear_segments(f):
                lf = form_over(f, a, b)
                if lf is None:
                    raise Unprovable("a found rate is not linear")
                form = "constant" if f.get("inflow") else None
                amts.append((f, _amount_tree(_lin(*lf), f, form)))
            else:
                segs = f.get("byTime")
                rate = segs[_seg_at(segs, sa)]["rate"] if segs else f.get("rate")
                base = _rate_tree(rate, f, env)
                if _has_flow_ref(base):
                    raise Unprovable("a found rate reads flow(id)")
                amts.append((f, _amount_tree(base, f, (rate or {}).get("form"))))
        out.append(((sa, sb), _net(amts, ids)))
    return out


# ---- snapping found numbers onto the truth's ----

def _numbers(node: tuple, out: list) -> list:
    kind = node[0]
    if kind == "num":
        out.append(node[1])
    elif kind == "neg":
        _numbers(node[1], out)
    elif kind == "bin":
        _numbers(node[2], out)
        _numbers(node[3], out)
    elif kind == "call":
        for a in node[2]:
            _numbers(a, out)
    elif kind == "list":
        for x, y in node[1]:
            out += [x, y]
    return out


def _snap(node: tuple, ref: np.ndarray, rel: float) -> tuple:
    """node with each number within rel of one of ref's replaced by the nearest."""
    def one(v: float) -> float:
        if not len(ref) or v == 0:
            return v
        i = int(np.argmin(np.abs(ref - v)))
        return float(ref[i]) if abs(ref[i] - v) <= rel * abs(ref[i]) + 1e-15 else v
    kind = node[0]
    if kind == "num":
        return _num(one(node[1]))
    if kind == "neg":
        return ("neg", _snap(node[1], ref, rel))
    if kind == "bin":
        return ("bin", node[1], _snap(node[2], ref, rel), _snap(node[3], ref, rel))
    if kind == "call":
        return ("call", node[1], [_snap(a, ref, rel) for a in node[2]])
    if kind == "list":
        return ("list", [[one(x), one(y)] for x, y in node[1]])
    return node


# ---- resolving the branches at a state ----

class _View(dict):
    """A state; an opaque atom not yet a variable of the space reads as its step function's value."""

    def __missing__(self, key):
        if isinstance(key, str) and key.startswith("@"):
            return float(compile_expr(parse(key[1:]))(self, {}))
        raise KeyError(key)


def _value(node: tuple, view: dict) -> float:
    try:
        return float(compile_expr(node)(view if isinstance(view, _View) else _View(view), {}))
    except (ArithmeticError, ValueError, TypeError, KeyError) as e:
        raise Unprovable(f"cannot evaluate {text(node)}: {e}") from e


def _resolve(node: tuple, view: dict, kinks: list) -> tuple:
    """node with every branch fixed as it is at the state `view` (MIN / MAX / ABS / comparisons / IF / LOOKUP
    resolved; opaque step functions as atoms), appending each kink (a tree that must keep its sign for the
    branches to stay as chosen) to `kinks`."""
    kind = node[0]
    if kind in ("num", "name"):
        return node
    if kind == "neg":
        return ("neg", _resolve(node[1], view, kinks))
    if kind == "bin":
        op = node[1]
        a, b = _resolve(node[2], view, kinks), _resolve(node[3], view, kinks)
        if op in COMPARE:
            d = _bin("-", a, b)
            kinks.append(d)
            return _num(1.0 if COMPARE[op](_value(a, view), _value(b, view)) else 0.0)
        return ("bin", op, a, b)
    if kind != "call":
        raise Unprovable(f"cannot read {kind}")
    name, raw = node[1], node[2]
    if name in ("min", "max"):
        args = [_resolve(x, view, kinks) for x in raw]
        vals = [_value(x, view) for x in args]
        i = int(np.argmin(vals) if name == "min" else np.argmax(vals))
        for j, x in enumerate(args):
            if j != i:
                kinks.append(_bin("-", args[i], x) if name == "max" else _bin("-", x, args[i]))
        return args[i]
    if name == "abs":
        x = _resolve(raw[0], view, kinks)
        kinks.append(x)
        return x if _value(x, view) >= 0 else ("neg", x)
    if name == "if_then_else":
        c = _resolve(raw[0], view, kinks)
        if c[0] != "num":                                  # a condition that is not a comparison: its sign
            kinks.append(c)
        return _resolve(raw[1] if _value(c, view) else raw[2], view, kinks)
    if name in ("and", "or", "not"):
        args = [_resolve(x, view, kinks) for x in raw]
        vals = [bool(_value(x, view)) for x in args]
        for x in args:
            if x[0] != "num":
                kinks.append(x)
        v = all(vals) if name == "and" else any(vals) if name == "or" else not vals[0]
        return _num(1.0 if v else 0.0)
    if name == "lookup":
        x = _resolve(raw[0], view, kinks)
        pts = sorted((float(a), float(b)) for a, b in raw[1][1])
        xv = _value(x, view)
        for p, _ in pts:
            kinks.append(_bin("-", x, _num(p)))
        if xv <= pts[0][0]:
            return _num(pts[0][1])
        for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
            if xv <= x1:
                s = (y1 - y0) / max(1e-12, x1 - x0)
                return _bin("+", _num(y0), _bin("*", _num(s), _bin("-", x, _num(x0))))
        return _num(pts[-1][1])
    if name in ("zidz", "xidz"):                             # a / b (the |b| < SMALL sliver is not compared)
        return _bin("/", _resolve(raw[0], view, kinks), _resolve(raw[1], view, kinks))
    if name in OPAQUE:
        args = [_resolve(x, view, kinks) for x in raw]
        return ("name", "@" + text(("call", name, args)))
    if name in SMOOTH_FN:
        return ("call", name, [_resolve(x, view, kinks) for x in raw])
    raise Unprovable(f"function {name} is not one the check knows")


# ---- sympy ----

def _sym(node: tuple, syms: dict):
    import sympy as sp
    kind = node[0]
    if kind == "num":
        v = node[1]
        return sp.Integer(int(v)) if v == int(v) and abs(v) < 1e12 else sp.Float(v, 17)
    if kind == "name":
        if node[1] not in syms:
            syms[node[1]] = sp.Symbol(node[1], real=True)
        return syms[node[1]]
    if kind == "neg":
        return -_sym(node[1], syms)
    if kind == "bin":
        a, b = _sym(node[2], syms), _sym(node[3], syms)
        return {"+": lambda: a + b, "-": lambda: a - b, "*": lambda: a * b, "/": lambda: a / b, "^": lambda: a ** b}[node[1]]()
    if kind == "call":
        args = [_sym(x, syms) for x in node[2]]
        fn = {"sqrt": sp.sqrt, "exp": sp.exp, "ln": sp.log, "sin": sp.sin, "cos": sp.cos, "tan": sp.tan, "arcsin": sp.asin,
              "arccos": sp.acos, "arctan": sp.atan, "sinh": sp.sinh, "cosh": sp.cosh, "tanh": sp.tanh}
        if node[1] in fn:
            return fn[node[1]](args[0])
        if node[1] == "power":
            return args[0] ** args[1]
        if node[1] == "log":
            return sp.log(args[0], 10) if len(args) == 1 else sp.log(args[0]) / sp.log(args[1])
    raise Unprovable(f"cannot write {text(node)} for sympy")


def _poly(expr, gens):
    """{monomial (names, repeated for powers): coefficient}, or None when expr is not a polynomial in gens."""
    import sympy as sp
    e = sp.expand(expr)
    try:
        p = sp.Poly(e, *gens) if gens else None
    except sp.PolynomialError:
        return None
    if p is None:
        return {(): float(e)} if e.is_number else None
    if any(not c.is_number for c in p.coeffs()):
        return None
    out = {}
    for mono, c in p.terms():
        key = tuple(g for g, n in zip(gens, mono) for _ in range(n))
        out[tuple(str(x) for x in key)] = float(c)
    return out


def _affine(node: tuple) -> tuple[dict[str, float], float] | None:
    """A kink tree as an affine function {name: coefficient}, constant; None when it is not affine."""
    syms: dict = {}
    e = _sym(node, syms)
    p = _poly(e, [syms[k] for k in sorted(syms)])
    if p is None or any(len(m) > 1 for m in p):
        return None
    return {m[0]: c for m, c in p.items() if m and c != 0.0}, p.get((), 0.0)


# ---- regions ----

class _Space:
    """The state space in scaled coordinates (y = x / range), and linear programs over its regions."""

    def __init__(self, ranges: dict[str, tuple[float, float, float]]):
        self.ranges = ranges                                # name: (scale, lo, hi) in scaled units

    def ensure(self, name: str, lo_hi: tuple[float, float, float]) -> None:
        self.ranges.setdefault(name, lo_hi)

    def _rows(self, cons: list, names: list[str]):
        A, b = [], []
        for (coef, c0, sign) in cons:                       # sign * (sum coef x + c0) >= t * |a|
            a = np.array([coef.get(n, 0.0) * self.ranges[n][0] for n in names])
            norm = float(np.linalg.norm(a)) or 1.0
            A.append(list(-sign * a / norm) + [1.0])
            b.append(sign * c0 / norm)
        return A, b

    def center(self, cons: list, faces: bool = True) -> tuple[dict[str, float], float] | None:
        """The deepest point of the region (Chebyshev centre against its kinks, and the box's faces unless
        faces is False) and its depth; None if empty."""
        from scipy.optimize import linprog
        names = sorted(self.ranges)
        A, b = self._rows(cons, names)
        if faces:                                            # y - lo >= t, hi - y >= t
            for i, n in enumerate(names):
                for sign, edge in ((1.0, self.ranges[n][1]), (-1.0, self.ranges[n][2])):
                    row = [0.0] * (len(names) + 1)
                    row[i], row[-1] = -sign, 1.0
                    A.append(row)
                    b.append(-sign * edge)
        bounds = [(self.ranges[n][1], self.ranges[n][2]) for n in names] + [(0.0, BOX)]
        c = np.zeros(len(names) + 1)
        c[-1] = -1.0
        res = linprog(c, A_ub=A or None, b_ub=b or None, bounds=bounds, method="highs")
        if res.status != 0 or -res.fun <= EPS:
            return None
        y = res.x[:-1]
        return {n: float(y[i] * self.ranges[n][0]) for i, n in enumerate(names)}, float(-res.fun)

    def extent(self, cons: list, coef: dict[str, float], c0: float) -> tuple[float, float]:
        """min and max of sum coef x + c0 over the region (scaled by its normal)."""
        from scipy.optimize import linprog
        names = sorted(self.ranges)
        a = np.array([coef.get(n, 0.0) * self.ranges[n][0] for n in names])
        norm = float(np.linalg.norm(a)) or 1.0
        A, b = self._rows(cons, names)
        A = [row[:-1] for row in A]                          # t = 0: the closed region
        bounds = [(self.ranges[n][1], self.ranges[n][2]) for n in names]
        out = []
        for s in (1.0, -1.0):
            res = linprog(s * a / norm, A_ub=A or None, b_ub=b or None, bounds=bounds, method="highs")
            if res.status != 0:
                return 0.0, 0.0
            out.append(s * res.fun + c0 / norm)
        return out[0], out[1]


def _same_kink(coef: dict, c0: float, cons: list) -> bool:
    for k2, c2, _ in cons:
        keys = set(coef) | set(k2)
        v1 = np.array([coef.get(k, 0.0) for k in keys] + [c0])
        v2 = np.array([k2.get(k, 0.0) for k in keys] + [c2])
        n1, n2 = np.linalg.norm(v1), np.linalg.norm(v2)
        if n1 and n2 and abs(abs(float(v1 @ v2)) / (n1 * n2) - 1) < 1e-12:
            return True
    return False


def _compare_region(tt: dict, ft: dict, view: dict, close, w: int, rel: float) -> list[dict]:
    """The stocks whose resolved net rates differ (as polynomials, within close; else by sympy's
    simplify of the exact difference): [difference]."""
    import sympy as sp
    out = []
    for s in tt:
        syms: dict = {}
        et, ef = _sym(tt[s], syms), _sym(ft[s], syms)
        gens = [syms[k] for k in sorted(syms)]
        pt, pf = _poly(et, gens), _poly(ef, gens)
        if pt is not None and pf is not None:
            for mono in sorted(set(pt) | set(pf)):
                a, b = pt.get(mono, 0.0), pf.get(mono, 0.0)
                if not close(s, mono, a, b, w):
                    out.append({"stock": s, "term": "*".join(mono) or "1", "truth": a, "found": b})
                    break
            continue
        d = sp.simplify(et - ef)
        if d != 0 and not (d.is_number and abs(float(d)) <= 1e-12):
            nums = [float(x) for x in d.atoms(sp.Float)]
            if not nums or max(abs(x) for x in nums) > 1e-12:
                out.append({"stock": s, "term": "(not a polynomial)", "truth": str(et), "found": str(ef), "exact": True})
    return out


def _explore(tt: dict, ft: dict, space: _Space, close, w: int, rel: float, atoms_range) -> tuple[int, list[dict], int]:
    """Cut the state space into regions where every branch of both models holds, and compare in each.
    (regions compared, differences, slivers let off)."""
    regions, diffs, slivers = 0, [], 0
    stack: list[list] = [[]]
    while stack:
        cons = stack.pop()
        got = space.center(cons)
        if got is None:
            continue
        view, _ = got
        view = _View(view)
        kinks: list = []
        rt = {s: _resolve(tr, view, kinks) for s, tr in tt.items()}
        rf = {s: _resolve(tr, view, kinks) for s, tr in ft.items()}
        for n in set().union(*[_names(x) for x in list(rt.values()) + list(rf.values()) + kinks]):
            if n not in space.ranges:
                if not n.startswith("@"):
                    raise Unprovable(f"reads {n}, which is not a measured stock or input")
                space.ensure(n, atoms_range(n))
                view = None
        if view is None:                                     # a new atom: find the centre again in the larger space
            stack.append(cons)
            continue
        split = None
        for k in kinks:
            aff = _affine(k)
            if aff is None:
                if _nonneg_poly(k):
                    continue
                raise Unprovable(f"a kink that is not affine in the state: {text(k)}")
            coef, c0 = aff
            if not coef or _same_kink(coef, c0, cons):
                continue
            lo, hi = space.extent(cons, coef, c0)
            if lo < -EPS and hi > EPS:
                split = (coef, c0)
                break
        if split is not None:
            if len(stack) + regions > MAX_REGIONS:
                raise Unprovable(f"more than {MAX_REGIONS} regions")
            stack += [cons + [(split[0], split[1], 1.0)], cons + [(split[0], split[1], -1.0)]]
            continue
        regions += 1
        d = _compare_region(rt, rf, view, close, w, rel)
        if d:
            thin = space.center(cons, faces=False) if cons else None
            if thin is not None and thin[1] <= rel:          # a sliver between two kinks a tolerance apart
                slivers += 1
                continue
            for x in d:
                x["at"] = {n: round(v, 6) for n, v in view.items() if not n.startswith("@")}
            diffs += d
            if len(diffs) >= 4:
                break
    return regions, diffs, slivers


def _nonneg_poly(node: tuple) -> bool:
    """A kink that is a polynomial with no negative coefficient (of stocks, never below 0): its sign never changes."""
    syms: dict = {}
    e = _sym(node, syms)
    p = _poly(e, [syms[k] for k in sorted(syms)])
    return p is not None and all(c >= 0 for c in p.values())


# ---- the check ----

def _ranges(ids: list[str], inputs: list[str], states: list[dict], signed: set[str]) -> dict:
    out = {}
    for n in list(ids) + list(inputs):
        vals = np.array([float(s.get(n, 0.0)) for s in states]) if states else np.zeros(1)
        scale = max(1e-6, float(np.max(np.abs(vals)))) if len(vals) else 1.0
        neg = n in signed or (n in inputs and len(vals) and float(np.min(vals)) < 0)
        out[n] = (scale, -BOX if neg else 0.0, BOX)
    return out


def check(truth_flows: list[dict], found_flows: list[dict], ids: list[str], wins: list[tuple[int, int]], *, inputs=(),
          states: list[dict] | None = None, close=None, rel: float = 0.02, aux=None, signed=frozenset()) -> dict:
    """Is every measured stock's net rate the found model's the same function as the truth's, in every
    window, for every state? See the module docstring. close(stock, monomial, true, found, window) -> bool
    compares one coefficient (default: within rel)."""
    close = close or (lambda s, m, a, b, w: abs(a - b) <= rel * abs(a) + 1e-12)
    states = states or []
    inputs = [x for x in inputs if x not in ids]
    out = {"equivalent": False, "proven": False, "method": None, "regions": 0, "differences": [], "notes": []}
    try:
        total, slivers, diffs, piecewise = 0, 0, [], False
        for w, win in enumerate(wins):
            tt = truth_nets(truth_flows, ids, win, aux)
            ref = np.array(sorted({abs(v) for tr in tt.values() for v in _numbers(tr, []) if v} |
                                  {-abs(v) for tr in tt.values() for v in _numbers(tr, []) if v}))
            for sub, ft in found_nets(found_flows, ids, win, aux):
                def atoms_range(name: str) -> tuple[float, float, float]:
                    vals = []
                    tree = parse(name[1:])
                    for s in states:
                        try:
                            vals.append(float(compile_expr(tree)(s, {})))
                        except (ArithmeticError, ValueError, TypeError, KeyError):
                            pass
                    scale = max(1e-6, max((abs(v) for v in vals), default=1.0))
                    return scale, (0.0 if vals and min(vals) >= 0 else -BOX), BOX
                best = None
                for snapped in (True, False):
                    space = _Space(_ranges(ids, inputs, states, set(signed)))
                    fs = {s: _snap(tr, ref, rel) for s, tr in ft.items()} if snapped else ft
                    n, d, sl = _explore(tt, fs, space, close, w, rel, atoms_range)
                    if best is None or (not d and best[1]):
                        best = (n, d, sl)
                    if not d:
                        break
                n, d, sl = best
                total += n
                slivers += sl
                piecewise |= n > 1
                for x in d:
                    x["window"] = list(sub)
                diffs += d
                if diffs:
                    break
            if diffs:
                break
        out.update(proven=True, equivalent=not diffs, differences=diffs[:4], regions=total,
                   method="regions" if piecewise else "identity")
        if slivers:
            out["notes"].append(f"{slivers} sliver region(s) between kinks a tolerance apart let off")
    except Unprovable as e:
        out.update(method="not covered", notes=[str(e)])
    return out


# ---- how two equivalent drawings differ ----

def bookkeeping(true_w: list[dict], found_w: list[dict], units: dict[str, str | None], close_part=None) -> dict:
    """How a proven-equivalent found model draws what the truth draws (parts per window, score.py's keys):
    {note, conserving, unit_moves}. conserving: the found model writes as moves between stocks of one unit
    what the truth writes as a link into B and an outflow from A of the same amount, and with that rewrite
    of the truth every part matches (close_part(key, true, found) -> bool): the conserving drawing, which
    the user prefers (2026-10-21), so it is the pass. unit_moves: found moves between stocks of different
    units that stand for the truth's link and outflow (never equivalent)."""
    close_part = close_part or (lambda k, a, b: abs(a - b) <= 1e-9 * max(1.0, abs(a)))
    words, unit_moves, rewrite_ok = [], [], True
    rewritten = []
    for tp, fp in zip(true_w, found_w):
        tp2 = dict(tp)
        for k in fp:
            if k[0] != "flow" or not (k[1] and k[2]) or k in tp:
                continue
            a, b, r = k[1], k[2], k[3]
            link, drain = ("flow", None, b, r), ("flow", a, None, r)
            if link in tp and drain in tp:
                if units.get(a) != units.get(b):
                    unit_moves.append(f"{a} -> {b} ({units.get(a)} -> {units.get(b)})")
                    continue
                kl = float(tp[link])
                tp2[k] = kl
                tp2.pop(link, None)
                rest = float(tp[drain]) - kl
                if close_part(drain, 0.0, rest):
                    tp2.pop(drain, None)
                    words.append(f"the truth's link into {b} and outflow from {a} (reading {r}) are drawn as the move {a} -> {b} (conserving)")
                else:
                    tp2[drain] = rest
                    words.append(f"the truth's link into {b} (reading {r}) is drawn as the move {a} -> {b} and a smaller outflow "
                                 f"from {a} (conserving)")
        for k in tp:
            if k[0] != "flow" or not (k[1] and k[2]) or k in fp:
                continue
            a, b, r = k[1], k[2], k[3]
            if ("flow", None, b, r) in fp and ("flow", a, None, r) in fp:
                words.append(f"the move {a} -> {b} (reading {r}) is drawn as a link into {b} and an outflow from {a} "
                             "(not conserving: the move is the preferred drawing)")
        rewritten.append(tp2)
    conserving = False
    if any("(conserving)" in x for x in words) and not unit_moves:
        conserving = True
        for tp2, fp in zip(rewritten, found_w):
            for k in set(tp2) | set(fp):
                tv, fv = tp2.get(k, 0.0), fp.get(k, 0.0)
                if not (isinstance(tv, (int, float)) and isinstance(fv, (int, float))):
                    if tv != fv:
                        conserving = False
                    continue
                if not close_part(k, float(tv), float(fv)):
                    conserving = False
        rewrite_ok = conserving
    if not words:
        missing = sorted({_label(k) for tp, fp in zip(true_w, found_w) for k in tp if k not in fp})
        extra = sorted({_label(k) for tp, fp in zip(true_w, found_w) for k in fp if k not in tp})
        if missing or extra:
            words.append("the same net rates drawn differently: " + "; ".join(
                ([f"the truth has {', '.join(missing[:4])}"] if missing else []) + ([f"the found model has {', '.join(extra[:4])}"] if extra else [])))
        else:
            words.append("the same parts, numbers that combine to the same net rates")
    note = "; ".join(dict.fromkeys(words))
    if unit_moves:
        note += "; a move between stocks of different units stands for the truth's link and outflow: " + ", ".join(sorted(set(unit_moves)))
    return {"note": note, "conserving": conserving and rewrite_ok, "unit_moves": sorted(set(unit_moves))}


def _label(k: tuple) -> str:
    from .parts import label
    try:
        return label(k)
    except (ValueError, IndexError):
        return str(k)

