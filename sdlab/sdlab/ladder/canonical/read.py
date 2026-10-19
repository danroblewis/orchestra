"""Read a Vensim (.mdl) or XMILE (.xmile, .stmx) model through PySD's parser into stocks and flows
whose rates are sympy expressions (needs the optional packages pysd and sympy).

    read(path) -> Model

PySD 3 parses a model into an abstract model (pysd.translators: sections of elements, each element's
equation a tree of ArithmeticStructure, ReferenceStructure, CallStructure, IntegStructure, ...). Here
every auxiliary and constant is inlined, so each flow's rate is an expression in the stocks, the
symbol TIME and placeholders:

- a call (MIN, SQRT, STEP, IF THEN ELSE, a comparison, ...) is an undefined sympy function F_<name>;
- a lookup is LK_<n>(argument), its points in Model.lookups;
- DELAY1/DELAY3/DELAY N (and I forms) of any whole order n are DELAY(input, time, initial, n);
- SMOOTH/SMOOTH3/SMOOTH N (and I forms) of any whole order n are SMOOTH(input, time, initial, n).

Arrays, macros and external data are read away (added for queue item 2c):

- a subscripted variable is flattened, one variable per element (arrays.py: PySD's SubscriptManager
  reads the ranges, subranges, copies and mappings; SUM / PROD / VMIN / VMAX over x[A!] are written
  out element by element; a range read as a number is the element's position). A subscripted stock
  is one stock per element, its id <stock>__<element>[__<element>...] and its name PySD's output
  column, Stock[a,b];
- a macro call is inlined: the macro's section is read with its parameters bound to the call's
  arguments, and a stock inside it becomes a stock of the model per call (measured through an
  auxiliary of the model that equals it, else hidden);
- GET XLS / GET DIRECT CONSTANTS, DATA and LOOKUPS are read through PySD itself (external.py): a
  constant is its number, a data series a lookup of TIME through its values at every Euler step (a
  measured input), an external lookup a lookup table.

Which of these SD Lab's case format can express is decided later (match.py): a placeholder whose
arguments read only TIME is an outside driver (a measured input); any other is a missing feature.
What cannot be read (VECTOR SELECT and other vector functions, DELAY FIXED, ...) is recorded in
Model.blocked as (feature, where), and the model is still read as far as it goes, so every feature a
model lacks is counted.

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

from .arrays import F_ARRAYS, Subscripts, label

TIME = sp.Symbol("TIME", real=True)
DELAY = sp.Function("DELAY")
SMOOTH = sp.Function("SMOOTH")
CONTROL = {"initial_time", "final_time", "time_step", "saveper"}
TIME_FNS = {"step", "pulse", "pulse_train", "ramp", "Xpulse", "Xpulse_train", "Xramp", "get_time_value"}
RANDOM = {"random_0_1", "random_uniform", "random_normal", "random_exponential", "random_poisson", "random_triangular",
          "random_lognormal", "random_gamma", "random_beta", "random_binomial", "random_weibull"}

# feature names for what the reader cannot take (the coverage report counts models by these)
F_VECTOR = "vector and matrix functions (VECTOR SELECT, VECTOR ELM MAP, ...)"
F_MACROS = "macros"
F_DATA = "external data (GET XLS / DATA)"
F_FIXED = "fixed delay (DELAY FIXED)"
F_DELAYN = "DELAY N / SMOOTH N of an order that is not a whole number"
F_DELAYN_T = "a DELAY N / SMOOTH N whose order changes"
F_DATA_MISSING = "external data in a file that is not there"
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


def stock_id(name: str, taken: set[str], keep: bool = False) -> str:
    """A model name as an SD Lab id: words joined by _, other characters dropped, unique (keep: the
    name is an id already)."""
    s = name if keep else re.sub(r"[^A-Za-z0-9]+", "_", name.strip()).strip("_") or "S"
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
    """Reads one section's equations: the model's own (the main reader), or one call of a macro (a
    reader of the macro's section whose parameters are the call's arguments, sharing the main
    reader's subscripts, lookups and new stocks)."""

    def __init__(self, am, model: Model, root: "_Reader | None" = None, section=None, params: dict | None = None,
                 prefix: str = ""):
        from pysd.translators.structures import abstract_expressions as ae

        self.ae, self.m = ae, model
        self.root = root or self
        section = section if section is not None else am.sections[0]
        if root is None:
            self.am = am
            self.macros = {self._py(s.name): s for s in am.sections[1:]}
            self.lookup_ids: dict = {}
            self.pending: list = []                    # stocks met inside macro calls: (reader, sid, integ, comp, coord, binding)
            self.calls = 0
            self.external = None
            try:
                self.subs = Subscripts(am.sections[0], model.path.parent)
            except Exception as e:                                                   # noqa: BLE001
                self.subs = None
                model.blocked.append((F_ARRAYS, f"PySD cannot read the subscript ranges: {str(e)[:80]}"))
        self.elements = {self._py(el.name): el for el in section.elements}
        self.params = params or {}
        self.prefix = prefix
        self.stocks_py: dict = model.stocks_py if root is None else {}   # (python name, coord) -> stock id
        self.memo: dict = {}
        self.stack: list = []
        self.env: dict = {}                            # range name -> element, in the equation being read
        self.ctx = None                                # (element, component, coord) of that equation

    @staticmethod
    def _py(name: str) -> str:
        return name.lower().replace(" ", "_").strip('"')

    # ---- elements ----
    def element(self, py: str):
        el = self.elements.get(py)
        if el is None:
            raise Blocked("a reference PySD did not define", py)
        return el

    def control(self, py: str) -> float:
        if self.root is not self:
            return self.root.control(py)
        el = self.element(py)
        if len(el.components) != 1 or el.components[0].subscripts[0]:
            raise Blocked(F_ARRAYS, el.name)
        v = self.expr(el.components[0].ast, py)
        if v.free_symbols:
            raise Blocked("a simulation setting that changes", py)
        return float(v)

    def coords(self, el) -> list[tuple]:
        if not any(c.subscripts[0] for c in el.components):
            return [()]
        if self.root.subs is None:
            raise Blocked(F_ARRAYS, el.name)
        return self.root.subs.coords(el)

    def instance(self, el, coord: tuple):
        """(component, binding) of one instance of an element."""
        if coord == ():
            if len(el.components) != 1 or el.components[0].subscripts[0]:
                raise Blocked(F_ARRAYS, f"{el.name}: read without its subscripts")
            return el.components[0], {}
        comp, binding = self.root.subs.instance(el, coord)
        if comp is None:
            raise Blocked(F_ARRAYS, f"{label(el.name, coord)} is not defined")
        return comp, binding

    def coord_of(self, el, subscripts) -> tuple:
        """The instance a reference names: its subscripts resolved under the current binding, or (none
        written) the element's own dimensions resolved the same way."""
        if self.coords(el) == [()]:
            if subscripts:
                raise Blocked(F_ARRAYS, f"{el.name}: subscripts on a variable without them")
            return ()
        subs = self.root.subs
        names = list(subscripts) if subscripts else subs.dims(el)
        coord = []
        for s in names:
            e = subs.resolve(s, self.env)
            if e is None:
                raise Blocked(F_ARRAYS, f"{el.name}[{s}]: a whole range where one element is meant (an array operation)")
            coord.append(e)
        coord = tuple(coord)
        if coord not in subs.coords(el):
            raise Blocked(F_ARRAYS, f"{label(el.name, coord)}: not an instance of {el.name}")
        return coord

    def within(self, el, comp, coord: tuple, binding: dict, fn):
        """fn() with the binding and context of one instance's equation."""
        saved = self.env, self.ctx
        self.env, self.ctx = dict(binding), (el, comp, coord)
        try:
            return fn()
        finally:
            self.env, self.ctx = saved

    def value(self, py: str, coord: tuple | None = None):
        """An element's instance as an expression (inlined; a stock is its symbol)."""
        if py in self.params:
            return self.params[py]
        el = self.element(py)
        if coord is None:
            coord = self.coord_of(el, None)
        key = (py, coord)
        if key in self.stocks_py:
            return sp.Symbol(self.stocks_py[key], real=True)
        if key in self.memo:
            return self.memo[key]
        if key in self.stack:
            raise Blocked("a loop of auxiliaries without a stock", " -> ".join(str(k[0]) for k in self.stack + [key]))
        comp, binding = self.instance(el, coord)
        self.stack.append(key)
        try:
            out = self.within(el, comp, coord, binding, lambda: self.expr(comp.ast, label(el.name, coord)))
        finally:
            self.stack.pop()
        self.memo[key] = out
        return out

    def lookup(self, key, struct, where: str, py: str = "", coord: tuple = ()) -> str:
        ae = self.ae
        if isinstance(struct, ae.GetLookupsStructure):
            points = self.ext_lookup(py, coord, where)
        elif not isinstance(struct, ae.LookupsStructure):
            raise Blocked(F_DATA, where)
        elif (struct.type or "interpolate") != "interpolate":
            raise Blocked(F_LOOKUPTYPE, where)
        else:
            points = ([float(x) for x in struct.x], [float(y) for y in struct.y])
        ids = self.root.lookup_ids
        key = (self.prefix, key, coord)
        if key not in ids:
            name = f"LK_{len(ids) + 1}"
            ids[key] = name
            self.m.lookups[name] = points
        return ids[key]

    # ---- external data and macros ----
    def ext(self):
        if self.root.external is None:
            from .external import External
            self.root.external = External(self.m.path)
            self.m.external = True
        return self.root.external

    def ext_lookup(self, py: str, coord: tuple, where: str):
        try:
            return self.ext().lookup(py, coord)
        except Exception as e:                                                       # noqa: BLE001
            raise _data_blocked(e, where) from None

    def ext_value(self, node, where: str):
        """GET ... CONSTANTS as its number; GET ... DATA as a lookup of TIME through PySD's values at
        every Euler step (an outside driver: a measured input)."""
        if self.ctx is None or self.root is not self:
            raise Blocked(F_DATA, where)
        el, _comp, coord = self.ctx
        m = self.m
        n = math.floor((m.final - m.t0) / m.dt + 1e-9)
        times = [m.t0 + k * m.dt for k in range(n + 1)]
        try:
            vals = self.ext().values(el.name, coord, times)
        except Exception as e:                                                       # noqa: BLE001
            raise _data_blocked(e, where) from None
        if isinstance(node, self.ae.GetConstantsStructure):
            return number(vals[0])
        if not all(math.isfinite(v) for v in vals):
            raise Blocked(F_DATA, f"{where}: missing values")
        if len(set(vals)) == 1:
            return number(vals[0])
        name = f"LK_{len(self.root.lookup_ids) + 1}"
        self.root.lookup_ids[("data", el.name, coord)] = name
        m.lookups[name] = (times, vals)
        return sp.Function(name)(TIME)

    def macro(self, name: str, args: list, where: str):
        """A macro call inlined: its section read with its parameters bound to the arguments. Each call
        is its own copy: a stock inside the macro becomes a stock of the model per call."""
        sec = self.root.macros[name]
        if sec.returns:
            raise Blocked(F_MACROS, f"{where}: a macro with more than one output")
        if len(args) != len(sec.params):
            raise Blocked(F_MACROS, f"{where}: {name} takes {len(sec.params)} arguments")
        if any(isinstance(a, list) for a in args):
            raise Blocked(F_ARRAYS, where)
        self.root.calls += 1
        prefix = f"{name}_{self.root.calls}"
        sub = _Reader(self.root.am, self.m, root=self.root, section=sec,
                      params={self._py(p): a for p, a in zip(sec.params, args)}, prefix=prefix)
        for py, el in sub.elements.items():
            for comp in el.components:
                if isinstance(comp.ast, self.ae.IntegStructure):
                    if comp.subscripts[0]:
                        raise Blocked(F_ARRAYS, f"{where}: a subscripted stock in a macro")
                    sid = stock_id(f"{prefix} {el.name}", self.m.taken)
                    sub.stocks_py[(py, ())] = sid
                    self.m.stocks[sid] = {"name": f"{name}: {el.name}", "py": None, "macro": True, "initial": None}
                    self.root.pending.append((sub, sid, comp.ast, el, comp, (), {}))
        if name not in sub.elements:
            raise Blocked(F_MACROS, f"{where}: {name} has no equation for its output")
        return sub.value(name, ())

    def aggregate(self, fname: str, arg, where: str):
        """SUM / PROD / VMIN / VMAX over the ranges marked ! in the argument, written out element by element."""
        from itertools import product

        if self.root.subs is None:
            raise Blocked(F_ARRAYS, where)
        subs = self.root.subs
        ranges = subs.ranges
        bangs = list(dict.fromkeys(_bang_subscripts(arg, self.ae)))
        if any(b[:-1] not in ranges for b in bangs):
            raise Blocked(F_ARRAYS, where)
        over = [ranges[b[:-1]] for b in bangs]
        if not bangs:                          # XMILE's MIN(x) / SUM(x): over every range the argument leaves free
            for ref, written in _references_in(arg, self.ae):
                el = self.elements.get(ref)
                names = written if written else (subs.dims(el) if el is not None else [])
                bangs += [s for s in names if s in ranges and subs.resolve(s, self.env) is None and s not in bangs]
            over = [ranges[b] for b in bangs]
        if not bangs:
            raise Blocked(F_ARRAYS, f"{where}: {fname.upper()} of a whole array")
        vals = []
        saved = self.env
        try:
            for combo in product(*over):
                self.env = {**saved, **dict(zip(bangs, combo))}
                vals.append(self.expr(arg, where))
        finally:
            self.env = saved
        if fname == "sum":
            return self.fold(sp.Add(*vals))
        if fname == "prod":
            return self.fold(sp.Mul(*vals))
        out = vals[0]
        for v in vals[1:]:
            out = sp.Function("F_min" if fname in ("vmin", "min") else "F_max")(out, v)
        return self.fold(out)

    # ---- expressions ----
    def expr(self, node, where: str):
        ae = self.ae
        if isinstance(node, (int, float)) and not isinstance(node, bool):
            return number(node)
        if hasattr(node, "dtype") and getattr(node, "shape", None) == ():          # numpy scalar
            return number(float(node))
        if hasattr(node, "shape"):                                                 # a numeric array definition
            if self.ctx is None or self.root.subs is None:
                raise Blocked(F_ARRAYS, where)
            v = self.root.subs.array_value(node, self.ctx[1], self.ctx[2])
            if v is None:
                raise Blocked(F_ARRAYS, f"{where}: an array of numbers of another shape")
            return number(v)
        if isinstance(node, ae.ReferenceStructure):
            ref = node.reference.strip('"')
            subscripts = node.subscripts.subscripts if node.subscripts is not None else None
            if ref == "time":
                return TIME
            if ref in CONTROL:
                return number(self.control(ref))
            if ref in self.params:
                if subscripts:
                    raise Blocked(F_ARRAYS, f"{where}: a subscripted macro argument")
                return self.params[ref]
            if self.root.subs is not None and ref not in self.elements:          # a range or element read as a number
                pos = self.root.subs.number(ref, self.env, self._py)
                if pos is not None:
                    return sp.Integer(pos)
                if any(self._py(name) == ref for name in self.root.subs.ranges):
                    raise Blocked(F_ARRAYS, f"{where}: the range {ref} read as a value outside its definition")
            el = self.element(ref)
            if isinstance(el.components[0].ast, (ae.LookupsStructure, ae.GetLookupsStructure)):
                raise Blocked("a lookup read as a value", where)
            return self.value(ref, self.coord_of(el, subscripts))
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
            fsubs = node.function.subscripts.subscripts if node.function.subscripts is not None else None
            if fname.removesuffix("_xmile") in AGGREGATES or (fname in ("min", "max") and len(node.arguments) == 1):
                return self.aggregate(fname.removesuffix("_xmile"), node.arguments[0], where)
            if fname in VECTOR_FNS:
                raise Blocked(F_VECTOR, f"{where}: {fname.upper()}")
            if fname == "elmcount":
                return self.elmcount(node.arguments, where)
            args = [self.expr(a, where) for a in node.arguments]
            el = self.elements.get(fname)
            if el is not None:                                                     # a lookup called on its argument
                if len(args) != 1:
                    raise Blocked(F_ARRAYS, where)
                coord = self.coord_of(el, fsubs)
                comp, _ = self.instance(el, coord)
                return self.fold(sp.Function(self.lookup(fname, comp.ast, el.name, fname, coord))(args[0]))
            if fname == "pi":
                return sp.pi
            if fname in self.root.macros:
                return self.macro(fname, args, where)
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
        if isinstance(node, (ae.GetDataStructure, ae.GetConstantsStructure)):
            return self.ext_value(node, where)
        if isinstance(node, (ae.DataStructure, ae.GetLookupsStructure)):
            raise Blocked(F_DATA, where)
        if isinstance(node, ae.IntegStructure):
            raise Blocked("a stock inside an expression", where)
        if isinstance(node, ae.LookupsStructure):
            raise Blocked("a lookup read as a value", where)
        if isinstance(node, str):
            raise Blocked(F_PARSE, f"{where}: {node[:40]}")
        raise Blocked(f"an equation PySD reads as {type(node).__name__}", where)

    def elmcount(self, args, where: str):
        """ELMCOUNT(range): the number of its elements."""
        subs = self.root.subs
        if len(args) == 1 and isinstance(args[0], self.ae.ReferenceStructure) and subs is not None:
            ref = args[0].reference.strip('"')
            for name, elems in subs.ranges.items():
                if self._py(name) == ref or name == ref:
                    return sp.Integer(len(elems))
        raise Blocked(F_VECTOR, f"{where}: ELMCOUNT")

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
        """DELAY / SMOOTH of any whole order n (pysd_import writes n hidden stocks)."""
        t = self.expr(time, where)
        n = self.expr(order, where)
        if n.free_symbols:
            raise Blocked(F_DELAYN_T, where)
        if not n.is_number or n != int(n) or int(n) < 1:
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


def _data_blocked(e: Exception, where: str) -> Blocked:
    missing = isinstance(e, FileNotFoundError) or "FileNotFound" in type(e).__name__ or "No such file" in str(e)
    return Blocked(F_DATA_MISSING if missing else F_DATA, f"{where}: {type(e).__name__}: {str(e)[:60]}")


AGGREGATES = {"sum", "prod", "vmin", "vmax"}
VECTOR_FNS = {"vector_select", "vector_elm_map", "vector_sort_order", "vector_rank", "vector_reorder", "invert_matrix",
              "vector_lookup"}


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
        out = sp.Pow(a, b)
        if out.is_number and not out.is_Rational and not out.has(sp.pi, sp.E):    # a power of numbers: its number
            try:
                return number(complex(out).real if complex(out).imag == 0 else float("nan"))
            except (TypeError, ValueError, OverflowError):
                return out
        return out
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


def _bang_subscripts(node, ae) -> list[str]:
    """The subscripts marked ! (SUM(x[A!])) in an expression, in order."""
    out: list[str] = []

    def walk(n):
        if isinstance(n, ae.ReferenceStructure):
            if n.subscripts is not None:
                out.extend(s for s in n.subscripts.subscripts if s.endswith("!"))
            return
        if hasattr(n, "__dataclass_fields__"):
            for k in n.__dataclass_fields__:
                walk(getattr(n, k))
        elif isinstance(n, (list, tuple)):
            for x in n:
                walk(x)

    walk(node)
    return out


def _references_in(node, ae) -> list[tuple[str, list]]:
    """(reference, its written subscripts) for every variable an expression reads."""
    out: list = []

    def walk(n):
        if isinstance(n, ae.ReferenceStructure):
            out.append((n.reference.strip('"'), list(n.subscripts.subscripts) if n.subscripts is not None else []))
            return
        if isinstance(n, ae.CallStructure):
            for a in n.arguments:
                walk(a)
            return
        if hasattr(n, "__dataclass_fields__"):
            for k in n.__dataclass_fields__:
                walk(getattr(n, k))
        elif isinstance(n, (list, tuple)):
            for x in n:
                walk(x)

    walk(node)
    return out


def _stock_name(name: str, coord: tuple, taken: set[str]) -> str:
    """A stock's id; an element of a subscripted stock is <stock>__<element>[__<element>...]."""
    if not coord:
        return stock_id(name, taken)
    word = lambda s: re.sub(r"[^A-Za-z0-9]+", "_", s.strip()).strip("_") or "x"  # noqa: E731
    return stock_id("__".join([word(name)] + [word(e) for e in coord]), taken, keep=True)


def _initials(m: Model, batch: list) -> None:
    """Initial levels: each an expression of constants and other stocks' initial levels."""
    from .timefns import evaluate

    pending = list(batch)
    for _ in range(len(pending) + 1):
        for item in list(pending):
            rd, sid, integ, el, comp, coord, binding = item
            try:
                e = rd.within(el, comp, coord, binding, lambda: rd.expr(integ.initial, m.stocks[sid]["name"]))
            except Blocked as b:
                m.blocked.append((b.feature, b.where))
                pending.remove(item)
                continue
            e = e.subs({sp.Symbol(s, real=True): v["initial"] for s, v in m.stocks.items() if v["initial"] is not None})
            e = at_start(e)
            if e.free_symbols - {TIME}:
                continue
            try:
                m.stocks[sid]["initial"] = float(evaluate(e, m.t0, m.dt, m.lookups))
            except Blocked as b:
                m.blocked.append((b.feature, b.where))
            pending.remove(item)
    for item in pending:
        m.blocked.append(("initial levels that depend on each other in a loop", m.stocks[item[1]]["name"]))


def _flow_terms(m: Model, batch: list, flows: dict, ends: dict) -> None:
    """The signed terms of each INTEG: a term that names a flow variable (instance) is that flow."""
    for rd, sid, integ, el, comp, coord, binding in batch:
        ae = rd.ae

        def terms():
            return [(sign, node, _term_flow(rd, node, ae)) for sign, node in _terms(integ.flow, ae)]

        try:
            items = rd.within(el, comp, coord, binding, terms)
        except Blocked as b:
            m.blocked.append((b.feature, b.where))
            continue
        for i, (sign, node, named) in enumerate(items):
            if named is not None:
                key, name, fcoord, fel = named
            else:
                key, name, fcoord, fel = f"{sid}#{i + 1}", f"{m.stocks[sid]['name']} term {i + 1}", None, None
            f = flows.setdefault(key, Flow(key=key, name=name))
            ends.setdefault(key, []).append((sign, sid))
            if f.expr is None:
                try:
                    if fel is not None:
                        f.expr = rd.value(rd._py(fel.name), fcoord)
                    else:
                        f.expr = rd.within(el, comp, coord, binding, lambda node=node, name=name: rd.expr(node, name))
                except Blocked as b:
                    f.blocked.append((b.feature, b.where))
                    f.expr = sp.nan


def _term_flow(rd, node, ae):
    """(key, name, coord, element) when a stock's term names a flow variable, else None."""
    if not isinstance(node, ae.ReferenceStructure):
        return None
    ref = node.reference.strip('"')
    if ref not in rd.elements or ref in CONTROL or ref in rd.params:
        return None
    el = rd.elements[ref]
    if isinstance(el.components[0].ast, (ae.LookupsStructure, ae.GetLookupsStructure)):
        return None
    coord = rd.coord_of(el, node.subscripts.subscripts if node.subscripts is not None else None)
    if (ref, coord) in rd.stocks_py:
        return None
    key = (f"{rd.prefix}:" if rd.prefix else "") + label(ref, coord)
    return key, label(el.name, coord), coord, el


def read(path) -> Model:
    """A model file as stocks and flows (sympy rates per model time unit); see the module docstring."""
    path = Path(path)
    m = Model(path=path)
    m.stocks_py = {}                                   # (python name, coord) -> stock id
    m.taken = set()
    m.external = False
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
    batch = []
    for py, el in r.elements.items():
        if py in CONTROL or not any(isinstance(c.ast, ae.IntegStructure) for c in el.components):
            continue
        try:
            coords = r.coords(el)
        except Blocked as b:
            m.blocked.append((b.feature, b.where))
            continue
        for coord in coords:
            comp, binding = r.instance(el, coord)
            if not isinstance(comp.ast, ae.IntegStructure):
                m.blocked.append((F_ARRAYS, f"{label(el.name, coord)}: a stock with an element defined as an auxiliary"))
                continue
            sid = _stock_name(el.name, coord, m.taken)
            m.stocks_py[(py, coord)] = sid
            m.stocks[sid] = {"name": label(el.name, coord), "py": py, "initial": None}
            batch.append((r, sid, comp.ast, el, comp, coord, binding))
    _initials(m, batch)
    flows: dict[str, Flow] = {}
    ends: dict[str, list] = {}
    _flow_terms(m, batch, flows, ends)
    # auxiliaries nothing reads (for a model without stocks: what a one-function test shows)
    if not batch:
        read_by = _references(am, ae)
        for py, el in r.elements.items():
            if py in CONTROL or py in read_by or isinstance(el.components[0].ast, (ae.LookupsStructure, ae.GetLookupsStructure)):
                continue
            try:
                for coord in r.coords(el):
                    key = label(py, coord)
                    m.aux[key] = r.value(py, coord)
                    m.sinks.append(key)
            except Blocked as b:
                m.blocked.append((b.feature, b.where))
    while r.pending:                                   # stocks inside macro calls
        more, r.pending = r.pending, []
        _initials(m, more)
        _flow_terms(m, more, flows, ends)
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
    m.element_names = {label(py, c): label(el.name, c) for py, el in r.elements.items() for c in _safe_coords(r, el)}
    m.aux_values = {label(py, c): v for (py, c), v in r.memo.items() if py not in CONTROL}
    # a stock inside a macro is measured through an auxiliary of the model that equals it, if any
    for sid, s in m.stocks.items():
        if s.get("macro"):
            sym = sp.Symbol(sid, real=True)
            col = next((m.element_names[k] for k, v in m.aux_values.items() if v == sym and k in m.element_names), None)
            if col is None:
                s["hidden"] = True
            else:
                s["column"] = col
    if r.external is not None:
        r.external.close()
    return m


def _safe_coords(r, el) -> list[tuple]:
    try:
        return r.coords(el)
    except Blocked:
        return [()]


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
