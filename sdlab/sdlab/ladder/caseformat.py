"""The compact case format: a ladder case written by hand in YAML (NNN-slug.yaml), compiled to the
same case dict as a JSON case (cases.py). docs/LADDER.md has the reference; in short:

    title: Chain of three
    level: 3
    tags: [chain, move]
    tests: two moves in a row are recovered, each at its own rate
    seed: 4
    stocks: {A: 0, B: 0, H: 0 hidden}
    flows:
      outside -> A: 20                       # constant              -> id "in" (the first inflow from outside)
      A -> B: 0.5 * A                        # proportional          -> id "ab"
      B -> H as wait: 0.2 * B                # a named flow
      H -> outside: 0.1 * H                  # -> id "h_out"
      outside -> B: 2 + 0.01 * A - 0.5 * H   # linear (c + terms)    -> id "b_in"
      outside -> A as orders: (300 - B) / 5  # gap: (goal - stock) / time
      A -> B as fast: 0.3 * A * effect(B, linear, normal=50, max=2) uses(H, 0.5)
    schedule:
      every: 200
      at 1 low: {in: 20}
      at 101 high announced: {in: 30}
    injections: [{t: 50, stock: A, amount: 400}]

Added on 2026-10-18 (engine features, additive; docs/LADDER.md "Inputs, sub-steps, ceilings, delays"):

    dt: 0.25                                 # sub-steps: each recorded step is 1/dt engine steps
    inputs:                                  # measured inputs (outside drivers given as data)
      pump: [3, 3, 5, 5, 4]                  #   a series, one value per step (the last holds)
      rain: 2 + step(3, 100) + sin(1.5, 50)  #   a formula: constant, step, pulse, ramp, pulse_train, sin
      demand: {file: data/demand.csv, column: demand, repeat: true}   # a column of a file in cases/
    stocks: {T: 0 max=500, A: {initial: 0, max: 80}}                 # a ceiling
    flows:
      outside -> T: 0.8 * pump               # a rate reads an input as it reads a stock (or input(pump))
      A -> B: delay3(0.5 * A, 6)             # a material delay: three hidden stocks at 3/6 each
      A -> B as d1: delay1(0.5 * A, 4)       # one hidden stock at 1/4
      outside -> C: 0.2 * smooth(A, 5)       # SMOOTH (smooth3 too): a hidden stock, exact flows
      outside -> D: 10 + step(5, 100) + pulse(20, 300, 2)   # test inputs: unannounced schedule changes

Added on 2026-10-19 (queue item 2d, engine features, additive; docs/LADDER.md "Expressions, signed stocks,
two-way flows, switches, fixed delays"):

    auxiliaries:                             # algebraic variables (no stock): read by name in rates
      util: cpu / max(1, ready)
    switches:                                # a switch with memory (hysteresis): a hidden 0/1 stock
      heater: {of: T, on_below: 19, off_above: 21, initial: 1}
    stocks: {x: 1 signed, T: 0 max=50 net}   # signed: may go negative; net: the ceiling counts the step's outflows
    flows:
      T -> outside: 0.3 * sqrt(T)            # any other rate is an expression (sdtruth_expr.py): + - * / ^,
      outside -> A: min(5, B / C) * (T > 2)  #   comparisons, min, max, ceil, sqrt, power, lookup, if_then_else, ...
      x <-> v: 0.1 * v                       # a two-way flow: a negative rate moves back (also {rate:, two_way: true})
      outside -> R: flow(kill)               # another flow's amount (after noise and limits) as a rate
      A -> B: delay_fixed(0.5 * A, 4)        # DELAY FIXED: a pipe of 4 / dt hidden stages, each passed on whole
      A -> C: delay3(0.5 * A, 2 + B / 10)    # a delay whose time changes (stages at 3 / time, an expression)
      outside -> D: 2 * trend(A, 5, 0)       # TREND(x, time, initial trend) and FORECAST(x, time, horizon[, initial trend])

Added on 2026-10-20 (the user: outside flows are a modelling decision; docs/LADDER.md "The boundary"):

    boundary:                                # the model boundary, announced to discovery: per measured stock
      A: {in: measured, out: estimate}       #   its outside inflows and outflows, each "measured" (driven by a
      B: {out: [estimate, estimate]}         #   measured input) or "estimate" (form and rate to estimate)
                                             # stocks not listed have none; `boundary: {}` declares none at all;
                                             # no boundary key: undeclared (outside flows are boundary claims)

A number anywhere may instead be a range to draw from, draw(lo, hi) (a parametric case; draws.py
resolves those to numbers before the text is compiled here).

compile_case(text, name) -> the case dict ({title, level, tags, tests, model, ...}); every mistake
raises CaseError with the file name and line. Rates are parsed by a small recursive-descent parser
(no eval).
"""

from __future__ import annotations

import re

import yaml

OUTSIDE = "outside"
TOP_KEYS = {"title", "level", "tags", "tests", "seed", "stocks", "flows", "schedule", "injections", "variants", "tolerance", "draws",
            "dt", "inputs", "source", "auxiliaries", "switches", "boundary"}
DELAYS = {"delay1": 1, "delay3": 3}                               # DELAYn(rate, time): n hidden stocks in a chain
TRENDS = ("trend", "forecast")                                     # TREND / FORECAST: a smoothing and an expression (2d)
SMOOTHS = {"smooth": 1, "smooth3": 3}                             # SMOOTHn(x, time): n hidden stocks, exact flows
TESTS = {"step": ("height", "start"), "pulse": ("height", "start", "width"), "ramp": ("slope", "start", "end"),
         "pulse_train": ("height", "first", "width", "every", "last")}
INPUT_FNS = {**TESTS, "sin": ("amplitude", "period", "phase")}
REQUIRED = {"step": 2, "pulse": 2, "ramp": 2, "pulse_train": 4, "sin": 2}
INPUT_REF_RE = re.compile(r"\binput\(\s*([A-Za-z_][A-Za-z0-9_]*)\s*\)")
CASES_DIR = __import__("pathlib").Path(__file__).resolve().parent / "cases"
FORMS = {"constant", "proportional", "gap", "linear", "available"}
ID_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
FLOW_KEY_RE = re.compile(r"^\s*(\S+)\s*->\s*(\S+)\s*(?:\bas\s+(\S+)\s*)?$")
TWO_WAY_KEY_RE = re.compile(r"^\s*(\S+?)\s*<->\s*(\S+)\s*(?:\bas\s+(\S+)\s*)?$")          # a two-way flow (2d)
CHANGE_KEY_RE = re.compile(r"^\s*at\s+(\d+)\s*(.*?)\s*$")


class CaseError(ValueError):
    """A case file that does not compile; the message names the file and line."""


# ---- YAML with line numbers and no duplicate keys ----

class _Map(dict):
    line = 0
    lines: dict


class _Loader(yaml.SafeLoader):
    pass


def _construct_map(loader: _Loader, node: yaml.MappingNode) -> _Map:
    loader.flatten_mapping(node)
    out = _Map()
    out.line, out.lines = node.start_mark.line + 1, {}
    for knode, vnode in node.value:
        key = loader.construct_object(knode, deep=True)
        if isinstance(key, (list, dict)):
            raise CaseError(f"{knode.start_mark.line + 1}: a key must be a plain value")
        if key in out:
            raise CaseError(f"{knode.start_mark.line + 1}: {key!r} appears twice (give one of two flows with the same ends a name: 'A -> B as other')")
        out[key] = loader.construct_object(vnode, deep=True)
        out.lines[key] = knode.start_mark.line + 1
    return out


_Loader.add_constructor("tag:yaml.org,2002:map", _construct_map)


# ---- rate expressions ----

TOKEN_RE = re.compile(r"\s*(?:(?P<num>(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?)|(?P<name>[A-Za-z_][A-Za-z0-9_]*)|(?P<op><=|>=|==|!=|[-+*/(),=\[\]<>^]))")
COMPARE = ("<=", ">=", "==", "!=", "<", ">")


def _number(text: str) -> int | float:
    """An int when written as one (20), else a float (0.5, 1e-3): the same values JSON would give."""
    return int(text) if re.fullmatch(r"\d+", text) else float(text)


