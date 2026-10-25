"""Expressions for the ground-truth engine (sdtruth.py): the rate form {"form": "expr", "expr": "..."},
auxiliaries and switches (added for queue item 2d, 2026-10-19; additive: a model that uses none of
them runs through the engine exactly as before).

    tree = parse("0.3 * sqrt(T) + min(A, B / max(1, C))")
    names(tree)        -> {"T", "A", "B", "C"}          what it reads (stocks, inputs, auxiliaries)
    flow_refs(tree)    -> set()                         the flows it reads with flow(id)
    fn = compile_expr(tree);  fn(view, flows) -> float  view: {name: value}; flows: {flow id: rate}

The grammar (no eval; a small recursive-descent parser):

    expr    := sum [('<' | '<=' | '>' | '>=' | '==' | '!=') sum]     a comparison is 1 or 0
    sum     := term (('+' | '-') term)*
    term    := unary (('*' | '/') unary)*
    unary   := '-' unary | '+' unary | power
    power   := atom ['^' unary]                                      -2^2 is -(2^2), 2^-1 is 0.5
    atom    := number | name | name '(' expr, ... ')' | '(' expr ')' | '[' [x, y], ... ']'

Functions (Vensim's meaning, as PySD computes them): min(a, b, ...), max(a, b, ...), abs, sqrt, exp,
ln, log(x, base), power(a, b), ceil, floor, integer (towards 0), modulo(a, b) (a - quantum(a, b)),
quantum(a, b) (b x integer(a / b), a when b < 1e-6), sin, cos, tan, arcsin, arccos, arctan, sinh,
cosh, tanh, if_then_else(c, a, b) (only the branch taken is computed), and(a, b, ...), or(a, b, ...),
not(a), xidz(a, b, x) and zidz(a, b) (a / b, or x / 0 when |b| < 1e-6), lookup(x, [[x0, y0], ...])
(linear between the points, held at the ends; not floored, unlike an effect table), and flow(id)
(another flow's rate in this sub-step: its amount as moved, after noise and the floor and ceiling,
over dt). Division by zero is an error: write zidz or xidz where a denominator can be 0.
"""

from __future__ import annotations

import math
import re

SMALL = 1e-6                                                         # Vensim's (and PySD's) SMALL_VENSIM
TOKEN_RE = re.compile(r"\s*(?:(?P<num>(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?)|(?P<name>[A-Za-z_][A-Za-z0-9_]*)"
                      r"|(?P<op><=|>=|==|!=|[-+*/^(),<>\[\]]))")
COMPARE = {"<": lambda a, b: a < b, "<=": lambda a, b: a <= b, ">": lambda a, b: a > b, ">=": lambda a, b: a >= b,
           "==": lambda a, b: a == b, "!=": lambda a, b: a != b}


def _quantum(a: float, b: float) -> float:
    return a if b < SMALL else b * int(a / b)


def _power(a: float, b: float) -> float:
    try:
        return math.pow(a, b)
    except (ValueError, OverflowError):
        return math.nan if a < 0 else math.inf


ONE_ARG = {"abs": abs, "sqrt": math.sqrt, "exp": math.exp, "ln": math.log, "ceil": lambda x: float(math.ceil(x)),
           "floor": lambda x: float(math.floor(x)), "integer": lambda x: float(int(x)), "sin": math.sin, "cos": math.cos,
           "tan": math.tan, "arcsin": math.asin, "arccos": math.acos, "arctan": math.atan, "sinh": math.sinh, "cosh": math.cosh,
           "tanh": math.tanh, "not": lambda x: float(not x)}
FUNCTIONS = {**{k: (1, 1) for k in ONE_ARG}, "min": (1, None), "max": (1, None), "log": (1, 2), "power": (2, 2), "modulo": (2, 2),
             "quantum": (2, 2), "if_then_else": (3, 3), "and": (1, None), "or": (1, None), "xidz": (3, 3), "zidz": (2, 2),
             "lookup": (2, 2), "flow": (1, 1)}


class ExprError(ValueError):
    """An expression that does not parse, or reads something unknown."""


