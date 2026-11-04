"""A person's queries of a source, from the Core page: bounded so that no question asked there can
take the store down (the owner, 2026-11-03: "some queries like ``{}`` might take down the
prometheus servers, gotta use other ways to get labels").

- **Within the match, always.** Every selector of a query, and every ``match[]`` of a labels
  request, has the source's ``match`` conjoined (``conjoined``): its matchers are added to the
  selector even on a label the selector constrains itself (``{namespace="other"}`` under
  ``namespace="shop"`` asks for both, and gets nothing), unlike ``scope.scoped``, which keeps a
  definition's own. A match of several selectors that differ beyond what they share cannot be
  conjoined to one selector, and is refused here with that reason.
- **A selector of its own** (``guard``): a selector needs a metric name or at least one label
  matcher of its own, not one the match has already and not one that matches everything
  (``=~".+"``, ``=~".*"``, ``=""``, ``!=""``): ``{}``, ``{__name__=~".+"}`` and, under
  ``{namespace="shop"}``, ``{namespace="shop"}`` are refused.
- **A bounded window** (``window``): an hour by default, a day at most; an instant query is
  evaluated at now, and no range or subquery in a query reaches back more than a day. **A bounded result** (``limit``): 50 series by default, at most the source's
  ``max_series``; each selector is first counted with ``/api/v1/series`` over the window with
  ``limit`` + 1 (a bounded listing that stops early), and a query whose selector selects more is
  refused before it is run.
- **Labels the cheap way** (``labels``, ``values``): ``/api/v1/labels`` and
  ``/api/v1/label/<name>/values`` with ``match[]`` the conjoined selector, ``start``/``end`` the
  window and ``limit``; with no selector, ``match[]`` is the source's match, or none at all when the
  match selects everything (an index read). Never ``/api/v1/series`` unbounded.

The reads themselves, and their log, are ``asking.py``; what the page shows of each source,
``stores.py``."""

from __future__ import annotations

import math
import re
import time

from . import SourceError
from .scope import LABEL, matchers, walk

LIMIT = 50                    # series a query returns, by default
WINDOW_S = 3600.0             # a range query's window, by default
MAX_WINDOW_S = 86400.0        # ... at most
EMPTY = {"", ".*", ".+", "^.*$", "^.+$", "(.*)", "(.+)"}   # a matcher with one of these values selects (nearly) everything
EVERYTHING = {'{__name__=~".+"}', "{__name__=~'.+'}", '{__name__=~".*"}', '{__name__!=""}'}


class Refused(SourceError):
    """A query the page will not send, with why."""


def _unquote(v: str) -> str:
    v = v.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'`":
        body = v[1:-1]
        return body if v[0] == "`" else re.sub(r"\\(.)", r"\1", body)
    return v


def _parsed(name: str | None, block: str | None) -> list[tuple[str, str, str]]:
    """A selector's matchers as (label, op, value), its metric name as ``__name__ = name``."""
    out = [("__name__", "=", name)] if name else []
    for label, text in matchers(block or ""):
        if label == "__name__" and not LABEL.match(text):        # a quoted metric name inside the braces
            out.append(("__name__", "=", _unquote(text)))
            continue
        m = LABEL.match(text)
        out.append((m[1], m[2], _unquote(text[m.end():])))
    return out


def matcher_text(label: str, op: str, value: str) -> str:
    return f'{label}{op}"{value.replace(chr(92), chr(92) * 2).replace(chr(34), chr(92) + chr(34))}"'


def match_matchers(match: list[str]) -> list[tuple[str, str, str]]:
    """The matchers every query of the source is conjoined with: its match's, when it is one selector
    (or several alike); [] when it selects everything. ``Refused`` when its selectors differ."""
    if not match or all(m.strip() in EVERYTHING for m in match):
        return []
    sets = []
    for m in match:
        found: list = []
        try:
            walk(m, lambda name, block, head, found=found: found.append(_parsed(name, block)) or "")
        except ValueError as e:
            raise Refused(f"the source's match {m!r} is not a selector this reads: {e}") from None
        if len(found) != 1:
            raise Refused(f"the source's match {m!r} is not one selector")
        sets.append(found[0])
    if any(sorted(s) != sorted(sets[0]) for s in sets[1:]):
        raise Refused(f"the source's match has {len(match)} selectors that differ ({', '.join(match)}): a query cannot be "
                      "kept within it as one selector, so this page does not query it; make the match one selector")
    return [x for x in sets[0] if not (x[0] == "__name__" and x[2] in EMPTY)]