class _Expr:
    """Tokens of one rate expression and a cursor; err() points at the current token."""

    def __init__(self, text: str):
        self.text, self.toks, pos = text, [], 0
        while pos < len(text):
            m = TOKEN_RE.match(text, pos)
            if not m or m.end() == pos:
                if text[pos:].strip() == "":
                    break
                col = pos + len(text[pos:]) - len(text[pos:].lstrip())
                raise self._error(f"unexpected {text[col]!r}", col)
            kind = m.lastgroup
            self.toks.append((kind, m.group(kind), m.start(kind)))
            pos = m.end()
        self.i = 0

    def _error(self, msg: str, col: int) -> CaseError:
        return CaseError(f"{msg} in '{self.text}' (column {col + 1})")

    def err(self, msg: str) -> CaseError:
        return self._error(msg, self.toks[self.i][2] if self.i < len(self.toks) else len(self.text))

    def peek(self, value: str | None = None, kind: str | None = None) -> bool:
        if self.i >= len(self.toks):
            return False
        k, v, _ = self.toks[self.i]
        return (value is None or v == value) and (kind is None or k == kind)

    def take(self, value: str | None = None, kind: str | None = None, what: str = "") -> str:
        if not self.peek(value, kind):
            raise self.err(f"expected {what or repr(value)}")
        self.i += 1
        return self.toks[self.i - 1][1]

    def done(self) -> bool:
        return self.i >= len(self.toks)

    # grammar: cmp := sum [compare sum];  sum := ['-'] product (('+'|'-') product)*;  product := factor (('*'|'/') factor)*
    #          factor := '-' factor | atom ['^' factor];  atom := number | name | name '(' args ')' | '(' cmp ')' | '[' list ']'
    # (a comparison, '^' and a '-' inside a product were added for 2d: a text that has one did not parse before)
    def cmp(self):
        a = self.sum()
        for op in COMPARE:
            if self.peek(op):
                self.take(op)
                return ("cmp", op, a, self.sum())
        return a

    def sum(self):
        terms = [("+" if not self.peek("-") else (self.take("-") and "-"), self.product())]
        while self.peek("+") or self.peek("-"):
            terms.append((self.take(), self.product()))
        return ("sum", terms) if len(terms) > 1 or terms[0][0] == "-" else terms[0][1]

    def product(self):
        parts = [("*", self.factor())]
        while self.peek("*") or self.peek("/"):
            parts.append((self.take(), self.factor()))
        return ("product", parts) if len(parts) > 1 else parts[0][1]

    def factor(self):
        if self.peek("-"):
            self.take("-")
            return ("sum", [("-", self.factor())])
        a = self.atom()
        if self.peek("^"):
            self.take("^")
            return ("pow", a, self.factor())
        return a

    def atom(self):
        if self.peek(kind="num"):
            return ("num", _number(self.take(kind="num")))
        if self.peek("("):
            self.take("(")
            inner = self.cmp()
            self.take(")")
            return ("group", inner)
        if self.peek("["):
            return ("list", self.listing())
        if self.peek(kind="name"):
            name = self.take(kind="name")
            if self.peek("("):
                return ("call", name, *self.args())
            return ("name", name)
        raise self.err("expected a number, a stock or '('")

    def listing(self) -> list:
        self.take("[")
        out = []
        while not self.peek("]"):
            neg = self.peek("-") and self.take("-")
            if self.peek("["):
                out.append(self.listing())
            else:
                v = _number(self.take(kind="num", what="a number"))
                out.append(-v if neg else v)
            if not self.peek("]"):
                self.take(",")
        self.take("]")
        return out

    def args(self) -> tuple[list, dict]:
        self.take("(")
        pos, kw = [], {}
        while not self.peek(")"):
            if self.peek(kind="name") and self.i + 1 < len(self.toks) and self.toks[self.i + 1][1] == "=":
                k = self.take(kind="name")
                self.take("=")
                kw[k] = self.cmp()
            else:
                pos.append(self.cmp())
            if not self.peek(")"):
                self.take(",", what="',' or ')'")
        self.take(")")
        return pos, kw


def _num_value(node, ex: _Expr, what: str) -> int | float:
    """A number literal, possibly negated."""
    if node[0] == "num":
        return node[1]
    if node[0] == "sum" and len(node[1]) == 1 and node[1][0][0] == "-" and node[1][0][1][0] == "num":
        return -node[1][0][1][1]
    raise ex.err(f"{what} must be a number")


def _stock(node, ex: _Expr, stocks: set[str], what: str = "a stock") -> str:
    if node[0] != "name":
        raise ex.err(f"expected {what}")
    if node[1] not in stocks:
        raise ex.err(f"unknown stock {node[1]!r}")
    return node[1]


def _term(sign: str, node, ex: _Expr, stocks: set[str]) -> dict | int | float:
    """One term of a rate: a number, or k * S, S * k, S / n, S (k = 1)."""
    neg = sign == "-"
    if node[0] == "num":
        return -node[1] if neg else node[1]
    if node[0] == "name":
        return {"stock": _stock(node, ex, stocks), "k": -1 if neg else 1}
    if node[0] == "product" and len(node[1]) == 2:
        (_, a), (op, b) = node[1]
        if op == "*" and a[0] == "num" and b[0] == "name":
            return {"stock": _stock(b, ex, stocks), "k": -a[1] if neg else a[1]}
        if op == "*" and a[0] == "name" and b[0] == "num":
            return {"stock": _stock(a, ex, stocks), "k": -b[1] if neg else b[1]}
        if op == "/" and a[0] == "name" and b[0] == "num" and b[1]:
            return {"stock": _stock(a, ex, stocks), "k": (-1 if neg else 1) / b[1]}
    raise ex.err("a rate is a number, k * stock, a sum of those, or (goal - stock) / time")


def _rate(node, ex: _Expr, stocks: set[str]) -> dict:
    """A rate without effects: constant, proportional, linear, gap, available."""
    if node[0] == "call" and node[1] == "max":                     # max(0, x): every rate is floored at 0 already
        pos, kw = node[2], node[3]
        if len(pos) != 2 or kw or pos[0] != ("num", 0):
            raise ex.err("max takes (0, rate): every rate is floored at 0")
        return _rate(pos[1], ex, stocks)
    if node[0] == "group":
        return _rate(node[1], ex, stocks)
    if node[0] == "name" and node[1] == "available":
        return {"form": "available"}
    if node[0] == "call" and node[1] == "available":
        if len(node[2]) != 1 or node[3]:
            raise ex.err("available takes one stock")
        return {"form": "available", "stock": _stock(node[2][0], ex, stocks)}
    if node[0] == "product" and len(node[1]) == 2 and node[1][1][0] == "/" and node[1][0][1][0] == "group":
        inner, time = node[1][0][1][1], node[1][1][1]
        if inner[0] == "sum" and len(inner[1]) == 2 and inner[1][0][0] == "+" and inner[1][1][0] == "-" \
                and inner[1][0][1][0] == "num" and inner[1][1][1][0] == "name":
            return {"form": "gap", "stock": _stock(inner[1][1][1], ex, stocks), "goal": inner[1][0][1][1],
                    "time": _num_value(time, ex, "a gap's time")}
        raise ex.err("a rate divided by a number is a gap: (goal - stock) / time")
    terms = [_term(s, n, ex, stocks) for s, n in (node[1] if node[0] == "sum" else [("+", node)])]
    consts = [t for t in terms if not isinstance(t, dict)]
    links = [t for t in terms if isinstance(t, dict)]
    if len(consts) > 1:
        raise ex.err("a linear rate has one number: c + k * stock + ...")
    if not links:
        return {"form": "constant", "value": consts[0]}
    if not consts and len(links) == 1 and node[0] != "sum":
        return {"form": "proportional", "stock": links[0]["stock"], "k": links[0]["k"]}
    return {"form": "linear", **({"c": consts[0]} if consts else {}), "terms": links}


