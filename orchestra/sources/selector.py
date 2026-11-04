"""A source-fed series as the store spells it: the selector the owner would type in the store
itself, and the query a view of it starts from (the Core page's External stores box).

Orchestra names a remote series ``<prefix>:<name>``, lower-cased, with ``:`` turned into ``_``,
and its labels in their canonical spelling: none of which can be pasted back into the store. The
selector here is taken from the definition the series was read by (its ``inner`` expression, or
its query when it is a plain selector), never rebuilt from Orchestra's name: the store's own
metric name, the matchers the definition reads it with (the source's ``match`` among them), and
one ``label="value"`` per label the series is grouped by, spelled as the store spells it.

The view's query follows the kind inference gave the series: a counter's increments open as
``rate(<selector>[<window>])`` (a counter only yields numbers through ``rate()`` in most stores'
own interfaces), ``<window>`` the discovery's step, at least the definition's lookback so a
window always holds two samples; anything else as the bare selector. A definition whose query is
not a plain selector (a hand-written ``[[series]]`` query, a script's) has no selector of its own:
its query, as written, is what is shown and prefilled."""

from __future__ import annotations

import re

from .family import esc, lookback
from .scope import scoped

PLAIN = re.compile(r"^\s*(?:[a-zA-Z_:][a-zA-Z0-9_:]*\s*)?(?:\{.*\})?\s*$", re.DOTALL)
HELD = re.compile(r"^\s*last_over_time\(\s*(.+?)\s*\[[0-9.]+[smhdw]\]\s*\)\s*$", re.DOTALL)
NATIVE = re.compile(r"^\s*histogram_count\(\s*(.+)\s*\)\s*$", re.DOTALL)
RATE_VIEWS = {"increments", "declared", "script"}       # a counter read as its increments: never a count of reporters


def plain(expr: str) -> bool:
    """Whether ``expr`` is a bare vector selector: a metric name, matchers in braces, or both."""
    return bool(expr and expr.strip() and PLAIN.match(expr))


def base(d) -> str | None:
    """The definition's selector in the store's own spelling: its ``inner`` expression without the
    lookback (``last_over_time(x[R])``) or a native histogram's ``histogram_count``, or its query
    when that is a plain selector; None for a query that is not one."""
    for expr in (getattr(d, "inner", "") or "", d.query or ""):
        e = expr.strip()
        for pat in (HELD, NATIVE):
            if m := pat.match(e):
                e = m[1].strip()
        if plain(e):
            return e
    return None


def _unprefixed(label: str, value: str, prefix: str) -> str:
    """A ``machine`` or ``source`` label's value as the store holds it (``fetch._finish`` prefixes it)."""
    return value.removeprefix(f"{prefix}.") if label in ("machine", "source") else value


def of_series(d, labels: dict, prefix: str) -> str | None:
    """One result series' selector in the store: the definition's own, narrowed to the values of the
    labels the series is grouped by (as the store spells them)."""
    sel = base(d)
    if sel is None:
        return None
    pins = []
    for canon, real in zip(d.group_by or [], d.by_real or [], strict=False):
        if canon in labels:
            pins.append(f'{real}="{esc(_unprefixed(canon, str(labels[canon]), prefix))}"')
    return scoped(sel, pins) if pins else sel


def view_query(d, selector: str | None, step: float) -> str:
    """The query the Core page's box opens with: a counter's ``rate`` over the step, else the
    selector; the definition's query as written when it has no selector."""
    if selector is None:
        return d.query or ""
    if d.kind == "counter" and d.view in RATE_VIEWS:
        w = max(round(step or 60), lookback(getattr(d, "resolution_s", None)))
        return f"rate({selector}[{w}s])"
    return selector

