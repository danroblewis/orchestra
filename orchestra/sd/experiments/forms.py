"""The model's equations in the equation language (``language``), and the language back into an
``Equation``, so a machine reads every flow exactly as it would write it.

**From the model.** Each form the model holds is written as a text and its parameters, named as
``Equation.params`` names them:

| form | text | parameters |
|---|---|---|
| no equation | ``observed()`` | |
| ``constant`` | ``c`` | c |
| ``proportional`` | ``k * X`` (X the stock or input it reads, else the flow's source) | k |
| ``linear`` | ``c + k * X`` | c, k |
| SD Lab ``constant`` | ``value`` | value |
| SD Lab ``proportional`` | ``k * X`` | k |
| SD Lab ``linear`` | ``c + k1 * A + k2 * B …`` | c, k1, k2… |
| SD Lab ``gap`` | ``(goal - X) / time`` | goal, time |
| SD Lab ``expr`` | ``(<its expression>) / per_step_of_time_unit`` (its numbers as written) | per_step_of_time_unit |
| SD Lab ``sum`` | ``max(0, <part 1>) + max(0, <part 2>) …`` (each part's parameters prefixed ``p1_``, ``p2_``…) | |

An SD Lab rate's effects multiply it: a linear effect is ``clip(X / normal, min, max)``, a table
``max(0, lookup(X, [[x, y], …]))``, with their numbers as written. A rate below 0 is 0 in the
language as in SD Lab's simulator, so no floor is written.

**Into the model.** A text is kept as written, as an equation of form ``expr`` whose ``spec`` is
``{"language": "orchestra", "text": …}`` and whose ``inputs`` are what it reads, except the three
classic forms written exactly as above (``c``, ``k * X``, ``c + k * X``), which become those forms,
so the rest of Orchestra (the era comparison, the verdicts, the trust flags) reads them as it reads
a fitted equation. Either way the text renders back exactly. Its origin is ``declared`` and its
method says who wrote it (AGENTS.md rule 6: an equation is an assumption until it is fitted)."""

from __future__ import annotations

import ast

from ..model import Equation, Flow, Model
from .language import EquationError, Parsed, name_of

LANGUAGE = "orchestra"
OBSERVED = "observed()"


class Names:
    """The names a model's equations may read: its stocks and its measured inputs."""

    def __init__(self, stocks, inputs):
        self.stocks, self.inputs = list(stocks), list(inputs)

    @classmethod
    def of(cls, model: Model, extra_inputs=()) -> Names:
        return cls([s.id for s in model.stocks], [*measured_inputs(model), *extra_inputs])

    def ref(self, x: str) -> str:
        """A stock id, or ``input:<name>``, as the language writes it."""
        if x.startswith("input:"):
            return name_of("input", x[6:], self.stocks, self.inputs)
        return name_of("stock", x, self.stocks, self.inputs)

    def bare(self, x: str) -> str:
        """A name SD Lab's rate reads (a stock or a measured input, unprefixed), as the language
        writes it."""
        return self.ref(x if x in self.stocks or x not in self.inputs else f"input:{x}")


def measured_inputs(model: Model) -> list[str]:
    """The measured inputs (gauges that are not stocks) the model's equations may read."""
    names = list((model.discovery or {}).get("inputs") or {})
    for f in model.flows:
        for x in (f.current().inputs if f.current() else []):
            if x.startswith("input:") and x[6:] not in names:
                names.append(x[6:])
    return names


def _num(v) -> str:
    return repr(float(v))


def _effects(effects: list[dict], names: Names) -> list[str]:
    out = []
    for e in effects or []:
        x = names.bare(e.get("stock")) if e.get("stock") else "0"
        if e.get("shape") == "table" and e.get("points"):
            pts = ", ".join(f"[{_num(a)}, {_num(b)}]" for a, b in sorted((float(a), float(b)) for a, b in e["points"]))
            out.append(f"max(0, lookup({x}, [{pts}]))")
        else:
            lo = float(e["min"]) if e.get("min") is not None else 0.0
            hi = float(e["max"]) if e.get("max") is not None else 1.0
            out.append(f"clip({x} / {_num(max(1e-9, float(e.get('normal') or 1)))}, {_num(lo)}, {_num(hi)})")
    return out


def _spec(rate: dict, names: Names, prefix: str = "") -> tuple[str, dict[str, float]]:
    """An SD Lab rate (per time unit) as text and parameters."""
    form = rate.get("form")
    p = lambda k: f"{prefix}{k}"
    if form == "constant":
        text, params = p("value"), {p("value"): float(rate.get("value") or 0.0)}
    elif form == "proportional":
        text, params = f"{p('k')} * {names.bare(rate['stock'])}", {p("k"): float(rate.get("k") or 0.0)}
    elif form == "linear":
        params = {p("c"): float(rate.get("c") or 0.0)}
        parts = [p("c")]
        for i, t in enumerate(rate.get("terms") or []):
            params[p(f"k{i + 1}")] = float(t.get("k") or 0.0)
            parts.append(f"{p(f'k{i + 1}')} * {names.bare(t['stock'])}")
        text = " + ".join(parts)
    elif form == "gap":
        text = f"({p('goal')} - {names.bare(rate['stock'])}) / {p('time')}"
        params = {p("goal"): float(rate.get("goal") or 0.0), p("time"): float(rate.get("time") or 1.0)}
    elif form == "expr":
        inner = _sdlab_expr(str(rate.get("expr") or "0"), names)
        if "per_step_of_time_unit" in rate:
            text, params = f"({inner}) / {p('per_step_of_time_unit')}", {p("per_step_of_time_unit"): float(rate["per_step_of_time_unit"])}
        else:
            text, params = inner, {}
    elif form == "sum":
        parts, params = [], {}
        for i, part in enumerate(rate.get("parts") or []):
            t, ps = _spec(part, names, f"{prefix}p{i + 1}_")
            parts.append(f"max(0, {t})")
            params.update(ps)
        text = " + ".join(parts) or "0"
    else:
        raise EquationError(f"an SD Lab rate of form {form!r} has no rendering")
    effects = _effects(rate.get("effects") or [], names)
    if effects:
        text = " * ".join([f"({text})" if " " in text else text, *effects])
    return text, params