def _effect(node, ex: _Expr, stocks: set[str]) -> dict:
    pos, kw = node[2], node[3]
    if not pos:
        raise ex.err("effect takes (stock, linear|table, ...)")
    e = {"stock": _stock(pos[0], ex, stocks)}
    shape = pos[1][1] if len(pos) > 1 and pos[1][0] == "name" else None
    if len(pos) > 1 and shape not in ("linear", "table"):
        raise ex.err("an effect's shape is linear or table")
    if shape:
        e["shape"] = shape
    if shape == "table":
        pts = pos[2] if len(pos) > 2 else kw.pop("points", None)
        if not pts or pts[0] != "list" or not all(isinstance(p, list) and len(p) == 2 for p in pts[1]):
            raise ex.err("a table effect needs its points: [[level, multiplier], ...]")
        if len(pos) > 3 or kw:
            raise ex.err("a table effect takes only its points")
        e["points"] = pts[1]
        return e
    if len(pos) > 2:
        raise ex.err("a linear effect takes normal=, max= and min= by name")
    for k, v in kw.items():
        if k not in ("normal", "max", "min"):
            raise ex.err(f"a linear effect has no {k!r} (normal, max, min)")
        e[k] = _num_value(v, ex, k)
    return e


def _fn_term(node, ex: _Expr, fns: dict, scale: float = 1.0) -> dict:
    """step(height, start), pulse(height, start, width=1), ramp(slope, start, end=never),
    pulse_train(height, first, width, every, last=never), sin(amplitude, period, phase=0): the engine's
    input term (sdtruth.input_value), its first number times scale."""
    name, pos, kw = node[1], node[2], node[3]
    keys = fns[name]
    if len(pos) > len(keys) or set(kw) - set(keys):
        raise ex.err(f"{name} takes ({', '.join(keys)})")
    vals = {k: _num_value(v, ex, k) for k, v in zip(keys, pos)}
    vals.update({k: _num_value(v, ex, k) for k, v in kw.items()})
    if any(k not in vals for k in keys[: REQUIRED[name]]):
        raise ex.err(f"{name} needs ({', '.join(keys[: REQUIRED[name]])})")
    vals[keys[0]] = vals[keys[0]] * scale
    return {"fn": name, **vals}


def _lift_tests(node, ex: _Expr) -> tuple:
    """The test inputs (step, pulse, ramp, pulse_train; optionally times a number) among a rate's
    top-level terms, taken out: (the rest of the rate or None, [input terms])."""
    terms = node[1] if node[0] == "sum" else [("+", node)]
    rest, tests = [], []
    for sign, n in terms:
        k = -1.0 if sign == "-" else 1.0
        if n[0] == "product" and len(n[1]) == 2 and n[1][0][1][0] == "num" and n[1][1][0] == "*" and n[1][1][1][0] == "call" and n[1][1][1][1] in TESTS:
            k, n = k * n[1][0][1][1], n[1][1][1]
        if n[0] == "call" and n[1] in TESTS:
            tests.append(_fn_term(n, ex, TESTS, k))
        else:
            rest.append((sign, n))
    if not tests:
        return node, []
    if not rest:
        return None, tests
    return (rest[0][1] if len(rest) == 1 and rest[0][0] == "+" else ("sum", rest)), tests


def _lift_smooths(node, ex: _Expr, names: set[str], out: dict, prior: dict | None = None, dt: float = 1.0):
    """smooth(x, time[, initial=]) and smooth3(...) replaced by the hidden stock that holds the smoothed
    value (its id added to names; out: {id: {"of", "time", "order", "initial"?}}); trend(x, time,
    initial trend) and forecast(x, time, horizon[, initial trend]) (2d) by the expression they are of
    such a stock (PySD's TREND and FORECAST: average = SMOOTH(x, time) from x / (1 + initial trend x time),
    resp. x / (1 + initial trend); trend = zidz(x - average, time x |average|), forecast =
    x (1 + zidz(x - average, time x average) x horizon))."""
    prior = {} if prior is None else prior
    if not isinstance(node, tuple):
        return node
    if node[0] == "call" and node[1] in TRENDS:
        return _lift_trend(node, ex, names, out)
    if node[0] == "call" and node[1] == "delayed":                 # x a fixed time ago (2d): an information pipe
        pos, kw = node[2], node[3]
        if len(pos) != 2 or set(kw) - {"initial"}:
            raise ex.err("delayed takes (stock, input or auxiliary, time, initial=its value during the first time)")
        of = _stock(pos[0], ex, names, "a stock, an input or an auxiliary")
        tau = _num_value(pos[1], ex, "a delay's time")
        if tau <= 0:
            raise ex.err("a delay's time is more than 0")
        n = max(1, round(tau / dt + 1e-6))
        sid = f"delayed_{of}_{str(tau).replace('.', 'p').replace('-', 'm')}"
        spec = {"of": of, "time": tau, "order": "pipe", "n": n, "dt": dt, **({"initial": _num_value(kw["initial"], ex, "initial")} if "initial" in kw else {})}
        base, i = sid, 2
        while (out.get(sid) or prior.get(sid) or spec) != spec:
            sid, i = f"{base}_s{i}", i + 1
        out[sid] = spec
        names.add(sid)
        return ("name", sid) if dt == 1 else ("group", ("product", [("*", ("name", sid)), ("/", ("num", dt))]))
    if node[0] == "call" and node[1] in SMOOTHS:
        pos, kw = node[2], node[3]
        if len(pos) != 2 or set(kw) - {"initial"}:
            raise ex.err(f"{node[1]} takes (stock or input, time, initial=level)")
        of = _stock(pos[0], ex, names, "a stock or an input")
        tau = _num_value(pos[1], ex, "a smoothing time")
        if tau <= 0:
            raise ex.err("a smoothing time is more than 0")
        sid = f"{node[1]}_{of}_{str(tau).replace('.', 'p').replace('-', 'm')}"
        spec = {"of": of, "time": tau, "order": SMOOTHS[node[1]], **({"initial": _num_value(kw["initial"], ex, "initial")} if "initial" in kw else {})}
        base, i = sid, 2
        while (out.get(sid) or prior.get(sid) or spec) != spec:     # the same smoothing from another start (2d): its own stock
            sid, i = f"{base}_s{i}", i + 1
        out[sid] = spec
        names.add(sid)
        return ("name", sid)
    if node[0] in ("sum", "product"):
        return (node[0], [(op, _lift_smooths(n, ex, names, out, prior, dt)) for op, n in node[1]])
    if node[0] == "group":
        return ("group", _lift_smooths(node[1], ex, names, out, prior, dt))
    if node[0] == "pow":
        return ("pow", _lift_smooths(node[1], ex, names, out, prior, dt), _lift_smooths(node[2], ex, names, out, prior, dt))
    if node[0] == "cmp":
        return ("cmp", node[1], _lift_smooths(node[2], ex, names, out, prior, dt), _lift_smooths(node[3], ex, names, out, prior, dt))
    if node[0] == "call":
        return ("call", node[1], [_lift_smooths(n, ex, names, out, prior, dt) for n in node[2]], {k: _lift_smooths(v, ex, names, out, prior, dt) for k, v in node[3].items()})
    return node


def _lift_trend(node, ex: _Expr, names: set[str], out: dict):
    fn, pos, kw = node[1], node[2], node[3]
    want = 3 if fn == "trend" else 4
    if kw or not (want - 1 <= len(pos) <= want):
        raise ex.err("trend takes (x, time, initial trend)" if fn == "trend" else "forecast takes (x, time, horizon, initial trend = 0)")
    of = _stock(pos[0], ex, names, "a stock, an input or an auxiliary")
    tau = _num_value(pos[1], ex, "an averaging time")
    if tau <= 0:
        raise ex.err("an averaging time is more than 0")
    g = _num_value(pos[2 if fn == "trend" else 3], ex, "an initial trend") if len(pos) == want else 0
    scale = 1 / (1 + g * tau) if fn == "trend" else 1 / (1 + g)
    sid = f"{fn}_{of}_{str(tau).replace('.', 'p').replace('-', 'm')}"
    if scale != 1:
        sid += "_g" + str(g).replace(".", "p").replace("-", "m")
    out[sid] = {"of": of, "time": tau, "order": 1, "scale": scale}
    names.add(sid)
    x, av = ("name", of), ("name", sid)
    gap = ("sum", [("+", x), ("-", av)])
    if fn == "trend":
        return ("call", "zidz", [gap, ("product", [("*", ("num", tau)), ("*", ("call", "abs", [av], {}))])], {})
    horizon = pos[2]
    return ("product", [("*", x), ("*", ("group", ("sum", [("+", ("num", 1)), ("+", ("product", [
        ("*", ("call", "zidz", [gap, ("product", [("*", ("num", tau)), ("*", av)])], {})), ("*", ("group", horizon))]))])))])


