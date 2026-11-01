"""The equation language: one written form for a flow's rate, read by every machine and by
Orchestra alike (goal G5; ``docs`` in USING_ORCHESTRA.md §5.9).

A rate is an expression in Python's syntax, per the model's time unit:

- **numbers**: ``2``, ``0.5``, ``1e-3``;
- **names**: a stock's id (its level), a measured input's name (its value), or one of the
  equation's **parameters** (named numbers given beside the text, ``{"k": 0.4}``). A name that is
  not a plain identifier, or that is both a stock and an input, is written ``stock("id")`` or
  ``input("name")``;
- **operators**: ``+ - * / **``, unary ``-``, parentheses, and one comparison (``<``, ``<=``,
  ``>``, ``>=``, ``==``, ``!=``), which is 1 when true and 0 when false;
- **functions**: ``min(a, b, …)``, ``max(a, b, …)``, ``abs(x)``, ``exp(x)``, ``log(x)`` (natural),
  ``sqrt(x)``, ``clip(x, lo, hi)``, SD Lab's (Vensim's) ``ceil``, ``floor``, ``integer``, ``power``,
  ``modulo``, ``quantum``, ``ln``, ``log10``, the trigonometric functions, ``xidz``, ``and_``,
  ``or_`` and ``not_``, ``if_then_else(c, a, b)`` (``a`` where ``c`` is not 0),
  ``zidz(a, b)`` (``a / b``, or 0 where ``|b|`` is under 1e-9), ``lookup(x, [[x0, y0], …])``
  (linear between the points, held beyond the ends), ``smooth(x, tau)`` (first-order exponential
  smoothing of ``x`` over ``tau`` time units, starting at ``x``), ``delay(x, tau)`` (``x`` as it
  was ``tau`` time units earlier; its first value before that), and ``observed()`` (the flow's own
  measured rate: in a replay what its counter counted, in a forward run its mean over the last ten
  minutes; a flow with no equation is ``observed()``).

What the simulator does with a rate: a rate below 0 is 0 (a flow moves material one way), a rate
that is not a number (``log(0)``, ``0/0``) is 0 and reported, and a stock's outflows share what it
holds. **Units are not checked**: a rate is whatever the numbers make it, per the model's time unit.

The text is parsed with ``ast`` into a tree of the nodes above and nothing else, and compiled into
numpy closures: nothing is ever passed to ``eval``. Names are checked against the model when the
equation is parsed, and the parse reports what it reads (stocks, inputs, parameters, functions)."""

from __future__ import annotations

import ast
import math
import re
from dataclasses import dataclass, field

MAX_TEXT = 4000
MAX_NODES = 600
MAX_PARAMS = 64
MAX_POINTS = 256
SMALL = 1e-9
IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

FUNCTIONS = {
    "min": (1, None, "the least of its arguments"),
    "max": (1, None, "the greatest of its arguments"),
    "abs": (1, 1, "absolute value"),
    "exp": (1, 1, "e to the power x"),
    "log": (1, 1, "natural logarithm"),
    "sqrt": (1, 1, "square root"),
    "clip": (3, 3, "x held within [lo, hi]"),
    "if_then_else": (3, 3, "a where c is not 0, else b"),
    "zidz": (2, 2, "a / b, or 0 where |b| < 1e-9"),
    "lookup": (2, 2, "linear between the points [[x0, y0], ...], held beyond the ends"),
    "smooth": (2, 2, "first-order exponential smoothing of x over tau time units"),
    "delay": (2, 2, "x as it was tau time units earlier"),
    "observed": (0, 0, "the flow's own measured rate"),
    "ceil": (1, 1, "the least whole number not below x"),
    "floor": (1, 1, "the greatest whole number not above x"),
    "integer": (1, 1, "x without its fraction (towards 0)"),
    "power": (2, 2, "a to the power b"),
    "modulo": (2, 2, "a - quantum(a, b)"),
    "quantum": (2, 2, "b times integer(a / b), or a where b < 1e-6"),
    "ln": (1, 1, "natural logarithm"),
    "log10": (1, 1, "logarithm to base 10"),
    "sin": (1, 1, "sine"), "cos": (1, 1, "cosine"), "tan": (1, 1, "tangent"),
    "arcsin": (1, 1, "inverse sine"), "arccos": (1, 1, "inverse cosine"), "arctan": (1, 1, "inverse tangent"),
    "sinh": (1, 1, "hyperbolic sine"), "cosh": (1, 1, "hyperbolic cosine"), "tanh": (1, 1, "hyperbolic tangent"),
    "xidz": (3, 3, "a / b, or x where |b| < 1e-6"),
    "and_": (1, None, "1 where every argument is not 0"),
    "or_": (1, None, "1 where any argument is not 0"),
    "not_": (1, 1, "1 where x is 0"),
    "stock": (1, 1, "a stock's level, by an id that is not a plain name"),
    "input": (1, 1, "a measured input's value, by a name that is not a plain name"),
}
STATEFUL = ("smooth", "delay")
COMPARE = {ast.Lt: "<", ast.LtE: "<=", ast.Gt: ">", ast.GtE: ">=", ast.Eq: "==", ast.NotEq: "!="}
BINARY = {ast.Add: "+", ast.Sub: "-", ast.Mult: "*", ast.Div: "/", ast.Pow: "**"}