class _Parser:
    def __init__(self, text: str):
        self.text, self.toks, pos = text, [], 0
        while pos < len(text):
            m = TOKEN_RE.match(text, pos)
            if not m or m.end() == pos:
                if not text[pos:].strip():
                    break
                raise ExprError(f"unexpected {text[pos:].lstrip()[0]!r} in {text!r}")
            self.toks.append((m.lastgroup, m.group(m.lastgroup)))
            pos = m.end()
        self.i = 0

    def peek(self, v: str) -> bool:
        return self.i < len(self.toks) and self.toks[self.i][1] == v and self.toks[self.i][0] == "op"

    def take(self, v: str | None = None) -> tuple[str, str]:
        if self.i >= len(self.toks) or (v is not None and not self.peek(v)):
            raise ExprError(f"expected {v or 'more'} in {self.text!r}")
        self.i += 1
        return self.toks[self.i - 1]

    def parse(self):
        node = self.expr()
        if self.i < len(self.toks):
            raise ExprError(f"unexpected {self.toks[self.i][1]!r} in {self.text!r}")
        return node

    def expr(self):
        a = self.sum()
        for op in COMPARE:
            if self.peek(op):
                self.take(op)
                return ("bin", op, a, self.sum())
        return a

    def sum(self):
        a = self.term()
        while self.peek("+") or self.peek("-"):
            op = self.take()[1]
            a = ("bin", op, a, self.term())
        return a

    def term(self):
        a = self.unary()
        while self.peek("*") or self.peek("/"):
            op = self.take()[1]
            a = ("bin", op, a, self.unary())
        return a

    def unary(self):
        if self.peek("-"):
            self.take()
            return ("neg", self.unary())
        if self.peek("+"):
            self.take()
            return self.unary()
        a = self.atom()
        if self.peek("^"):
            self.take()
            return ("bin", "^", a, self.unary())
        return a

    def atom(self):
        if self.i >= len(self.toks):
            raise ExprError(f"unexpected end of {self.text!r}")
        kind, v = self.toks[self.i]
        if kind == "num":
            self.i += 1
            return ("num", float(v))
        if self.peek("("):
            self.take("(")
            inner = self.expr()
            self.take(")")
            return inner
        if self.peek("["):
            return ("list", self.points())
        if kind == "name":
            self.i += 1
            if not self.peek("("):
                return ("name", v)
            if v not in FUNCTIONS:
                raise ExprError(f"unknown function {v!r} in {self.text!r} (functions: {', '.join(sorted(FUNCTIONS))})")
            self.take("(")
            args = []
            while not self.peek(")"):
                args.append(("ref", self.take()[1]) if v == "flow" else self.expr())
                if not self.peek(")"):
                    self.take(",")
            self.take(")")
            lo, hi = FUNCTIONS[v]
            if len(args) < lo or (hi is not None and len(args) > hi):
                raise ExprError(f"{v} takes {lo}{'' if hi == lo else ' or more' if hi is None else f' to {hi}'} arguments in {self.text!r}")
            if v == "lookup" and args[1][0] != "list":
                raise ExprError(f"lookup takes (x, [[x0, y0], [x1, y1], ...]) in {self.text!r}")
            if v != "lookup" and any(a[0] == "list" for a in args):
                raise ExprError(f"a list of points is only for lookup, in {self.text!r}")
            return ("call", v, args)
        raise ExprError(f"unexpected {v!r} in {self.text!r}")

    def points(self) -> list:
        self.take("[")
        out = []
        while not self.peek("]"):
            self.take("[")
            pair = [self._signed(), None]
            self.take(",")
            pair[1] = self._signed()
            self.take("]")
            out.append(pair)
            if not self.peek("]"):
                self.take(",")
        self.take("]")
        if not out:
            raise ExprError(f"a lookup needs points in {self.text!r}")
        return out

    def _signed(self) -> float:
        neg = self.peek("-") and self.take("-")
        kind, v = self.take()
        if kind != "num":
            raise ExprError(f"a lookup's points are numbers, in {self.text!r}")
        return -float(v) if neg else float(v)


def parse(text) -> tuple:
    if isinstance(text, (int, float)) and not isinstance(text, bool):
        return ("num", float(text))
    if not isinstance(text, str) or not text.strip():
        raise ExprError(f"an expression is a non-empty string, not {text!r}")
    return _Parser(text).parse()


def _walk(node):
    yield node
    if node[0] == "neg":
        yield from _walk(node[1])
    elif node[0] == "bin":
        yield from _walk(node[2])
        yield from _walk(node[3])
    elif node[0] == "call":
        for a in node[2]:
            yield from _walk(a)


def names(node) -> set[str]:
    """The names an expression reads (stocks, inputs, auxiliaries), not the flows of flow(id)."""
    return {n[1] for n in _walk(node) if n[0] == "name"}