def flow_body(text, stocks: set[str], prior: dict | None = None, dt: float = 1.0) -> dict:
    """A flow's rate expression, effects and co-flows: {"rate": {...}, "effects"?: [...], "uses"?: [...]}.
    A rate may also be wrapped in delay1/delay3 ("_delay": {order, time, initial?}), read smooth/smooth3
    ("_smooths": {hidden id: {of, time, order, initial?}}) and add test inputs ("_tests": [input terms]);
    _flows compiles those into hidden stocks, flows and schedule changes."""
    if isinstance(text, bool) or not isinstance(text, (int, float, str)):
        raise CaseError(f"a rate is a number or an expression, not {text!r}")
    if not isinstance(text, str):
        return {"rate": {"form": "constant", "value": text}}
    text = INPUT_REF_RE.sub(r"\1", text)                           # input(pump) is pump
    ex = _Expr(text)
    if ex.done():
        raise CaseError("empty rate")
    node = ex.cmp()
    uses = []
    while not ex.done():
        if not ex.peek("uses"):
            raise ex.err("expected '*', '+', '-' or uses(stock, per)")
        ex.take("uses")
        pos, kw = ex.args()
        if len(pos) != 2 or kw:
            raise ex.err("uses takes (stock, per)")
        uses.append({"stock": _stock(pos[0], ex, stocks), "per": _num_value(pos[1], ex, "a co-flow's per")})
    extra: dict = {}
    if node[0] == "call" and node[1] in DELAYS:                    # delay3(rate, time, initial=level)
        pos, kw = node[2], node[3]
        if len(pos) != 2 or set(kw) - {"initial"}:
            raise ex.err(f"{node[1]} takes (rate, time, initial=level of each hidden stock)")
        try:
            time = _num_value(pos[1], ex, "a delay's time")
        except CaseError:                                          # a delay whose time changes (2d): an expression
            time = _engine_text(pos[1], ex, stocks)
        if not isinstance(time, str) and time <= 0:
            raise ex.err("a delay's time is more than 0")
        extra["_delay"] = {"order": DELAYS[node[1]], "time": time, **({"initial": _num_value(kw["initial"], ex, "initial")} if "initial" in kw else {})}
        node = pos[0]
    elif node[0] == "call" and node[1] == "delay_fixed":           # DELAY FIXED (2d): a pipe
        pos, kw = node[2], node[3]
        if len(pos) != 2 or set(kw) - {"initial"}:
            raise ex.err("delay_fixed takes (rate, time, initial=the rate that comes out during the first time)")
        time = _num_value(pos[1], ex, "a fixed delay's time")
        if time <= 0:
            raise ex.err("a delay's time is more than 0")
        extra["_delay"] = {"order": "fixed", "time": time, **({"initial": _num_value(kw["initial"], ex, "initial")} if "initial" in kw else {})}
        node = pos[0]
    smooths: dict = {}
    if any(f"{k}(" in text.replace(" ", "") for k in (*SMOOTHS, *TRENDS, "delayed")):
        stocks = set(stocks)
        node = _lift_smooths(node, ex, stocks, smooths, prior or {}, dt)
    if smooths:
        extra["_smooths"] = smooths
    if any(f"{k}(" in text.replace(" ", "") for k in TESTS):
        node, tests = _lift_tests(node, ex)
        if tests:
            extra["_tests"] = tests
        if node is None:
            node = ("num", 0)
    effects = []
    if node[0] == "product":                                       # rate * effect(...) * effect(...)
        keep = [p for p in node[1] if not (p[1][0] == "call" and p[1][1] == "effect")]
        for op, p in node[1]:
            if p[0] == "call" and p[1] == "effect":
                if op != "*":
                    raise ex.err("an effect multiplies a rate: rate * effect(...)")
                effects.append(_effect(p, ex, stocks))
        if effects:
            if not keep or keep[0][0] != "*":
                raise ex.err("an effect multiplies a rate: rate * effect(...)")
            node = ("product", keep) if len(keep) > 1 else keep[0][1]
    elif node[0] == "call" and node[1] == "effect":
        raise ex.err("an effect multiplies a rate: rate * effect(...)")
    try:
        out = {"rate": _rate(node, ex, stocks)}
    except CaseError as first:                                     # any other rate is an expression (2d)
        try:
            out = {"rate": {"form": "expr", "expr": _engine_text(node, ex, stocks)}}
        except CaseError as second:
            raise (second if "unknown stock" in str(second) or "not allowed" in str(second) else first) from None
    if effects:
        out["effects"] = effects
    if uses:
        out["uses"] = uses
    out.update(extra)
    return out


def _engine_text(node, ex: _Expr, readable: set[str]) -> str:
    """A rate that has no linear form as the engine's expression text (sdtruth_expr.py; 2d), checked:
    every name it reads is a stock, input, auxiliary or switch, every function one the engine has."""
    from ..sdtruth_expr import ExprError, names, parse

    def go(n) -> str:
        k = n[0]
        if k == "num":
            v = n[1]
            return str(v) if isinstance(v, int) else repr(v)
        if k == "name":
            return n[1]
        if k == "group":
            return go(n[1]) if n[1][0] in ("sum", "product", "pow", "cmp") else f"({go(n[1])})"
        if k == "sum":
            parts = []
            for i, (sign, x) in enumerate(n[1]):
                parts.append(("-" if sign == "-" else "") + go(x) if i == 0 else f" {sign} {go(x)}")
            return "(" + "".join(parts) + ")"
        if k == "product":
            return "(" + go(n[1][0][1]) + "".join(f" {op} {go(x)}" for op, x in n[1][1:]) + ")"
        if k == "pow":
            return f"({go(n[1])} ^ {go(n[2])})"
        if k == "cmp":
            return f"({go(n[2])} {n[1]} {go(n[3])})"
        if k == "list":
            return "[" + ", ".join("[" + ", ".join(repr(float(v)) for v in p) + "]" for p in n[1]) + "]"
        if k == "call":
            if n[3]:
                raise ex.err(f"{n[1]}() takes no named arguments inside an expression")
            if n[1] in ("effect", "uses", *DELAYS, "delay_fixed", *TESTS, *SMOOTHS, *TRENDS, "delayed"):
                raise ex.err(f"{n[1]}() is not allowed inside an expression")
            return f"{n[1]}({', '.join(go(a) for a in n[2])})"
        raise ex.err("not an expression")

    text = go(node)
    try:
        tree = parse(text)
    except ExprError as e:
        raise ex.err(str(e)) from None
    unknown = sorted(names(tree) - set(readable))
    if unknown:
        raise ex.err(f"unknown stock {unknown[0]!r}")
    return text


# ---- the case ----

def _at(m: _Map, key, name: str) -> str:
    return f"{name}:{m.lines.get(key, m.line)}" if isinstance(m, _Map) else name


def _stocks(raw, name: str) -> list[dict]:
    if not isinstance(raw, dict) or not raw:
        raise CaseError(f"{name}: stocks is a mapping of stock id to its initial level, e.g. {{A: 0, B: 0}}")
    out = []
    for sid, v in raw.items():
        where = _at(raw, sid, name)
        if not isinstance(sid, str) or not ID_RE.match(sid) or sid == OUTSIDE:
            raise CaseError(f"{where}: {sid!r} is not a stock id (letters, digits, _; not 'outside')")
        s = {"id": sid}
        if isinstance(v, dict):
            extra = dict(v)
            if "initial" not in extra:
                raise CaseError(f"{where}: stock {sid} needs an initial level")
            s["initial"] = extra.pop("initial")
            if extra.pop("hidden", False):
                s["measured"] = False
            s.update(extra)
        elif isinstance(v, str):
            words = v.split()
            try:
                s["initial"] = _number(words[0]) if words else None
            except ValueError:
                s["initial"] = None
            if s["initial"] is None:
                raise CaseError(f"{where}: stock {sid}: {v!r} should start with its initial level")
            for w in words[1:]:
                if w == "hidden":
                    s["measured"] = False
                elif w == "final":
                    s["final"] = True
                elif w == "signed":                                # may go negative (2d)
                    s["signed"] = True
                elif w == "net":                                   # its ceiling counts the step's outflows (2d)
                    s["max_net"] = True
                elif w.startswith("max="):
                    try:
                        s["max"] = _number(w[4:])
                    except ValueError:
                        raise CaseError(f"{where}: stock {sid}: {w!r}: a ceiling is max=<number>") from None
                else:
                    raise CaseError(f"{where}: stock {sid}: unknown word {w!r} (hidden, final, max=N, signed, net)")
        elif isinstance(v, (int, float)) and not isinstance(v, bool):
            s["initial"] = v
        else:
            raise CaseError(f"{where}: stock {sid}: {v!r} is not an initial level")
        if "max" in s and (isinstance(s["max"], bool) or not isinstance(s["max"], (int, float)) or s["max"] <= 0):
            raise CaseError(f"{where}: stock {sid}: a ceiling (max) is a number above 0")
        if s.get("max_net") and "max" not in s:
            raise CaseError(f"{where}: stock {sid}: net is a word of a ceiling (max=N net)")
        out.append(s)
    return out


