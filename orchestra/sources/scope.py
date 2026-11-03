"""A source's ``match``, carried by every query made of it: the store is read within what the
``[[sources]]`` entry selects, never beyond (bootstrap run 4: a shared Prometheus whose discovery
queries named no namespace, so ``sum by (status)`` summed another team's series into the project's).

``match`` is a list of selectors, any of which a series may match. Its **scope** (``scope_of``) is
the label matchers every one of them carries (``__name__`` aside): ``['{namespace="hackriff"}']``
scopes to ``namespace="hackriff"``; ``['{__name__=~"http_.*",env="prod"}', 'queue_depth{env="prod"}']``
to ``env="prod"``; the match-everything default, or entries with no label matcher in common, to
nothing (each entry's own label matchers would need a query of its own).

``scoped(expr, scope)`` adds the scope's matchers to every vector selector of a PromQL expression
(``x``, ``x{a="b"}``, ``{__name__=~"a|b"}``), but never one on a label the selector constrains
already: a query written with ``namespace=~"a|b"`` keeps its own. Function and aggregation names,
label lists (``by (…)``, ``on (…)``), strings, durations and numbers are left as they are. Inference
scopes each definition's queries (``infer.py``), so what is planned, read and shown as a series'
provenance carries the scope, and the transport scopes every request again (``prometheus.py``):
the listings, the schema's samples and a query as written included."""

from __future__ import annotations

import re

IDENT = re.compile(r"[a-zA-Z_:][a-zA-Z0-9_:]*")
LABEL = re.compile(r"\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*(=~|!~|!=|=)\s*")
AGGREGATIONS = {"sum", "avg", "count", "min", "max", "group", "stddev", "stdvar", "topk", "bottomk", "quantile",
                "count_values", "limitk", "limit_ratio"}
LISTS = {"by", "without", "on", "ignoring", "group_left", "group_right"}      # followed by a list of labels
WORDS = {"and", "or", "unless", "bool", "offset", "atan2", "inf", "nan"}


def _string(s: str, i: int) -> int:
    """The index just past the string literal starting at ``i``."""
    q, i = s[i], i + 1
    while i < len(s) and s[i] != q:
        i += 2 if s[i] == "\\" and q != "`" else 1
    return i + 1


def _close(s: str, i: int, opener: str, closer: str) -> int:
    """The index just past the bracket matching the one at ``i``, strings skipped."""
    depth = 0
    while i < len(s):
        c = s[i]
        if c in "\"'`":
            i = _string(s, i)
            continue
        if c == opener:
            depth += 1
        elif c == closer:
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return len(s)


def matchers(block: str) -> list[tuple[str, str]]:
    """The matchers inside a selector's braces (without them): (label, matcher as written); a bare
    string (a quoted metric name) as ``("__name__", text)``."""
    out, i = [], 0
    while i < len(block):
        while i < len(block) and block[i] in " \t\n,":
            i += 1
        if i >= len(block):
            break
        if block[i] in "\"'`":
            j = _string(block, i)
            out.append(("__name__", block[i:j]))
            i = j
            continue
        m = LABEL.match(block, i)
        if not m:
            raise ValueError(f"not a label matcher: {block[i:]!r}")
        j = m.end()
        if j < len(block) and block[j] in "\"'`":
            j = _string(block, j)
        out.append((m[1], f"{m[1]}{m[2]}{block[m.end():j]}"))
        i = j
    return out


def _entry(sel: str) -> list[str] | None:
    """One selector's label matchers (``__name__`` aside), as written; None when it is not one."""
    s = sel.strip()
    m = IDENT.match(s)
    rest = s[m.end():].strip() if m else s
    if not rest:
        return []
    if not rest.startswith("{") or _close(rest, 0, "{", "}") != len(rest):
        return None
    try:
        return [text for label, text in matchers(rest[1:-1]) if label != "__name__"]
    except ValueError:
        return None


def scope_of(match: list[str]) -> list[str]:
    """The label matchers every selector of ``match`` carries, in the first one's order."""
    sets = [_entry(m) for m in match or []]
    if not sets or any(x is None for x in sets):
        return []
    common = [x for x in sets[0] if all(x in other for other in sets[1:])]
    return list(dict.fromkeys(common))


def _label(matcher: str) -> str:
    m = LABEL.match(matcher)
    return m[1] if m else matcher


def _inject(block: str, scope: list[str]) -> str:
    """A selector's braces' content with the scope's matchers on labels it does not constrain."""
    try:
        have = {label for label, _ in matchers(block)}
    except ValueError:
        return block                       # not a selector this reads: left as it is
    add = [m for m in scope if _label(m) not in have]
    if not add:
        return block
    inner = block.strip().rstrip(",").strip()
    return ",".join([inner, *add]) if inner else ",".join(add)


def _next(s: str, i: int) -> int:
    while i < len(s) and s[i].isspace():
        i += 1
    return i


def scoped(expr: str, scope: list[str]) -> str:
    """``expr`` with the scope's matchers in every vector selector (the module's docstring)."""
    if not scope or not expr:
        return expr
    out, i, n = [], 0, len(expr)
    while i < n:
        c = expr[i]
        if c in "\"'`":
            j = _string(expr, i)
            out.append(expr[i:j])
            i = j
        elif c == "[":
            j = _close(expr, i, "[", "]")
            out.append(expr[i:j])
            i = j
        elif c == "{":
            j = _close(expr, i, "{", "}")
            out.append("{" + _inject(expr[i + 1:j - 1], scope) + "}")
            i = j
        elif c.isdigit() or (c == "." and i + 1 < n and expr[i + 1].isdigit()):
            j = i
            while j < n and (expr[j].isalnum() or expr[j] in "._"):
                j += 1
            out.append(expr[i:j])
            i = j
        elif m := IDENT.match(expr, i):
            word, j = m[0], m.end()
            k = _next(expr, j)
            follows = expr[k] if k < n else ""
            if word.lower() in LISTS:
                out.append(word)
                if follows == "(":
                    e = _close(expr, k, "(", ")")
                    out.append(expr[j:e])
                    j = e
            elif follows == "(" or word.lower() in WORDS or (word in AGGREGATIONS and IDENT.match(expr, k)
                                                             and IDENT.match(expr, k)[0].lower() in LISTS):
                out.append(word)
            elif follows == "{":
                e = _close(expr, k, "{", "}")
                out.append(word + expr[j:k] + "{" + _inject(expr[k + 1:e - 1], scope) + "}")
                j = e
            else:
                out.append(word + "{" + ",".join(scope) + "}")
            i = j
        else:
            out.append(c)
            i += 1
    return "".join(out)