def _sdlab_expr(expr: str, names: Names) -> str:
    """An SD Lab expression in the language: ``^`` is ``**``; ``and``, ``or`` and ``not`` (Python's
    words) are ``and_``, ``or_`` and ``not_``; SD Lab's ``log(x)`` (to base 10) is ``log10(x)``
    and ``log(x, b)`` is ``ln(x) / ln(b)``; names that are not plain are qualified."""
    import re

    text = re.sub(r"\b(and|or|not)\s*\(", r"\1_(", expr.replace("^", "**"))
    try:
        tree = ast.parse(text, mode="eval")
    except SyntaxError as e:
        raise EquationError(f"SD Lab's expression {expr!r} does not parse: {e.msg}") from None

    class Qualify(ast.NodeTransformer):
        def visit_Call(self, node):
            self.generic_visit(node)
            if isinstance(node.func, ast.Name) and node.func.id == "log":
                if len(node.args) == 1:
                    node.func.id = "log10"
                elif len(node.args) == 2:
                    a, b = node.args
                    return ast.BinOp(ast.Call(ast.Name("ln", ast.Load()), [a], []), ast.Div(), ast.Call(ast.Name("ln", ast.Load()), [b], []))
            return node

        def visit_Name(self, node):
            if node.id in names.stocks or node.id in names.inputs:
                written = names.bare(node.id)
                if written != node.id:
                    return ast.parse(written, mode="eval").body
            return node
    return ast.unparse(Qualify().visit(tree))


def text_of(eq: Equation | None, src: str | None, names: Names) -> tuple[str, dict[str, float]]:
    """A flow's equation (``Flow.current()``) as the language writes it, with its parameters."""
    if eq is None:
        return OBSERVED, {}
    if (eq.spec or {}).get("language") == LANGUAGE:
        return eq.spec["text"], dict(eq.params)
    if eq.spec and eq.spec.get("form"):
        return _spec(eq.spec, names)
    p = eq.params
    x = eq.inputs[0] if eq.inputs else src
    if eq.form == "constant":
        return "c", {"c": float(p.get("c", 0.0))}
    if eq.form == "proportional" and x:
        return f"k * {names.ref(x)}", {"k": float(p.get("k", 0.0))}
    if eq.form == "linear" and x:
        return f"c + k * {names.ref(x)}", {"c": float(p.get("c", 0.0)), "k": float(p.get("k", 0.0))}
    raise EquationError(f"an equation of form {eq.form!r} has no rendering")


def flow_text(f: Flow, names: Names) -> tuple[str, dict[str, float]]:
    return text_of(f.current(), f.src, names)


def _classic(parsed: Parsed) -> tuple[str, list[str]] | None:
    """The classic form a text is written in exactly (``c``, ``k * X``, ``c + k * X``), or None."""
    body, p = parsed.tree.body, set(parsed.params)

    def ref(node) -> str | None:
        if isinstance(node, ast.Name) and node.id not in p:
            return node.id if node.id in parsed.stocks else f"input:{node.id}"
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in ("stock", "input"):
            v = node.args[0].value
            return v if node.func.id == "stock" else f"input:{v}"
        return None

    def term(node) -> str | None:
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mult) and isinstance(node.left, ast.Name) and node.left.id == "k":
            return ref(node.right)
        return None
    if isinstance(body, ast.Name) and body.id == "c" and p == {"c"}:
        return "constant", []
    if p == {"k"} and (x := term(body)):
        return "proportional", [x]
    if (p == {"c", "k"} and isinstance(body, ast.BinOp) and isinstance(body.op, ast.Add) and isinstance(body.left, ast.Name)
            and body.left.id == "c" and (x := term(body.right))):
        return "linear", [x]
    return None


def equation_of(parsed: Parsed, method: str, window=None) -> Equation:
    """The equation a checked text stands for: declared, with ``method`` saying who wrote it."""
    classic = _classic(parsed)
    if classic and parsed.text == _canonical(classic[0], parsed):
        form, inputs = classic
        return Equation(form, dict(parsed.params), "declared", method, window, None, {}, inputs)
    return Equation("expr", dict(parsed.params), "declared", method, window, None, {}, parsed.reads(),
                    {"language": LANGUAGE, "text": parsed.text})


def _canonical(form: str, parsed: Parsed) -> str:
    """The text the classic form renders as, to keep a text written differently as written."""
    names = Names(parsed.stocks, parsed.inputs)
    x = parsed.reads()[0] if parsed.reads() else None
    return {"constant": "c", "proportional": f"k * {names.ref(x) if x else ''}",
            "linear": f"c + k * {names.ref(x) if x else ''}"}[form]