def default_flow_id(src: str | None, dst: str | None, first_inflow: bool) -> str:
    """outside -> X: "in" for the case's first flow from outside (named or not), "x_in" after; X -> outside: "x_out";
    X -> Y: "xy" when both ids are one letter, else "x_y"."""
    if src is None:
        return "in" if first_inflow else f"{dst.lower()}_in"
    if dst is None:
        return f"{src.lower()}_out"
    return f"{src.lower()}{dst.lower()}" if len(src) == len(dst) == 1 else f"{src.lower()}_{dst.lower()}"


def _flow_items(raw, name: str) -> list[tuple[str, object, str]]:
    """(key, value, where) for each flow, from a mapping or a list of one-key mappings."""
    if isinstance(raw, dict):
        return [(k, v, _at(raw, k, name)) for k, v in raw.items()]
    if isinstance(raw, list):
        out = []
        for item in raw:
            if not isinstance(item, dict) or len(item) != 1:
                raise CaseError(f"{name}: each item of a flows list is one 'A -> B: rate'")
            k, v = next(iter(item.items()))
            out.append((k, v, _at(item, k, name)))
        return out
    raise CaseError(f"{name}: flows is a mapping of 'A -> B: rate'")


def _flows(raw, stocks: set[str], name: str, inputs: set[str] = frozenset(), hidden: list | None = None, also: set[str] = frozenset(),
           dt: float = 1.0) -> list[dict]:
    """The flows; a delay's or a smoothing's hidden stocks are appended to `hidden` (and their flows
    to the flows); a flow's test inputs are left on it as "_tests" for compile_case. also: other names a
    rate may read (auxiliaries and switches, 2d); dt: the case's sub-step (a fixed delay's stages)."""
    out, ids, inflow_seen = [], {}, False
    readable = set(stocks) | set(inputs) | set(also)
    smoothed: dict = {}
    for key, v, where in _flow_items(raw, name):
        m = FLOW_KEY_RE.match(str(key))
        two_way = False
        if not m:
            m = TWO_WAY_KEY_RE.match(str(key))
            two_way = bool(m)
        if not m:
            raise CaseError(f"{where}: {key!r} is not 'A -> B', 'A <-> B' or 'A -> B as id'")
        ends = []
        for end in m.group(1, 2):
            if end != OUTSIDE and end not in stocks:
                raise CaseError(f"{where}: unknown stock {end!r} (stocks: {', '.join(sorted(stocks))}; or outside)")
            ends.append(None if end == OUTSIDE else end)
        if ends == [None, None]:
            raise CaseError(f"{where}: a flow needs a stock at one end at least")
        fid = m.group(3)
        if fid is None:
            fid = default_flow_id(ends[0], ends[1], not inflow_seen)
        inflow_seen = inflow_seen or ends[0] is None
        if not ID_RE.match(fid):
            raise CaseError(f"{where}: {fid!r} is not a flow id")
        if fid in ids:
            raise CaseError(f"{where}: flow id {fid!r} is taken (by '{ids[fid]}'): name this one with '{m.group(1)} -> {m.group(2)} as <id>'")
        ids[fid] = key
        f = {"id": fid, "from": ends[0], "to": ends[1], **({"two_way": True} if two_way else {})}
        extra = {}
        if isinstance(v, dict):
            extra = dict(v)
            if "rate" not in extra:
                raise CaseError(f"{where}: flow {fid} needs a rate")
            v = extra.pop("rate")
        try:
            body = {"rate": dict(v)} if isinstance(v, dict) else flow_body(v, readable, smoothed, dt)
        except CaseError as e:
            raise CaseError(f"{where}: flow {key}: {e}") from None
        for u in body.get("uses") or []:
            if u["stock"] not in stocks:
                raise CaseError(f"{where}: flow {key}: uses({u['stock']}, ...) names an input, not a stock")
        for k in ("effects", "uses"):
            if k in body and k in extra:
                raise CaseError(f"{where}: flow {fid} has {k} in its rate and as a key")
        delay = body.pop("_delay", None)
        smoothed.update(body.pop("_smooths", None) or {})
        f.update(body)
        f.update(extra)
        if delay is None:
            out.append(f)
            continue
        if hidden is None:
            raise CaseError(f"{where}: a delay is not allowed here")
        out += _pipe(f, delay, stocks, hidden, where, dt) if delay["order"] == "fixed" else _delay_chain(f, delay, stocks, hidden, where)
    for sid, sm in smoothed.items():
        if hidden is None:
            raise CaseError(f"{name}: a smoothing is not allowed here")
        out += _smoothing(sid, sm, stocks, hidden)
    return out


def _delay_chain(f: dict, delay: dict, stocks: set[str], hidden: list, where: str) -> list[dict]:
    """DELAYn(rate, time) from A to B: A -> H1 at the rate (the flow keeps its id), then H1 -> H2 ...
    Hn -> B, each n / time x its hidden stock (an Erlang-n delay with mean `time`, exact as Vensim's
    DELAY3 is a chain of three first-order stages). Hidden stocks are <id>_d1 .. <id>_dn, starting
    at `initial` (default 0)."""
    n, time = delay["order"], delay["time"]
    hs = [f"{f['id']}_d{i}" for i in range(1, n + 1)]
    two = {"two_way": True} if f.get("two_way") else {}            # 2d: a two-way delay's stages may hold a negative amount
    for h in hs:
        if h in stocks or any(x["id"] == h for x in hidden):
            raise CaseError(f"{where}: the delay's hidden stock {h} clashes with a stock")
        hidden.append({"id": h, "initial": delay.get("initial", 0), "measured": False, **({"signed": True} if two else {})})
    tag = lambda i: {"id": f["id"], "stage": i, "of": n, "time": time}  # noqa: E731
    out = [{**f, "to": hs[0], "delay": tag(0)}]
    for i, h in enumerate(hs, start=1):
        rate = {"form": "expr", "expr": f"{n} * {h} / ({time})"} if isinstance(time, str) else {"form": "proportional", "stock": h, "k": n / time}
        out.append({"id": f"{f['id']}_{i}", "from": h, "to": hs[i] if i < n else f["to"], "rate": rate, "delay": tag(i), **two})
    return out


def _pipe(f: dict, delay: dict, stocks: set[str], hidden: list, where: str, dt: float) -> list[dict]:
    """DELAY FIXED(rate, time) from A to B (2d): A -> H1 at the rate (the flow keeps its id), then
    H1 -> H2 ... Hn -> B, n = time / dt stages (rounded, as PySD does), each passed on whole in one
    sub-step (k = 1 / dt, exact), so what leaves A arrives at B exactly `time` later. Each stage starts
    at initial x dt (initial: the rate that comes out during the first `time`, default 0)."""
    time = delay["time"]
    n = max(1, round(time / dt + 1e-6))
    hs = [f"{f['id']}_p{i}" for i in range(1, n + 1)]
    two = {"two_way": True} if f.get("two_way") else {}            # a two-way pipe's stages may hold a negative amount
    for h in hs:
        if h in stocks or any(x["id"] == h for x in hidden):
            raise CaseError(f"{where}: the fixed delay's hidden stock {h} clashes with a stock")
        hidden.append({"id": h, "initial": delay.get("initial", 0) * dt if dt != 1 else delay.get("initial", 0), "measured": False,
                       **({"signed": True} if two else {})})
    tag = lambda i: {"id": f["id"], "stage": i, "of": n, "time": time, "shape": "pipe"}  # noqa: E731
    out = [{**f, "to": hs[0], "delay": tag(0)}]
    for i, h in enumerate(hs, start=1):
        out.append({"id": f"{f['id']}_{i}", "from": h, "to": hs[i] if i < n else f["to"],
                    "rate": {"form": "proportional", "stock": h, "k": 1 / dt if dt != 1 else 1}, "exact": True, "delay": tag(i), **two})
    return out


