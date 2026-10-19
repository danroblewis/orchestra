"""Read a Vensim (.mdl) or XMILE (.xmile, .stmx) model through PySD's parser into stocks and flows
whose rates are sympy expressions (needs the optional packages pysd and sympy).

    read(path) -> Model

PySD 3 parses a model into an abstract model (pysd.translators: sections of elements, each element's
equation a tree of ArithmeticStructure, ReferenceStructure, CallStructure, IntegStructure, ...). Here
every auxiliary and constant is inlined, so each flow's rate is an expression in the stocks, the
symbol TIME and placeholders:

- a call (MIN, SQRT, STEP, IF THEN ELSE, a comparison, ...) is an undefined sympy function F_<name>;
- a lookup is LK_<n>(argument), its points in Model.lookups;
- DELAY1/DELAY3 (and their I forms, DELAY N of order 1 or 3) are DELAY(input, time, initial, order);
- SMOOTH/SMOOTH3 (and I forms, SMOOTH N of order 1 or 3) are SMOOTH(input, time, initial, order).

Which of these SD Lab's case format can express is decided later (match.py): a placeholder whose
arguments read only TIME is an outside driver (a measured input); any other is a missing feature.
What cannot be read at all (arrays, macros, external data, ...) is recorded in Model.blocked as
(feature, where), and the model is still read as far as it goes, so every feature a model lacks is
counted.

A stock's INTEG(...) is split into its top-level signed terms. A term that names a flow variable is
that flow: the same flow subtracted from A and added to B is a move A -> B. Any other term is a flow
of its own (to or from outside).
"""

from __future__ import annotations

import math
import re
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import sympy as sp

TIME = sp.Symbol("TIME", real=True)
DELAY = sp.Function("DELAY")
SMOOTH = sp.Function("SMOOTH")
CONTROL = {"initial_time", "final_time", "time_step", "saveper"}
TIME_FNS = {"step", "pulse", "pulse_train", "ramp", "Xpulse", "Xpulse_train", "Xramp", "get_time_value"}
RANDOM = {"random_0_1", "random_uniform", "random_normal", "random_exponential", "random_poisson", "random_triangular",
          "random_lognormal", "random_gamma", "random_beta", "random_binomial", "random_weibull"}

# feature names for what the reader cannot take (the coverage report counts models by these)
F_ARRAYS = "arrays (subscripts)"
F_MACROS = "macros"
F_DATA = "external data (GET XLS / DATA)"
F_FIXED = "fixed delay (DELAY FIXED)"
F_DELAYN = "DELAY N / SMOOTH N of order other than 1 or 3"
F_DELAYT = "a delay or smoothing whose time changes"
F_TREND = "TREND / FORECAST"
F_SAMPLE = "SAMPLE IF TRUE"
F_ALLOCATE = "ALLOCATE"
F_LOOKUPTYPE = "a lookup that steps (not interpolated)"
F_PARSE = "PySD cannot read it"
F_COEF_FLOW = "a flow counted with a coefficient in a stock"
F_NO_STOCKS = "no stocks"


class Blocked(Exception):
    def __init__(self, feature: str, where: str = ""):
        super().__init__(f"{feature}: {where}" if where else feature)
        self.feature, self.where = feature, where


@dataclass
class Flow:
    key: str                      # the flow variable's python name, or "<stock>#<i>" for a bare term
    name: str                     # its name in the model
    src: str | None = None        # stock id it drains (None: outside)
    dst: str | None = None        # stock id it fills
    expr: object = None           # sympy expression, per model time unit
    blocked: list = field(default_factory=list)


@dataclass
class Model:
    path: Path
    t0: float = 0.0
    final: float = 0.0
    dt: float = 1.0
    stocks: dict = field(default_factory=dict)          # id -> {"name", "py", "initial" (float)}
    flows: list = field(default_factory=list)
    lookups: dict = field(default_factory=dict)         # "LK_<n>" -> (xs, ys)
    aux: dict = field(default_factory=dict)             # python name -> sympy expr (inlined), for wrapping
    sinks: list = field(default_factory=list)           # auxiliaries nothing else reads (aux-only models)
    blocked: list = field(default_factory=list)         # (feature, where)


