"""A PromQL subset: lexer and parser to a small AST.

Supported: number literals, vector selectors with = != =~ !~ matchers, range
selectors, `offset`, function calls, aggregations (with by/without before or
after the argument, and a parameter for topk/bottomk), unary minus, binary
arithmetic and comparison (with `bool`, `on(...)`, `ignoring(...)`), parens.
"""

import re
from dataclasses import dataclass, field


class ParseError(Exception):
    pass


AGGREGATIONS = {"sum", "avg", "max", "min", "count", "group", "topk", "bottomk"}
RANGE_FUNCS = {
    "rate",
    "irate",
    "increase",
    "delta",
    "idelta",
    "deriv",
    "avg_over_time",
    "max_over_time",
    "min_over_time",
    "sum_over_time",
    "count_over_time",
    "last_over_time",
    "changes",
    "resets",
}
INSTANT_FUNCS = {
    "abs",
    "ceil",
    "floor",
    "round",
    "sqrt",
    "exp",
    "ln",
    "log2",
    "log10",
    "clamp",
    "clamp_min",
    "clamp_max",
    "scalar",
    "vector",
    "time",
    "label_replace",
    "sort",
    "sort_desc",
    "timestamp",
}
PRECEDENCE = {
    "or": 1,
    "and": 2,
    "unless": 2,
    "==": 3,
    "!=": 3,
    "<": 3,
    ">": 3,
    "<=": 3,
    ">=": 3,
    "+": 4,
    "-": 4,
    "*": 5,
    "/": 5,
    "%": 5,
    "^": 6,
}
COMPARISONS = {"==", "!=", "<", ">", "<=", ">="}
UNITS = {"ms": 0.001, "s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800, "y": 31536000}


@dataclass
class Number:
    value: float


@dataclass
class String:
    value: str


@dataclass
class Selector:
    name: str | None
    matchers: list  # (label, op, value)
    offset: float = 0.0


@dataclass
class MatrixSelector:
    selector: Selector
    range: float


@dataclass
class Call:
    func: str
    args: list


@dataclass
class Aggregate:
    op: str
    expr: object
    grouping: list = field(default_factory=list)
    without: bool = False
    param: object = None


@dataclass
class Binary:
    op: str
    lhs: object
    rhs: object
    bool_: bool = False
    on: list | None = None
    ignoring: list | None = None


@dataclass
class Neg:
    expr: object


TOKEN = re.compile(
    r"""
    (?P<ws>\s+)
  | (?P<duration>(?:\d+(?:ms|[smhdwy]))+)(?![\w.])
  | (?P<number>0[xX][0-9a-fA-F]+|(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?|[Ii]nf|NaN)(?![\w:])
  | (?P<ident>[a-zA-Z_:][a-zA-Z0-9_:]*)
  | (?P<string>"(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*'|`[^`]*`)
  | (?P<op>==|!=|=~|!~|<=|>=|[-+*/%^<>=(){}\[\],])
    """,
    re.VERBOSE,
)


def tokenize(text: str):
    out, pos = [], 0
    while pos < len(text):
        m = TOKEN.match(text, pos)
        if not m:
            raise ParseError(f"1:{pos + 1}: parse error: unexpected character: {text[pos]!r}")
        pos = m.end()
        kind = m.lastgroup
        if kind == "ws":
            continue
        out.append((kind, m.group(kind), m.start()))
    out.append(("eof", "", len(text)))
    return out


def parse_duration(text: str) -> float:
    total = 0.0
    for num, unit in re.findall(r"(\d+)(ms|[smhdwy])", text):
        total += int(num) * UNITS[unit]
    if total <= 0:
        raise ParseError(f"invalid duration {text!r}")
    return total


def _unquote(s: str) -> str:
    if s[0] == "`":
        return s[1:-1]
    return bytes(s[1:-1], "utf-8").decode("unicode_escape")


class Parser:
    def __init__(self, text: str):
        self.text = text
        self.toks = tokenize(text)
        self.i = 0

    def peek(self, k=0):
        return self.toks[min(self.i + k, len(self.toks) - 1)]

    def next(self):
        tok = self.toks[self.i]
        self.i += 1
        return tok

    def error(self, msg, tok=None):
        tok = tok or self.peek()
        raise ParseError(f"1:{tok[2] + 1}: parse error: {msg}")

    def expect(self, value):
        tok = self.next()
        if tok[1] != value:
            self.error(f"unexpected {tok[1] or 'end of input'!r}, expected {value!r}", tok)
        return tok

    def parse(self):
        node = self.expr(0)
        if self.peek()[0] != "eof":
            self.error(f"unexpected {self.peek()[1]!r}")
        return node

    def binop(self):
        kind, val, _ = self.peek()
        if kind == "op" and val in PRECEDENCE:
            return val
        if kind == "ident" and val in ("and", "or", "unless"):
            return val
        return None

    def expr(self, min_prec):
        lhs = self.unary()
        while True:
            op = self.binop()
            if op is None or PRECEDENCE[op] < min_prec:
                return lhs
            self.next()
            node = Binary(op, lhs, None)
            if self.peek()[1] == "bool":
                self.next()
                node.bool_ = True
            if self.peek()[1] in ("on", "ignoring"):
                which = self.next()[1]
                setattr(node, which, self.label_list())
            if self.peek()[1] in ("group_left", "group_right"):
                self.error("group_left/group_right are not supported")
            nxt = PRECEDENCE[op] if op == "^" else PRECEDENCE[op] + 1
            node.rhs = self.expr(nxt)
            lhs = node

    def unary(self):
        if self.peek()[1] in ("-", "+"):
            sign = self.next()[1]
            inner = self.expr(PRECEDENCE["^"])
            if sign == "+":
                return inner
            if isinstance(inner, Number):
                return Number(-inner.value)
            return Neg(inner)
        return self.postfix()

    def postfix(self):
        node = self.primary()
        if self.peek()[1] == "[":
            self.next()
            kind, val, _ = self.next()
            if kind != "duration":
                self.error("expected a duration in range selector (subqueries are not supported)")
            if self.peek()[1] == ":":
                self.error("subqueries are not supported")
            self.expect("]")
            if not isinstance(node, Selector):
                self.error("ranges only allowed for vector selectors")
            node = MatrixSelector(node, parse_duration(val))
        if self.peek()[1] == "offset":
            self.next()
            kind, val, _ = self.next()
            if kind != "duration":
                self.error("expected a duration after offset")
            sel = node.selector if isinstance(node, MatrixSelector) else node
            if not isinstance(sel, Selector):
                self.error("offset modifier must be preceded by a selector")
            sel.offset = parse_duration(val)
        if self.peek()[1] == "@":
            self.error("the @ modifier is not supported")
        return node

    def label_list(self):
        self.expect("(")
        out = []
        while self.peek()[1] != ")":
            kind, val, _ = self.next()
            if kind != "ident":
                self.error(f"unexpected {val!r} in grouping")
            out.append(val)
            if self.peek()[1] == ",":
                self.next()
        self.expect(")")
        return out

    def primary(self):
        kind, val, _ = self.peek()
        if kind == "number":
            self.next()
            return Number(float(int(val, 16)) if val.lower().startswith("0x") else float(val))
        if kind == "duration":  # a bare number such as `5m` is not valid outside brackets
            self.error(f"unexpected duration {val!r}")
        if kind == "string":
            self.next()
            return String(_unquote(val))
        if val == "(":
            self.next()
            node = self.expr(0)
            self.expect(")")
            return node
        if val == "{":
            return self.selector(None)
        if kind == "ident":
            nxt = self.peek(1)[1]
            if val in AGGREGATIONS and nxt in ("(", "by", "without"):
                return self.aggregate()
            if nxt == "(":
                return self.call()
            self.next()
            return self.selector(val)
        self.error(f"unexpected {val or 'end of input'!r}")

    def selector(self, name):
        matchers = []
        if self.peek()[1] == "{":
            self.next()
            while self.peek()[1] != "}":
                kind, label, _ = self.next()
                if kind != "ident":
                    self.error(f"unexpected {label!r} in label matching, expected label name")
                op = self.next()[1]
                if op not in ("=", "!=", "=~", "!~"):
                    self.error(f"unexpected {op!r} in label matching, expected one of = != =~ !~")
                kind, value, _ = self.next()
                if kind != "string":
                    self.error("expected a quoted label value")
                matchers.append((label, op, _unquote(value)))
                if self.peek()[1] == ",":
                    self.next()
                elif self.peek()[1] != "}":
                    self.error(f"unexpected {self.peek()[1]!r} in label matching")
            self.expect("}")
        for label, op, value in matchers:
            if label == "__name__" and op == "=":
                if name is not None and name != value:
                    self.error("metric name given twice")
                name = value
        if name is None and not any(op in ("=", "=~") and not _matches_empty(op, v) for _, op, v in matchers):
            self.error("vector selector must contain at least one non-empty matcher")
        return Selector(name, [m for m in matchers if not (m[0] == "__name__" and m[1] == "=")])

    def aggregate(self):
        op = self.next()[1]
        grouping, without = [], False
        if self.peek()[1] in ("by", "without"):
            without = self.next()[1] == "without"
            grouping = self.label_list()
        self.expect("(")
        param = None
        if op in ("topk", "bottomk"):
            param = self.expr(0)
            self.expect(",")
        inner = self.expr(0)
        self.expect(")")
        if self.peek()[1] in ("by", "without"):
            without = self.next()[1] == "without"
            grouping = self.label_list()
        return Aggregate(op, inner, grouping, without, param)

    def call(self):
        tok = self.next()
        func = tok[1]
        if func not in RANGE_FUNCS and func not in INSTANT_FUNCS:
            self.error(f"unknown function with name {func!r}", tok)
        self.expect("(")
        args = []
        while self.peek()[1] != ")":
            args.append(self.expr(0))
            if self.peek()[1] == ",":
                self.next()
            elif self.peek()[1] != ")":
                self.error(f"unexpected {self.peek()[1]!r} in function call")
        self.expect(")")
        if func in RANGE_FUNCS and (len(args) != 1 or not isinstance(args[0], MatrixSelector)):
            self.error(f"expected 1 range-vector argument in call to {func}", tok)
        return Call(func, args)


def _matches_empty(op, value):
    if op == "=":
        return value == ""
    return re.fullmatch(value, "") is not None


def parse(text: str):
    if not text or not text.strip():
        raise ParseError("no expression found in input")
    return Parser(text).parse()