def _smoothing(sid: str, sm: dict, stocks: set[str], hidden: list) -> list[dict]:
    """SMOOTHn(x, time): n hidden stocks in a row, the last (sid) holding the smoothed value; stage i
    fills at x_(i-1) x n / time from outside (it reads x, it does not drain it) and drains at its own
    level x n / time. Its flows are exact (no counting noise: information, not material). Each stage
    starts at `initial` (default: x's initial level when x is a stock, else 0)."""
    if sm["order"] == "pipe":
        return _info_pipe(sid, sm, stocks, hidden)
    n, k = sm["order"], sm["order"] / sm["time"]
    start = sm.get("initial", {"initial of": sm["of"], **({"scale": sm["scale"]} if "scale" in sm else {})})   # compile_case reads x's initial level
    names = [f"{sid}_{i}" for i in range(1, n)] + [sid]
    out, prev = [], sm["of"]
    for h in names:
        if h in stocks or any(x["id"] == h for x in hidden):
            continue                                              # the same smoothing used twice
        hidden.append({"id": h, "initial": start, "measured": False})
        out.append({"id": f"{h}_in", "from": None, "to": h, "rate": {"form": "proportional", "stock": prev, "k": k}, "exact": True})
        out.append({"id": f"{h}_out", "from": h, "to": None, "rate": {"form": "proportional", "stock": h, "k": k}, "exact": True})
        prev = h
    return out


def _info_pipe(sid: str, sm: dict, stocks: set[str], hidden: list) -> list[dict]:
    """delayed(x, time) (2d): x as it was `time` ago (Vensim's DELAY FIXED of information). n = time / dt
    hidden stages <sid>_1 .. <sid>_(n-1), sid: the first fed from outside at x, each passed on whole in
    one sub-step, the last (sid) drained to outside; sid holds x(t - time) x dt at the start of a
    sub-step, so the reader is sid / dt. Signed stages and two-way exact flows (information may be
    negative). Each stage starts at initial x dt (initial: the value during the first `time`; default:
    x's initial level when x is a stock, else 0)."""
    n, dt = sm["n"], sm["dt"]
    start = sm["initial"] * dt if "initial" in sm else {"initial of": sm["of"], "scale": dt}
    names = [f"{sid}_{i}" for i in range(1, n)] + [sid]
    if any(h in stocks or any(x["id"] == h for x in hidden) for h in names):
        return []                                                  # the same delay used twice
    out, k = [], (1 / dt if dt != 1 else 1)
    for i, h in enumerate(names):
        hidden.append({"id": h, "initial": start, "measured": False, "signed": True})
        if i == 0:
            out.append({"id": f"{h}_in", "from": None, "to": h, "rate": {"form": "proportional", "stock": sm["of"], "k": 1}, "exact": True, "two_way": True})
        out.append({"id": f"{h}_out", "from": h, "to": names[i + 1] if i + 1 < n else None, "rate": {"form": "proportional", "stock": h, "k": k},
                    "exact": True, "two_way": True})
    return out


def _flow_ref(ref, flows: list[dict], where: str) -> str:
    """A flow in a schedule: its id, or its ends ('A -> B') when one flow has them."""
    if any(f["id"] == ref for f in flows):
        return ref
    m = FLOW_KEY_RE.match(str(ref)) or TWO_WAY_KEY_RE.match(str(ref))
    if m and not m.group(3):
        ends = [None if e == OUTSIDE else e for e in m.group(1, 2)]
        got = [f["id"] for f in flows if [f["from"], f["to"]] == ends]
        if len(got) == 1:
            return got[0]
        if got:
            raise CaseError(f"{where}: {ref!r} is ambiguous ({', '.join(got)}): use a flow id")
    raise CaseError(f"{where}: no flow {ref!r} (flows: {', '.join(f['id'] for f in flows)})")


def _schedule(raw, flows: list[dict], stocks: set[str], name: str) -> dict:
    if not isinstance(raw, dict):
        raise CaseError(f"{name}: schedule is a mapping: every: N, then 'at T label: {{flow: rate}}' lines")
    out = {}
    if "every" in raw:
        out["every"] = raw["every"]
    if "changes" in raw:                                           # the JSON form, as is
        out["changes"] = raw["changes"]
    else:
        out["changes"] = []
    for key, v in raw.items():
        if key in ("every", "changes"):
            continue
        where = _at(raw, key, name)
        m = CHANGE_KEY_RE.match(str(key))
        if not m:
            raise CaseError(f"{where}: {key!r} is not 'at T [label] [announced]'")
        rest, announce = m.group(2), False
        if rest == "announced" or rest.endswith(" announced"):
            rest, announce = rest[: -len("announced")].strip(), True
        if len(rest) >= 2 and rest[0] == rest[-1] and rest[0] in "\"'":
            rest = rest[1:-1]
        change = {"t": int(m.group(1))}
        if rest:
            change["label"] = rest
        if v is None:
            v = {}
        if not isinstance(v, dict):
            raise CaseError(f"{where}: a change is a mapping of flow to its new rate")
        sets = {}
        for ref, expr in v.items():
            fid = _flow_ref(ref, flows, where)
            try:
                body = {"rate": dict(expr)} if isinstance(expr, dict) else flow_body(expr, stocks)
            except CaseError as e:
                raise CaseError(f"{where}: {ref}: {e}") from None
            if set(body) != {"rate"}:
                raise CaseError(f"{where}: {ref}: a schedule changes a rate only (no effects or uses)")
            sets[fid] = body["rate"]
        change["set"] = sets
        if announce:
            change["announce"] = True
        out["changes"].append(change)
    return out