def number(x) -> sp.Rational:
    """A model's number as an exact rational (its decimal as written: 0.3 is 3/10)."""
    f = float(x)
    if not math.isfinite(f):
        raise Blocked("a number that is not finite", repr(x))
    return sp.Rational(repr(f))


def stock_id(name: str, taken: set[str]) -> str:
    """A model name as an SD Lab id: words joined by _, other characters dropped, unique."""
    s = re.sub(r"[^A-Za-z0-9]+", "_", name.strip()).strip("_") or "S"
    if s[0].isdigit():
        s = "S_" + s
    out, i = s, 2
    while out in taken or out.lower() == "outside":
        out, i = f"{s}_{i}", i + 1
    taken.add(out)
    return out


def abstract_model(path: Path):
    """PySD's abstract model of a .mdl, .xmile or .stmx file (read from a copy: PySD writes beside it)."""
    from pysd.translators.vensim.vensim_file import VensimFile
    from pysd.translators.xmile.xmile_file import XmileFile

    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / path.name
        shutil.copy(path, p)
        f = VensimFile(p) if path.suffix.lower() == ".mdl" else XmileFile(p)
        f.parse()
        return f.get_abstract_model()


class _Reader:
    def __init__(self, am, model: Model):
        from pysd.translators.structures import abstract_expressions as ae

        self.ae, self.m = ae, model
        self.macros = {self._py(s.name) for s in am.sections[1:]}
        if len(am.sections) > 1:
            model.blocked.append((F_MACROS, ", ".join(s.name for s in am.sections[1:])))
        self.elements = {}                             # python name -> element
        for el in am.sections[0].elements:
            self.elements[self._py(el.name)] = el
        self.memo: dict = {}
        self.stack: list = []
        self.lookup_ids: dict = {}

    @staticmethod
    def _py(name: str) -> str:
        return name.lower().replace(" ", "_").strip('"')

    # ---- elements ----
    def component(self, py: str):
        el = self.elements.get(py)
        if el is None:
            raise Blocked("a reference PySD did not define", py)
        if len(el.components) != 1 or el.components[0].subscripts[0]:
            raise Blocked(F_ARRAYS, el.name)
        return el, el.components[0]

    def control(self, py: str) -> float:
        _, c = self.component(py)
        v = self.expr(c.ast, py)
        if v.free_symbols:
            raise Blocked("a simulation setting that changes", py)
        return float(v)

    def value(self, py: str):
        """An element as an expression (inlined; a stock is its symbol)."""
        if py in self.m.stocks_py:
            return sp.Symbol(self.m.stocks_py[py], real=True)
        if py in self.memo:
            return self.memo[py]
        if py in self.stack:
            raise Blocked("a loop of auxiliaries without a stock", " -> ".join(self.stack + [py]))
        el, c = self.component(py)
        self.stack.append(py)
        try:
            out = self.expr(c.ast, el.name)
        finally:
            self.stack.pop()
        self.memo[py] = out
        return out

    def lookup(self, key, struct, where: str) -> str:
        ae = self.ae
        if not isinstance(struct, ae.LookupsStructure):
            raise Blocked(F_DATA, where)
        if (struct.type or "interpolate") != "interpolate":
            raise Blocked(F_LOOKUPTYPE, where)
        if key not in self.lookup_ids:
            name = f"LK_{len(self.lookup_ids) + 1}"
            self.lookup_ids[key] = name
            self.m.lookups[name] = ([float(x) for x in struct.x], [float(y) for y in struct.y])
        return self.lookup_ids[key]

    # ---- expressions ----
    def expr(self, node, where: str):
        ae = self.ae
        if isinstance(node, (int, float)) and not isinstance(node, bool):
            return number(node)
        if hasattr(node, "dtype") and getattr(node, "shape", None) == ():          # numpy scalar
            return number(float(node))
        if isinstance(node, ae.ReferenceStructure):
            if node.subscripts is not None:
                raise Blocked(F_ARRAYS, where)
            ref = node.reference.strip('"')
            if ref == "time":
                return TIME
            if ref in CONTROL:
                return number(self.control(ref))
            el = self.elements.get(ref)
            if el is not None and isinstance(el.components[0].ast, ae.LookupsStructure):
                raise Blocked("a lookup read as a value", where)
            return self.value(ref)
        if isinstance(node, ae.ArithmeticStructure):
            return self.arith(node, where)
        if isinstance(node, ae.LogicStructure):
            args = [self.expr(a, where) for a in node.arguments]
            out = args[0]
            for op, b in zip(node.operators, args[1:]):
                out = sp.Function(f"F_cmp_{_OPS.get(op, 'op')}")(out, b)
            if node.operators and node.operators[0] in (":NOT:", "not") and len(args) == 1:
                out = sp.Function("F_cmp_not")(args[0])
            return self.fold(out)
        if isinstance(node, ae.CallStructure):
            fname = node.function.reference.strip('"')
            args = [self.expr(a, where) for a in node.arguments]
            el = self.elements.get(fname)
            if el is not None:                                                     # a lookup called on its argument
                if len(args) != 1:
                    raise Blocked(F_ARRAYS, where)
                return self.fold(sp.Function(self.lookup(fname, el.components[0].ast, el.name))(args[0]))
            if fname == "pi":
                return sp.pi
            if fname in self.macros:
                raise Blocked(F_MACROS, where)
            if fname in TIME_FNS:                                                  # reads TIME without naming it
                return sp.Function(f"F_{fname}")(TIME, *args)
            out = sp.Function(f"F_{fname}")(*args)
            if fname not in RANDOM and not any(a.free_symbols or a.has(DELAY, SMOOTH) for a in args):   # a function of numbers is a number
                from .timefns import evaluate
                try:
                    return number(evaluate(out, 0.0, 1.0, {}))
                except (Blocked, ValueError, ZeroDivisionError, OverflowError, TypeError):
                    return out
            return out
        if isinstance(node, ae.InlineLookupsStructure):
            return self.fold(sp.Function(self.lookup(id(node.lookups), node.lookups, where))(self.expr(node.argument, where)))
        if isinstance(node, ae.GameStructure):
            return self.expr(node.expression, where)
        if isinstance(node, ae.InitialStructure):
            return self.initial_value(self.expr(node.initial, where), where)
        if isinstance(node, ae.DelayStructure):
            return self.stateful(DELAY, node.input, node.delay_time, node.initial, node.order, where)
        if isinstance(node, ae.DelayNStructure):
            return self.stateful(DELAY, node.input, node.delay_time, node.initial, node.order, where)
        if isinstance(node, ae.SmoothStructure):
            return self.stateful(SMOOTH, node.input, node.smooth_time, node.initial, node.order, where)
        if isinstance(node, ae.SmoothNStructure):
            return self.stateful(SMOOTH, node.input, node.smooth_time, node.initial, node.order, where)
        if isinstance(node, ae.DelayFixedStructure):
            raise Blocked(F_FIXED, where)
        if isinstance(node, (ae.TrendStructure, ae.ForecastStructure)):
            raise Blocked(F_TREND, where)
        if isinstance(node, ae.SampleIfTrueStructure):
            raise Blocked(F_SAMPLE, where)
        if isinstance(node, (ae.AllocateAvailableStructure, ae.AllocateByPriorityStructure)):
            raise Blocked(F_ALLOCATE, where)
        if isinstance(node, (ae.DataStructure, ae.GetDataStructure, ae.GetLookupsStructure, ae.GetConstantsStructure)):
            raise Blocked(F_DATA, where)
        if isinstance(node, ae.IntegStructure):
            raise Blocked("a stock inside an expression", where)
        if isinstance(node, ae.LookupsStructure):
            raise Blocked("a lookup read as a value", where)
        if isinstance(node, str):
            raise Blocked(F_PARSE, f"{where}: {node[:40]}")
        if hasattr(node, "shape"):
            raise Blocked(F_ARRAYS, where)
        raise Blocked(f"an equation PySD reads as {type(node).__name__}", where)

    def fold(self, e):
        """A function of numbers (no stock, no TIME) as its number."""
        from .timefns import evaluate

        if e.free_symbols or e.has(DELAY, SMOOTH) or any(type(a).__name__.removeprefix("F_") in RANDOM for a in e.atoms(sp.Function)):
            return e
        try:
            return number(evaluate(e, 0.0, 1.0, self.m.lookups))
        except (Blocked, ValueError, ZeroDivisionError, OverflowError, TypeError):
            return e

    def arith(self, node, where: str):
        args = [self.expr(a, where) for a in node.arguments]
        ops = list(node.operators)
        if ops in (["negative"], ["-"]) and len(args) == 1:
            return -args[0]
        if ops in (["positive"], ["+"]) and len(args) == 1:
            return args[0]
        # precedence: ^ binds first, then * /, then + - (PySD keeps one level per structure, but be safe)
        items = [args[0]]
        pend = []
        for op, a in zip(ops, args[1:]):
            pend.append(op)
            items.append(a)
        for level in (("^",), ("*", "/"), ("+", "-")):
            out_items, out_ops = [items[0]], []
            for op, a in zip(pend, items[1:]):
                if op in level:
                    x = out_items.pop()
                    out_items.append(_apply(op, x, a, where))
                else:
                    out_ops.append(op)
                    out_items.append(a)
            items, pend = out_items, out_ops
        if pend:
            raise Blocked(f"an operator {pend[0]!r}", where)
        return items[0]

    def stateful(self, fn, inp, time, init, order, where: str):
        t = self.expr(time, where)
        n = self.expr(order, where)
        if n.free_symbols or not n.is_number:
            raise Blocked(F_DELAYN, where)
        if int(n) not in (1, 3) or n != int(n):
            raise Blocked(F_DELAYN, where)
        if t.free_symbols:
            raise Blocked(F_DELAYT, where)
        return fn(self.expr(inp, where), t, self.expr(init, where), sp.Integer(int(n)))

    def initial_value(self, e, where: str):
        """INITIAL(x): x at the start (stocks at their initial levels, TIME at the initial time)."""
        from .timefns import evaluate

        e = e.subs({sp.Symbol(s, real=True): v["initial"] for s, v in self.m.stocks.items() if v.get("initial") is not None})
        if e.free_symbols - {TIME}:
            raise Blocked("INITIAL of a stock whose start depends on another", where)
        return number(evaluate(e, self.m.t0, self.m.dt, self.m.lookups))


