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
TOP_KEYS = {"title", "level", "tags", "tests", "seed", "stocks", "flows", "schedule", "injections", "variants", "tolerance", "draws"}
FORMS = {"constant", "proportional", "gap", "linear", "available"}
ID_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
FLOW_KEY_RE = re.compile(r"^\s*(\S+)\s*->\s*(\S+)\s*(?:\bas\s+(\S+)\s*)?$")
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

TOKEN_RE = re.compile(r"\s*(?:(?P<num>(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?)|(?P<name>[A-Za-z_][A-Za-z0-9_]*)|(?P<op>[-+*/(),=\[\]]))")


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

    # grammar: sum := ['-'] product (('+'|'-') product)*;  product := factor (('*'|'/') factor)*
    #          factor := number | name | name '(' args ')' | '(' sum ')' | '[' list ']'
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
        if self.peek(kind="num"):
            return ("num", _number(self.take(kind="num")))
        if self.peek("("):
            self.take("(")
            inner = self.sum()
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
                kw[k] = self.sum()
            else:
                pos.append(self.sum())
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


def flow_body(text, stocks: set[str]) -> dict:
    """A flow's rate expression, effects and co-flows: {"rate": {...}, "effects"?: [...], "uses"?: [...]}."""
    if isinstance(text, bool) or not isinstance(text, (int, float, str)):
        raise CaseError(f"a rate is a number or an expression, not {text!r}")
    if not isinstance(text, str):
        return {"rate": {"form": "constant", "value": text}}
    ex = _Expr(text)
    if ex.done():
        raise CaseError("empty rate")
    node = ex.sum()
    uses = []
    while not ex.done():
        if not ex.peek("uses"):
            raise ex.err("expected '*', '+', '-' or uses(stock, per)")
        ex.take("uses")
        pos, kw = ex.args()
        if len(pos) != 2 or kw:
            raise ex.err("uses takes (stock, per)")
        uses.append({"stock": _stock(pos[0], ex, stocks), "per": _num_value(pos[1], ex, "a co-flow's per")})
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
    out = {"rate": _rate(node, ex, stocks)}
    if effects:
        out["effects"] = effects
    if uses:
        out["uses"] = uses
    return out


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
                else:
                    raise CaseError(f"{where}: stock {sid}: unknown word {w!r} (hidden, final)")
        elif isinstance(v, (int, float)) and not isinstance(v, bool):
            s["initial"] = v
        else:
            raise CaseError(f"{where}: stock {sid}: {v!r} is not an initial level")
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


def _flows(raw, stocks: set[str], name: str) -> list[dict]:
    out, ids, inflow_seen = [], {}, False
    for key, v, where in _flow_items(raw, name):
        m = FLOW_KEY_RE.match(str(key))
        if not m:
            raise CaseError(f"{where}: {key!r} is not 'A -> B' or 'A -> B as id'")
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
        f = {"id": fid, "from": ends[0], "to": ends[1]}
        extra = {}
        if isinstance(v, dict):
            extra = dict(v)
            if "rate" not in extra:
                raise CaseError(f"{where}: flow {fid} needs a rate")
            v = extra.pop("rate")
        try:
            body = {"rate": dict(v)} if isinstance(v, dict) else flow_body(v, stocks)
        except CaseError as e:
            raise CaseError(f"{where}: flow {key}: {e}") from None
        for k in ("effects", "uses"):
            if k in body and k in extra:
                raise CaseError(f"{where}: flow {fid} has {k} in its rate and as a key")
        f.update(body)
        f.update(extra)
        out.append(f)
    return out


def _flow_ref(ref, flows: list[dict], where: str) -> str:
    """A flow in a schedule: its id, or its ends ('A -> B') when one flow has them."""
    if any(f["id"] == ref for f in flows):
        return ref
    m = FLOW_KEY_RE.match(str(ref))
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
    out = {k: raw[k] for k in ("title", "level", "tags", "tests", "tolerance") if k in raw}
    v = raw.get("variants")
    if v is not None and v != "default":
        out["variants"] = v
    stocks = _stocks(raw["stocks"], name)
    ids = {s["id"] for s in stocks}
    flows = _flows(raw["flows"], ids, name)
    model = {**({"seed": raw["seed"]} if "seed" in raw else {}), "stocks": stocks, "flows": flows}
    if raw.get("schedule"):
        model["schedule"] = _schedule(raw["schedule"], flows, ids, name)
    if raw.get("injections"):
        inj = raw["injections"]
        if not isinstance(inj, list) or not all(isinstance(j, dict) and {"t", "stock", "amount"} <= set(j) for j in inj):
            raise CaseError(f"{_at(raw, 'injections', name)}: injections is a list of {{t: T, stock: S, amount: N}}")
        for j in inj:
            if j["stock"] not in ids:
                raise CaseError(f"{_at(raw, 'injections', name)}: injection into unknown stock {j['stock']!r}")
        model["injections"] = inj
    out["model"] = model
    return _plain(out)


def _plain(x):
    """Plain dicts and lists (the loader's line-carrying dicts are dropped)."""
    if isinstance(x, dict):
        return {k: _plain(v) for k, v in x.items()}
    if isinstance(x, list):
        return [_plain(v) for v in x]
    return x