def compile_case(text: str, name: str = "<case>") -> dict:
    """A YAML case as the case dict the loader takes: {title, level, tags, tests, tolerance?, variants?,
    model: {seed?, stocks, flows, schedule?, injections?}}."""
    try:
        raw = yaml.load(text, Loader=_Loader)
    except CaseError as e:
        raise CaseError(f"{name}:{e}") from None
    except yaml.YAMLError as e:
        mark = getattr(e, "problem_mark", None)
        raise CaseError(f"{name}:{mark.line + 1 if mark else '?'}: not valid YAML: {getattr(e, 'problem', None) or e}") from None
    if not isinstance(raw, dict):
        raise CaseError(f"{name}: a case is a mapping (title, level, tags, tests, stocks, flows, ...)")
    unknown = [k for k in raw if k not in TOP_KEYS]
    if unknown:
        raise CaseError(f"{_at(raw, unknown[0], name)}: unknown key {unknown[0]!r} (keys: {', '.join(sorted(TOP_KEYS))})")
    for k in ("stocks", "flows"):
        if k not in raw:
            raise CaseError(f"{name}: a case needs {k}")
    if "draws" in raw:
        raise CaseError(f"{_at(raw, 'draws', name)}: draws is for a case with draw(lo, hi) numbers (draws.py), and this one has none")
    out = {k: raw[k] for k in ("title", "level", "tags", "tests", "tolerance", "source") if k in raw}   # source: where a case comes from, and its licence
    if "boundary" in raw:                                           # declared (even empty); checked against the model in cases.py
        out["boundary"] = boundary_spec(raw["boundary"], _at(raw, "boundary", name))
    v = raw.get("variants")
    if v is not None and v != "default":
        out["variants"] = v
    stocks = _stocks(raw["stocks"], name)
    ids = {s["id"] for s in stocks}
    inputs = _inputs(raw["inputs"], ids, _at(raw, "inputs", name)) if raw.get("inputs") else {}
    switches = _switches(raw["switches"], ids | set(inputs), _at(raw, "switches", name)) if raw.get("switches") else []
    names = ids | set(inputs) | {s["id"] for s in switches}
    aux = _auxiliaries(raw["auxiliaries"], names, _at(raw, "auxiliaries", name)) if raw.get("auxiliaries") else {}
    for sw in switches:
        sw["switch"]["of"] = _check_names(sw["switch"]["of"], names | set(aux), f"{_at(raw, 'switches', name)}: switch {sw['id']}")
    hidden: list[dict] = []
    dt = _dt(raw["dt"], _at(raw, "dt", name)) if "dt" in raw else 1.0
    flows = _flows(raw["flows"], ids, name, set(inputs), hidden, {s["id"] for s in switches} | set(aux), float(dt))
    first = {s["id"]: s["initial"] for s in stocks}
    for h in hidden:                                               # a smoothing starts at what it smooths
        if isinstance(h["initial"], dict):
            h["initial"] = first.get(h["initial"]["initial of"], 0) * h["initial"].get("scale", 1) if "scale" in h["initial"] \
                else first.get(h["initial"]["initial of"], 0)
    stocks = stocks + switches + hidden
    model = {**({"seed": raw["seed"]} if "seed" in raw else {}), "stocks": stocks, "flows": flows}
    if aux:
        model["auxiliaries"] = aux
    if "dt" in raw:
        model["dt"] = _dt(raw["dt"], _at(raw, "dt", name))
    if inputs:
        model["inputs"] = inputs
    if raw.get("schedule"):
        model["schedule"] = _schedule(raw["schedule"], flows, ids | set(inputs) | {s["id"] for s in switches} | set(aux), name)
    if any(f.get("_tests") for f in flows):
        _test_changes(model, raw, _at(raw, "flows", name))
    if raw.get("injections"):
        inj = raw["injections"]
        if not isinstance(inj, list) or not all(isinstance(j, dict) and {"t", "stock", "amount"} <= set(j) for j in inj):
            raise CaseError(f"{_at(raw, 'injections', name)}: injections is a list of {{t: T, stock: S, amount: N}}")
        for j in inj:
            if j["stock"] not in ids:
                raise CaseError(f"{_at(raw, 'injections', name)}: injection into unknown stock {j['stock']!r}")
        model["injections"] = inj
    from ..sdtruth import _Program, uses_2d
    if uses_2d(model):                                             # the engine's own checks of 2d's features
        from ..sdtruth_expr import ExprError
        try:
            _Program(model)
        except ExprError as e:
            raise CaseError(f"{name}: {e}") from None
    out["model"] = model
    return _plain(out)


BOUNDARY_KINDS = ("measured", "estimate")       # driven by a measured input series / exists, form and rate to estimate


def boundary_spec(raw, where: str = "boundary") -> dict:
    """A case's declared boundary as {stock: {"in": [kinds], "out": [kinds]}} (kinds: BOUNDARY_KINDS; one
    per outside flow; a stock not listed has none). `{}`, `none` or null: declared, no outside flows at all.
    Only the stock and the kind: never a form or a rate. The stocks are checked against the model in
    cases.py (boundary_problems)."""
    if raw is None or raw == "none":
        return {}
    if not isinstance(raw, dict):
        raise CaseError(f"{where}: boundary is a mapping of stock to {{in: kinds, out: kinds}} (kinds: measured, estimate), or {{}} for none")
    out = {}
    for stock, v in raw.items():
        at = f"{where.split(':')[0]}:{raw.lines.get(stock)}" if isinstance(raw, _Map) and raw.lines.get(stock) else where
        if not isinstance(stock, str) or not ID_RE.match(stock):
            raise CaseError(f"{at}: boundary: {stock!r} is not a stock id")
        if v is None or v == "none":
            v = {}
        if not isinstance(v, dict) or set(v) - {"in", "out"}:
            raise CaseError(f"{at}: boundary of {stock}: {{in: kinds, out: kinds}} (kinds: measured, estimate)")
        entry = {}
        for side in ("in", "out"):
            kinds = v.get(side) or []
            kinds = [kinds] if isinstance(kinds, str) else kinds
            if not isinstance(kinds, list) or any(k not in BOUNDARY_KINDS for k in kinds):
                raise CaseError(f"{at}: boundary of {stock}: {side} is a kind or a list of kinds (measured, estimate), not {v.get(side)!r}")
            entry[side] = list(kinds)
        if entry["in"] or entry["out"]:
            out[stock] = entry
    return out


def boundary_problems(boundary: dict, model: dict) -> list[str]:
    """What a declared boundary gets wrong about the case's true model: a stock that is not measured
    (announcing it would leak a hidden stock), an outside flow of the truth on a stock and side the
    boundary does not declare, a declared side the truth has no outside flow on, a "measured" kind in a
    case with no measured inputs."""
    from .parts import outside_ends                                 # the scorer's reading of where outside flows reach
    measured = {s["id"] for s in model.get("stocks") or [] if s.get("measured", True)}     # the page's stocks
    problems = [f"boundary: {s} is not a measured stock" for s in boundary if s not in measured]
    truth = outside_ends(model.get("flows") or [], measured)
    for s, side in sorted(truth):
        if not (boundary.get(s) or {}).get(side):
            problems.append(f"boundary: the model has an outside {'inflow to' if side == 'in' else 'outflow from'} {s}, not declared")
    for s, e in boundary.items():
        for side in ("in", "out"):
            if e.get(side) and (s, side) not in truth and s in measured:
                problems.append(f"boundary: {s} declares an outside {'inflow' if side == 'in' else 'outflow'} the model does not have")
    if any("measured" in e.get(side, []) for e in boundary.values() for side in ("in", "out")) and not model.get("inputs"):
        problems.append("boundary: a 'measured' outside flow needs a measured input (inputs:)")
    return problems


def _check_names(text, readable: set[str], where: str) -> str:
    """An expression (the engine's syntax; input(x) is x) that reads only these names."""
    from ..sdtruth_expr import ExprError, parse
    text = INPUT_REF_RE.sub(r"\1", str(text)) if not isinstance(text, (int, float)) else text
    try:
        ex = _Expr(str(text))
        out = _engine_text(ex.cmp(), ex, readable)
        if not ex.done():
            raise ex.err("unexpected text after the expression")
        parse(out)
    except (CaseError, ExprError) as e:
        raise CaseError(f"{where}: {e}") from None
    return out


def _auxiliaries(raw, readable: set[str], where: str) -> dict:
    """auxiliaries: {name: expression} (2d): algebraic variables a rate reads by name, each computed
    from the levels and inputs (and the auxiliaries before it) in every sub-step."""
    if not isinstance(raw, dict):
        raise CaseError(f"{where}: auxiliaries is a mapping of name to its expression")
    out = {}
    for k, v in raw.items():
        at = _at(raw, k, where.split(":")[0])
        if not isinstance(k, str) or not ID_RE.match(k) or k == OUTSIDE or k in readable:
            raise CaseError(f"{at}: {k!r} is not an auxiliary name (letters, digits, _; not a stock's or input's id)")
        out[k] = v
    known = set(readable) | set(out)
    return {k: _check_names(v, known, f"{_at(raw, k, where.split(':')[0])}: auxiliary {k}") for k, v in out.items()}