_OPS = {"=": "eq", "<>": "ne", "<": "lt", "<=": "le", ">": "gt", ">=": "ge", ":AND:": "and", ":OR:": "or", "and": "and", "or": "or"}


def _apply(op: str, a, b, where: str):
    if op == "+":
        return a + b
    if op == "-":
        return a - b
    if op == "*":
        return a * b
    if op == "/":
        if b == 0:
            raise Blocked("division by zero", where)
        return a / b
    if op == "^":
        return sp.Pow(a, b)
    raise Blocked(f"an operator {op!r}", where)


def at_start(e):
    """ACTIVE INITIAL(x, init) as its value while the model initialises: init."""
    return e.replace(lambda a: type(a).__name__ == "F_active_initial", lambda a: a.args[1])


def running(e):
    """ACTIVE INITIAL(x, init) as its value once the model runs: x."""
    return e.replace(lambda a: type(a).__name__ == "F_active_initial", lambda a: a.args[0])


def _terms(node, ae, sign: int = 1):
    """A stock's INTEG argument as its top-level signed terms [(sign, node)]."""
    if isinstance(node, ae.ArithmeticStructure):
        ops = list(node.operators)
        if ops in (["negative"], ["-"]) and len(node.arguments) == 1:
            return _terms(node.arguments[0], ae, -sign)
        if ops and all(o in ("+", "-") for o in ops):
            out = _terms(node.arguments[0], ae, sign)
            for op, a in zip(ops, node.arguments[1:]):
                out += _terms(a, ae, sign if op == "+" else -sign)
            return out
    return [(sign, node)]