def _own(sel: list[tuple[str, str, str]], scope: list[tuple[str, str, str]]) -> list[tuple[str, str, str]]:
    """A selector's matchers of its own: not the match's, and not one that matches everything."""
    return [x for x in sel if x not in scope and x[2] not in EMPTY]


def conjoined(expr: str, match: list[str]) -> str:
    """``expr`` with the source's match conjoined into every selector, after ``guard``'s check of
    each: ``Refused`` with the reason for a selector with no matcher of its own."""
    scope = match_matchers(match)
    named = any(x[0] == "__name__" for x in scope)

    def one(name, block, head):
        written = (head + "{" + block + "}") if block is not None else head
        try:
            sel = _parsed(name, block)
        except ValueError as e:
            raise Refused(f"{written.strip()}: not a selector this reads ({e})") from None
        if not _own(sel, scope):
            within = f" beyond the source's match ({', '.join(match)})" if scope else ""
            raise Refused(f"{written.strip() or '{}'}: a selector needs a metric name or at least one label matcher of its own{within}; "
                          '__name__=~".+" counts as none, so a query cannot select every series of the store')
        mine = [matcher_text(*x) for x in sel if not (name and x == ("__name__", "=", name))]
        extra = [matcher_text(*x) for x in scope]
        if name and not named:
            return name + ("{" + ",".join(mine + extra) + "}" if mine or extra else "")
        return "{" + ",".join(([matcher_text("__name__", "=", name)] if name else []) + mine + extra) + "}"
    if not expr.strip():
        raise Refused("an empty query")
    _ranges(expr)
    return walk(expr, one)


UNIT_S = {"ms": 0.001, "s": 1, "m": 60, "h": 3600, "d": 86400, "w": 7 * 86400, "y": 365 * 86400}
DURATION = re.compile(r"(\d+(?:\.\d+)?)(ms|s|m|h|d|w|y)")
STRINGS = re.compile(r"\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'|`[^`]*`")


def _ranges(expr: str) -> None:
    """``Refused`` for a range or a subquery (``x[30d]``, ``x[7d:1h]``) longer than a day: it would
    read more than the page's window allows."""
    for block in re.findall(r"\[([^\]]*)\]", STRINGS.sub('""', expr)):
        span = block.split(":")[0]
        secs = sum(float(n) * UNIT_S[u] for n, u in DURATION.findall(span))
        if secs > MAX_WINDOW_S:
            raise Refused(f"[{block}] reads {secs / 3600:g} h: a range or subquery reads at most {MAX_WINDOW_S / 3600:g} h here")


def guard(expr: str, match: list[str]) -> str | None:
    """Why ``expr`` is refused under ``match``, or None when it may be sent."""
    try:
        conjoined(expr, match)
    except Refused as e:
        return str(e)
    return None


def selectors(expr: str) -> list[str]:
    """The vector selectors of ``expr``, as written."""
    out: list[str] = []

    def one(name, block, head):
        out.append((head + "{" + block + "}") if block is not None else head)
        return out[-1]
    walk(expr, one)
    return out


def window(minutes: float | None, now: float | None = None) -> tuple[float, float]:
    """[start, end] of a read: the last ``minutes`` (an hour by default), at most a day."""
    span = WINDOW_S if minutes is None or not math.isfinite(minutes) or minutes <= 0 else min(MAX_WINDOW_S, minutes * 60)
    end = time.time() if now is None else now
    return end - span, end


def limit(asked: int | None, spec) -> int:
    """The series a read returns: ``LIMIT`` by default, at least 1, at most the source's ``max_series``."""
    cap = max(1, int(getattr(spec, "max_series", LIMIT) or LIMIT))
    n = LIMIT if asked is None or asked <= 0 else int(asked)
    return max(1, min(n, cap))


def step(span_s: float) -> float:
    """About 240 points across a range, on a round step."""
    nice = [15, 30, 60, 120, 300, 600, 900, 1800, 3600]
    return next((x for x in nice if x >= span_s / 240), nice[-1])


def resets(now: float | None = None) -> str:
    """When the daily cap resets: the next 00:00 UTC, and how long from now."""
    now = time.time() if now is None else now
    left = 86400 - now % 86400
    return f"it resets at 00:00 UTC, in {int(left // 3600)} h {int(left % 3600 // 60)} min"