class EquationError(ValueError):
    """An equation that does not parse, reads something unknown, or uses something not allowed."""


@dataclass
class Parsed:
    """An equation checked against the names it may read."""

    text: str
    tree: ast.Expression
    params: dict[str, float]
    stocks: list[str] = field(default_factory=list)
    inputs: list[str] = field(default_factory=list)
    functions: list[str] = field(default_factory=list)

    @property
    def observed(self) -> bool:
        return "observed" in self.functions

    def reads(self) -> list[str]:
        """What it reads, as ``Equation.inputs`` records it: stock ids, and ``input:<name>``."""
        return [*self.stocks, *(f"input:{x}" for x in self.inputs)]

    def describe(self) -> dict:
        return {"equation": self.text, "params": dict(self.params), "reads": {"stocks": list(self.stocks), "inputs": list(self.inputs),
                "params": sorted(self.params), "functions": list(self.functions)}}


def _number(v, what: str) -> float:
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        raise EquationError(f"{what} must be a finite number, not {v!r}")
    return float(v)


def check_params(params) -> dict[str, float]:
    if params is None:
        return {}
    if not isinstance(params, dict):
        raise EquationError(f"params are an object of names and numbers, not {params!r}")
    if len(params) > MAX_PARAMS:
        raise EquationError(f"at most {MAX_PARAMS} parameters")
    out = {}
    for k, v in params.items():
        if not isinstance(k, str) or not IDENT.match(k) or k in FUNCTIONS:
            raise EquationError(f"parameter {k!r}: a parameter's name is a plain name (letters, digits, _), not a function's")
        out[k] = _number(v, f"parameter {k}")
    return out


def parse(text, *, stocks=(), inputs=(), params=None) -> Parsed:
    """The equation ``text`` checked: its syntax, and every name it reads among ``stocks`` (ids),
    ``inputs`` (names) and ``params`` (``{name: number}``). Raises EquationError saying what is
    wrong. Every parameter given must be read."""
    if not isinstance(text, str) or not text.strip():
        raise EquationError("an equation is a non-empty string, e.g. \"k * waiting\"")
    if len(text) > MAX_TEXT:
        raise EquationError(f"an equation is at most {MAX_TEXT} characters")
    p = check_params(params)
    stocks, inputs = set(stocks), set(inputs)
    try:
        tree = ast.parse(text.strip(), mode="eval")
    except SyntaxError as e:
        raise EquationError(f"{text.strip()!r} does not parse: {e.msg} at column {e.offset}") from None
    out = Parsed(text.strip(), tree, p)
    used: set[str] = set()
    count = [0]

    def name(n: str):
        if n in p:
            if n in stocks or n in inputs:
                raise EquationError(f"parameter {n} has the name of a {'stock' if n in stocks else 'measured input'}: rename it")
            used.add(n)
            return
        if n in stocks and n in inputs:
            raise EquationError(f"{n} is both a stock and an input: write stock(\"{n}\") or input(\"{n}\")")
        if n in stocks:
            _add(out.stocks, n)
        elif n in inputs:
            _add(out.inputs, n)
        else:
            raise EquationError(f"unknown name {n}: not a stock ({_some(stocks)}), a measured input ({_some(inputs)}) "
                                "or a parameter (give its value in params)")

    def walk(node, in_lookup: bool = False):
        count[0] += 1
        if count[0] > MAX_NODES:
            raise EquationError(f"an equation has at most {MAX_NODES} parts")
        if isinstance(node, ast.Expression):
            return walk(node.body)
        if isinstance(node, ast.Constant):
            if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
                raise EquationError(f"only numbers are constants, not {node.value!r} (a stock or input by its id: stock(\"id\"))")
            return
        if isinstance(node, ast.Name):
            return name(node.id)
        if isinstance(node, ast.BinOp) and type(node.op) in BINARY:
            walk(node.left)
            return walk(node.right)
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
            return walk(node.operand)
        if isinstance(node, ast.Compare):
            if len(node.ops) != 1 or type(node.ops[0]) not in COMPARE:
                raise EquationError("one comparison at a time (<, <=, >, >=, ==, !=); join several with min or max")
            walk(node.left)
            return walk(node.comparators[0])
        if isinstance(node, ast.Call):
            return call(node)
        raise EquationError(f"{type(node).__name__.lower()} is not part of the equation language: numbers, names, + - * / **, "
                            f"one comparison, and the functions {', '.join(FUNCTIONS)}")

    def call(node: ast.Call):
        if not isinstance(node.func, ast.Name) or node.func.id not in FUNCTIONS:
            fn = node.func.id if isinstance(node.func, ast.Name) else ast.unparse(node.func)
            raise EquationError(f"unknown function {fn}: the functions are {', '.join(FUNCTIONS)}")
        fn = node.func.id
        if node.keywords:
            raise EquationError(f"{fn} takes its arguments in order, without names")
        lo, hi, _ = FUNCTIONS[fn]
        n = len(node.args)
        if n < lo or (hi is not None and n > hi):
            raise EquationError(f"{fn} takes {lo if lo == hi else f'{lo} or more' if hi is None else f'{lo} to {hi}'} "
                                f"argument{'s' if (hi or 2) != 1 else ''}, not {n}")
        _add(out.functions, fn)
        if fn in ("stock", "input"):
            [a] = node.args
            if not isinstance(a, ast.Constant) or not isinstance(a.value, str):
                raise EquationError(f"{fn}(\"id\") takes the id as a string")
            known = stocks if fn == "stock" else inputs
            if a.value not in known:
                raise EquationError(f"no {'stock' if fn == 'stock' else 'measured input'} {a.value!r}: {_some(known)}")
            _add(out.stocks if fn == "stock" else out.inputs, a.value)
            return
        if fn == "lookup":
            walk(node.args[0])
            points(node.args[1])
            return
        if fn in STATEFUL and _constant(node.args[1]) is not None and _constant(node.args[1]) <= 0:
            raise EquationError(f"{fn}: tau must be above 0")
        for a in node.args:
            walk(a)

    def points(node):
        if not isinstance(node, (ast.List, ast.Tuple)) or not 2 <= len(node.elts) <= MAX_POINTS:
            raise EquationError(f"lookup's points are a list of 2 to {MAX_POINTS} pairs [[x0, y0], [x1, y1], ...]")
        xs = []
        for e in node.elts:
            if not isinstance(e, (ast.List, ast.Tuple)) or len(e.elts) != 2 or any(_constant(v) is None for v in e.elts):
                raise EquationError("lookup's points are pairs of numbers [x, y]")
            xs.append(_constant(e.elts[0]))
        if xs != sorted(xs):
            raise EquationError("lookup's points rise in x")

    walk(tree)
    if unused := sorted(set(p) - used):
        raise EquationError(f"parameter{'s' if len(unused) > 1 else ''} {', '.join(unused)} not read by the equation")
    return out