def read(path) -> Model:
    """A model file as stocks and flows (sympy rates per model time unit); see the module docstring."""
    from .timefns import evaluate

    path = Path(path)
    m = Model(path=path)
    m.stocks_py = {}                                   # python name -> stock id
    try:
        am = abstract_model(path)
    except Exception as e:                                                           # noqa: BLE001
        m.blocked.append((F_PARSE, f"{type(e).__name__}: {str(e)[:120]}"))
        return m
    r = _Reader(am, m)
    ae = r.ae
    for k, attr in (("initial_time", "t0"), ("final_time", "final"), ("time_step", "dt")):
        try:
            setattr(m, attr, r.control(k))
        except Blocked as b:
            m.blocked.append((b.feature, b.where))
    taken: set[str] = set()
    integs = {}
    for py, el in r.elements.items():
        if py in CONTROL:
            continue
        for c in el.components:
            if isinstance(c.ast, ae.IntegStructure):
                if len(el.components) != 1 or (c.subscripts[0] or []):
                    m.blocked.append((F_ARRAYS, el.name))
                    break
                sid = stock_id(el.name, taken)
                m.stocks_py[py] = sid
                m.stocks[sid] = {"name": el.name, "py": py, "initial": None}
                integs[sid] = c.ast
    # initial levels: each an expression of constants and other stocks' initial levels
    pending = dict(integs)
    for _ in range(len(pending) + 1):
        for sid, integ in list(pending.items()):
            try:
                e = r.expr(integ.initial, m.stocks[sid]["name"])
            except Blocked as b:
                m.blocked.append((b.feature, b.where))
                pending.pop(sid)
                continue
            e = e.subs({sp.Symbol(s, real=True): v["initial"] for s, v in m.stocks.items() if v["initial"] is not None})
            e = at_start(e)
            if e.free_symbols - {TIME}:
                continue
            try:
                m.stocks[sid]["initial"] = float(evaluate(e, m.t0, m.dt, m.lookups))
            except Blocked as b:
                m.blocked.append((b.feature, b.where))
            pending.pop(sid)
    for sid in pending:
        m.blocked.append(("initial levels that depend on each other in a loop", m.stocks[sid]["name"]))
    # flows: the signed terms of each INTEG
    flows: dict[str, Flow] = {}
    ends: dict[str, list] = {}
    for sid, integ in integs.items():
        for i, (sign, node) in enumerate(_terms(integ.flow, ae)):
            ref = node.reference.strip('"') if isinstance(node, ae.ReferenceStructure) else None
            if ref is not None and node.subscripts is None and ref in r.elements and ref not in r.m.stocks_py and ref not in CONTROL:
                key, name = ref, r.elements[ref].name
            else:
                key, name = f"{sid}#{i + 1}", f"{m.stocks[sid]['name']} term {i + 1}"
            f = flows.setdefault(key, Flow(key=key, name=name))
            ends.setdefault(key, []).append((sign, sid))
            if f.expr is None:
                try:
                    f.expr = r.expr(node, name)
                except Blocked as b:
                    f.blocked.append((b.feature, b.where))
                    f.expr = sp.nan
    # a flow variable subtracted from A and added to B is a move; one used by more stocks is several
    # flows with the same rate (sources paired with destinations in order, the rest to or from outside)
    out = []
    for key, f in flows.items():
        srcs = [s for g, s in ends[key] if g < 0]
        dsts = [s for g, s in ends[key] if g > 0]
        pairs = [(srcs[i] if i < len(srcs) else None, dsts[i] if i < len(dsts) else None) for i in range(max(len(srcs), len(dsts)))]
        for j, (a, b) in enumerate(pairs):
            name = f.name if len(pairs) == 1 else f"{f.name} {j + 1}"
            out.append(Flow(key=key if j == 0 else f"{key}#{j + 1}", name=name, src=a, dst=b, expr=f.expr, blocked=list(f.blocked)))
    m.flows = out
    for f in flows.values():
        m.blocked += f.blocked
    # auxiliaries nothing reads (for a model without stocks: what a one-function test shows)
    if not integs:
        read_by = _references(am, ae)
        for py, el in r.elements.items():
            if py in CONTROL or py in read_by or isinstance(el.components[0].ast, ae.LookupsStructure):
                continue
            try:
                m.aux[py] = r.value(py)
                m.sinks.append(py)
            except Blocked as b:
                m.blocked.append((b.feature, b.where))
    m.element_names = {py: el.name for py, el in r.elements.items()}
    m.aux_values = {py: v for py, v in r.memo.items() if py not in CONTROL}
    return m


def _references(am, ae) -> set[str]:
    out: set[str] = set()

    def walk(n):
        if isinstance(n, ae.ReferenceStructure):
            out.add(n.reference.strip('"'))
            return
        if isinstance(n, ae.CallStructure):
            out.add(n.function.reference.strip('"'))
        if hasattr(n, "__dataclass_fields__"):
            for k in n.__dataclass_fields__:
                walk(getattr(n, k))
        elif isinstance(n, (list, tuple)):
            for x in n:
                walk(x)

    for el in am.sections[0].elements:
        for c in el.components:
            walk(c.ast)
    return out