def _switches(raw, readable: set[str], where: str) -> list[dict]:
    """switches: {id: {of, on_below, off_above | on_above, off_below, initial = 0, measured = false}}
    (2d): a hidden stock that is 1 or 0, set in every sub-step from `of` (an expression): on below one
    level and off above another, held in between (or the reverse), never moved by flows."""
    if not isinstance(raw, dict):
        raise CaseError(f"{where}: switches is a mapping of switch id to {{of, on_below, off_above}}")
    out = []
    for k, v in raw.items():
        at = _at(raw, k, where.split(":")[0])
        if not isinstance(k, str) or not ID_RE.match(k) or k == OUTSIDE or k in readable:
            raise CaseError(f"{at}: {k!r} is not a switch id (letters, digits, _; not a stock's or input's id)")
        if not isinstance(v, dict) or "of" not in v:
            raise CaseError(f"{at}: switch {k} is {{of: expression, on_below: N, off_above: M}} (or on_above, off_below)")
        rule = {x: v[x] for x in ("on_below", "off_above", "on_above", "off_below") if x in v}
        if set(rule) not in ({"on_below", "off_above"}, {"on_above", "off_below"}) or not all(
                isinstance(x, (int, float)) and not isinstance(x, bool) for x in rule.values()):
            raise CaseError(f"{at}: switch {k} needs numbers on_below and off_above, or on_above and off_below")
        unknown = set(v) - {"of", "initial", "measured", *rule}
        if unknown:
            raise CaseError(f"{at}: switch {k}: unknown key {sorted(unknown)[0]!r}")
        if v.get("initial", 0) not in (0, 1):
            raise CaseError(f"{at}: switch {k} starts at 0 or 1")
        out.append({"id": k, "initial": v.get("initial", 0), **({} if v.get("measured") else {"measured": False}),
                    "switch": {"of": v["of"], **rule}})
    return out


def _dt(v, where: str) -> float:
    from ..sdtruth import substeps
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise CaseError(f"{where}: dt is a number, 1/n for a whole number n (0.5, 0.25, 0.1)")
    try:
        substeps({"dt": v})
    except ValueError as e:
        raise CaseError(f"{where}: {e}") from None
    return v


def _input_formula(text, where: str) -> list[dict]:
    """A formula: a sum of numbers and step/pulse/ramp/pulse_train/sin terms (each optionally times
    a number) as the engine's input terms."""
    if isinstance(text, (int, float)) and not isinstance(text, bool):
        return [{"fn": "constant", "value": text}]
    ex = _Expr(str(text))
    if ex.done():
        raise CaseError(f"{where}: an empty formula")
    try:
        node = ex.sum()
        if not ex.done():
            raise ex.err("expected '+' or '-'")
        out = []
        for sign, n in (node[1] if node[0] == "sum" else [("+", node)]):
            k = -1 if sign == "-" else 1
            if n[0] == "num":
                out.append({"fn": "constant", "value": k * n[1]})
                continue
            if n[0] == "product" and len(n[1]) == 2 and n[1][0][1][0] == "num" and n[1][1][0] == "*":
                k, n = k * n[1][0][1][1], n[1][1][1]
            if n[0] != "call" or n[1] not in INPUT_FNS:
                raise ex.err(f"an input formula adds numbers and {', '.join(INPUT_FNS)}")
            out.append(_fn_term(n, ex, INPUT_FNS, k))
        return out
    except CaseError as e:
        raise CaseError(f"{where}: {e}") from None


def _read_series(spec: dict, where: str) -> list[float]:
    """A column of a .csv file (by name, or the only column) or a .json list, in sdlab/ladder/cases/."""
    rel = str(spec["file"])
    path = (CASES_DIR / rel).resolve()
    if CASES_DIR not in path.parents or not path.is_file():
        raise CaseError(f"{where}: no file {rel!r} under sdlab/ladder/cases/")
    if path.suffix == ".json":
        vals = __import__("json").loads(path.read_text())
    elif path.suffix == ".csv":
        import csv
        rows = list(csv.reader(path.read_text().splitlines()))
        head, body = rows[0], [r for r in rows[1:] if r]
        col = spec.get("column")
        if col is None and len(head) != 1:
            raise CaseError(f"{where}: {rel} has columns {head}: say which (column: <name>)")
        i = 0 if col is None else (head.index(col) if col in head else -1)
        if i < 0:
            raise CaseError(f"{where}: {rel} has no column {col!r} (columns: {head})")
        vals = [r[i] for r in body]
    else:
        raise CaseError(f"{where}: an input file is .csv or .json")
    try:
        return [float(x) for x in vals]
    except (TypeError, ValueError):
        raise CaseError(f"{where}: {rel}: every value must be a number") from None


def _inputs(raw, stocks: set[str], where: str) -> dict:
    """inputs: {name: series | formula | {values?, file?, column?, formula?, repeat?}} as the engine's
    {name: {"values"?, "repeat"?, "terms"?}}."""
    if not isinstance(raw, dict):
        raise CaseError(f"{where}: inputs is a mapping of input name to its series, formula or file")
    out = {}
    for k, v in raw.items():
        at = _at(raw, k, where.split(":")[0])
        if not isinstance(k, str) or not ID_RE.match(k) or k == OUTSIDE or k in stocks:
            raise CaseError(f"{at}: {k!r} is not an input name (letters, digits, _; not a stock's id)")
        spec: dict = {}
        if isinstance(v, list):
            v = {"values": v}
        elif not isinstance(v, dict):
            v = {"formula": v}
        unknown = set(v) - {"values", "file", "column", "formula", "repeat"}
        if unknown:
            raise CaseError(f"{at}: input {k}: unknown key {sorted(unknown)[0]!r} (values, file, column, formula, repeat)")
        if "values" in v and "file" in v:
            raise CaseError(f"{at}: input {k}: values or file, not both")
        if "values" in v:
            if not v["values"] or not all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in v["values"]):
                raise CaseError(f"{at}: input {k}: values is a list of numbers")
            spec["values"] = list(v["values"])
        if "file" in v:
            spec["values"] = _read_series(v, at)
        if v.get("repeat"):
            spec["repeat"] = True
        if "formula" in v:
            spec["terms"] = _input_formula(v["formula"], at)
        if not spec.get("values") and not spec.get("terms"):
            raise CaseError(f"{at}: input {k} needs values, a file or a formula")
        out[k] = spec
    return out


def _with_constant(rate: dict, c: float) -> dict:
    """A rate with c added (before its floor at 0): constant + c, k X + c, c + terms, and a gap
    (goal - X) / time + c = (goal + c time - X) / time."""
    form = rate.get("form")
    if c == 0:
        return dict(rate)
    if form == "constant":
        return {**rate, "value": rate.get("value", 0) + c}
    if form == "proportional":
        return {"form": "linear", "c": c, "terms": [{"stock": rate["stock"], "k": rate["k"]}]}
    if form == "linear":
        return {**rate, "c": rate.get("c", 0) + c}
    if form == "gap":
        return {**rate, "goal": rate["goal"] + c * rate["time"]}
    if form == "expr":
        return {**rate, "expr": f"({rate['expr']}) + {c!r}"}
    raise CaseError(f"a test input cannot be added to a rate of form {form}")


def _test_changes(model: dict, raw: dict, where: str) -> None:
    """A flow's test inputs (step, pulse, ramp, pulse_train) as unannounced schedule changes: at every
    step where their sum differs from the step before, the flow's rate becomes its own plus the sum
    (the rate at step 1 includes it). Written out up to the case's longest run (pulse trains and ramps
    hold their last value after it)."""
    from ..sdtruth import input_value
    sch = model.setdefault("schedule", {"changes": []})
    if sch.get("every"):
        raise CaseError(f"{where}: test inputs (step, pulse, ...) cannot be combined with a periodic schedule (every)")
    lengths = ((raw.get("variants") or {}) if isinstance(raw.get("variants"), dict) else {}).get("lengths") or {"long": 2000}
    horizon = max(int(x) for x in lengths.values())
    changes: dict[int, dict] = {}
    for f in model["flows"]:
        tests = f.pop("_tests", None)
        if not tests:
            continue
        if any(f["id"] in (c.get("set") or {}) for c in sch["changes"]):
            raise CaseError(f"{where}: flow {f['id']} has test inputs and schedule changes: write one or the other")
        base, spec = f["rate"], {"terms": tests}
        f["rate"] = _with_constant(base, input_value(spec, 1, 1))
        last = input_value(spec, 1, 1)
        for t in range(2, horizon + 1):
            v = input_value(spec, t, t)
            if v != last:
                changes.setdefault(t, {"t": t, "label": "test input", "set": {}})["set"][f["id"]] = _with_constant(base, v)
                last = v
    sch["changes"] = sch["changes"] + [changes[t] for t in sorted(changes)]
    if not sch["changes"]:
        del model["schedule"]


def _plain(x):
    """Plain dicts and lists (the loader's line-carrying dicts are dropped)."""
    if isinstance(x, dict):
        return {k: _plain(v) for k, v in x.items()}
    if isinstance(x, list):
        return [_plain(v) for v in x]
    return x