def flow_refs(node) -> set[str]:
    return {n[1] for n in _walk(node) if n[0] == "ref"}


def _lookup(pts: list):
    pts = sorted((float(a), float(b)) for a, b in pts)
    pairs = list(zip(pts, pts[1:]))

    def at(x: float) -> float:
        if x <= pts[0][0]:
            return pts[0][1]
        for (x0, y0), (x1, y1) in pairs:
            if x <= x1:
                return y0 + (y1 - y0) * (x - x0) / max(1e-12, x1 - x0)
        return pts[-1][1]
    return at


def compile_expr(node):
    """The expression as a function fn(view, flows) of a {name: value} view and {flow id: rate}."""
    kind = node[0]
    if kind == "num":
        v = node[1]
        return lambda view, fl: v
    if kind == "name":
        n = node[1]
        return lambda view, fl: view[n]
    if kind == "neg":
        a = compile_expr(node[1])
        return lambda view, fl: -a(view, fl)
    if kind == "bin":
        op, a, b = node[1], compile_expr(node[2]), compile_expr(node[3])
        if op == "+":
            return lambda view, fl: a(view, fl) + b(view, fl)
        if op == "-":
            return lambda view, fl: a(view, fl) - b(view, fl)
        if op == "*":
            return lambda view, fl: a(view, fl) * b(view, fl)
        if op == "/":
            return lambda view, fl: a(view, fl) / b(view, fl)
        if op == "^":
            return lambda view, fl: _power(a(view, fl), b(view, fl))
        cmp = COMPARE[op]
        return lambda view, fl: 1.0 if cmp(a(view, fl), b(view, fl)) else 0.0
    if kind == "call":
        name, raw = node[1], node[2]
        if name == "flow":
            fid = raw[0][1]
            return lambda view, fl: fl[fid]
        if name == "lookup":
            x, at = compile_expr(raw[0]), _lookup(raw[1][1])
            return lambda view, fl: at(x(view, fl))
        args = [compile_expr(a) for a in raw]
        if name in ONE_ARG:
            f, a = ONE_ARG[name], args[0]
            return lambda view, fl: f(a(view, fl))
        if name == "min":
            return lambda view, fl: min(g(view, fl) for g in args)
        if name == "max":
            return lambda view, fl: max(g(view, fl) for g in args)
        if name == "and":
            return lambda view, fl: 1.0 if all(g(view, fl) for g in args) else 0.0
        if name == "or":
            return lambda view, fl: 1.0 if any(g(view, fl) for g in args) else 0.0
        if name == "if_then_else":
            c, a, b = args
            return lambda view, fl: a(view, fl) if c(view, fl) else b(view, fl)
        if name == "zidz":
            a, b = args
            return lambda view, fl: (lambda d: 0.0 if abs(d) < SMALL else a(view, fl) / d)(b(view, fl))
        if name == "xidz":
            a, b, x = args
            return lambda view, fl: (lambda d: x(view, fl) if abs(d) < SMALL else a(view, fl) / d)(b(view, fl))
        if name == "log":
            if len(args) == 1:
                a = args[0]
                return lambda view, fl: math.log10(a(view, fl))
            a, b = args
            return lambda view, fl: math.log(a(view, fl)) / math.log(b(view, fl))
        if name == "power":
            a, b = args
            return lambda view, fl: _power(a(view, fl), b(view, fl))
        if name == "quantum":
            a, b = args
            return lambda view, fl: _quantum(a(view, fl), b(view, fl))
        if name == "modulo":
            a, b = args
            return lambda view, fl: (lambda x, m: x - _quantum(x, m))(a(view, fl), b(view, fl))
    raise ExprError(f"cannot compile {node!r}")


def text(node) -> str:
    """The expression written back (fully parenthesised where needed)."""
    kind = node[0]
    if kind == "num":
        v = node[1]
        return str(int(v)) if v == int(v) and abs(v) < 1e15 else repr(v)
    if kind == "name":
        return node[1]
    if kind == "ref":
        return node[1]
    if kind == "neg":
        return f"-({text(node[1])})"
    if kind == "bin":
        return f"({text(node[2])} {node[1]} {text(node[3])})"
    if kind == "list":
        return "[" + ", ".join(f"[{text(('num', a))}, {text(('num', b))}]" for a, b in node[1]) + "]"
    return f"{node[1]}({', '.join(text(a) for a in node[2])})"
