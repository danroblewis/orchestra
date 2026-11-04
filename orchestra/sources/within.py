"""Whether one selector lies within another: a source's ``match`` within its ``explore``
(``spec.py``), so the explorer's scope always holds what the model reads.

Judged by the matchers as written, conservatively: ``inner`` lies within ``outer`` when every
matcher of ``outer`` is implied by one of ``inner``'s on the same label: the same matcher; an
equality whose value ``outer``'s regex matches whole (``=~``) or whose value differs from what
``outer`` excludes (``!=``, ``!~``). A matcher of ``outer`` that selects (nearly) everything
(``__name__=~".+"``) asks nothing. Anything else (two regexes, a regex inside an exclusion) is not
proved, and so not within: the owner writes ``explore`` wider or ``match`` plainer."""

from __future__ import annotations

import re

from .console import EMPTY, _parsed
from .scope import walk


def parsed(sel: str) -> list[tuple[str, str, str]] | None:
    """One selector's matchers as (label, op, value), its metric name as ``__name__ = name``; None
    when it is not one selector this reads."""
    found: list = []
    try:
        walk(sel, lambda name, block, head: found.append(_parsed(name, block)) or "")
    except ValueError:
        return None
    return found[0] if len(found) == 1 else None


def _full(rx: str, v: str) -> bool:
    try:
        return re.fullmatch(rx, v) is not None
    except re.error:
        return False


def _implies(m: tuple[str, str, str], o: tuple[str, str, str]) -> bool:
    """Whether the series matcher ``m`` admits are all admitted by ``o`` (the same label)."""
    if m == o:
        return True
    _, mop, mv = m
    _, oop, ov = o
    if mop != "=":
        return False
    return {"=~": lambda: _full(ov, mv), "!=": lambda: mv != ov, "!~": lambda: not _full(ov, mv), "=": lambda: mv == ov}[oop]()


def within(inner: str, outer: str) -> bool:
    """Whether every series ``inner`` selects is one ``outer`` selects (the module's docstring)."""
    i, o = parsed(inner), parsed(outer)
    if i is None or o is None:
        return False
    for om in o:
        if om[1] == "=~" and om[2] in EMPTY:
            continue
        if not any(im[0] == om[0] and _implies(im, om) for im in i):
            return False
    return True


def outside(match: list[str], explore: list[str]) -> list[str]:
    """The selectors of ``match`` that lie within none of ``explore``'s."""
    return [m for m in match if not any(within(m, e) for e in explore)]