def _constant(node) -> float | None:
    """A number written as a literal (with a sign)."""
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
        return float(node.value)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)) and (v := _constant(node.operand)) is not None:
        return -v if isinstance(node.op, ast.USub) else v
    return None


def _add(xs: list, x) -> None:
    if x not in xs:
        xs.append(x)


def _some(xs) -> str:
    xs = sorted(xs)
    return ", ".join(xs[:12]) + (f" and {len(xs) - 12} more" if len(xs) > 12 else "") if xs else "none"


def name_of(kind: str, ident: str, stocks=(), inputs=()) -> str:
    """How an id is written: bare when it is a plain name nothing else is called, else qualified."""
    other = inputs if kind == "stock" else stocks
    if IDENT.match(ident) and ident not in FUNCTIONS and ident not in other:
        return ident
    return f'{kind}("{ident}")'


def reference() -> dict:
    """The language, for a machine to read (``GET /language``)."""
    return {"syntax": "Python expression syntax: numbers, names, + - * / **, unary -, parentheses, one comparison (1 or 0)",
            "names": "a stock's id (its level), a measured input's name (its value), or a parameter given in params; "
                     "stock(\"id\") or input(\"name\") for ids that are not plain names or are both",
            "functions": {k: {"arguments": [lo, hi], "meaning": d} for k, (lo, hi, d) in FUNCTIONS.items()},
            "rate": "per the model's time unit; below 0 is 0; not a number is 0 and reported; a stock's outflows share what it holds",
            "units": "not checked",
            "limits": {"characters": MAX_TEXT, "parts": MAX_NODES, "params": MAX_PARAMS, "lookup_points": MAX_POINTS}}


def syntax(text, params=None) -> Parsed:
    """An equation checked without a model: its syntax and its parameters; every other bare name
    is taken as a stock (a prediction is checked before the model it will be judged on exists)."""
    if not isinstance(text, str) or not text.strip():
        raise EquationError("an equation is a non-empty string, e.g. \"k * waiting\"")
    try:
        tree = ast.parse(text.strip(), mode="eval")
    except SyntaxError as e:
        raise EquationError(f"{text.strip()!r} does not parse: {e.msg} at column {e.offset}") from None
    p = check_params(params)
    bare = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} - set(p)
    quoted = {(n.func.id, n.args[0].value) for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
              and n.func.id in ("stock", "input") and n.args and isinstance(n.args[0], ast.Constant) and isinstance(n.args[0].value, str)}
    return parse(text, stocks=bare | {v for k, v in quoted if k == "stock"}, inputs={v for k, v in quoted if k == "input"}, params=p)
