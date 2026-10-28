"""Many reads in few requests, under the store's per-query limits.

- **Range queries** (``run``): each part is an instant-vector expression; parts are joined with
  ``or``, each tagged by ``label_replace(…, "orchestra_part", "<i>", "", "")`` so its results come
  back apart (``a or b`` keeps every series of ``a``, and those of ``b`` with labels ``a`` has
  not: tagged, none collide). A request holds parts touching at most ``limit`` series together
  (the source's ``series_per_query``, or under the limit the store named when it refused one),
  at most ``MAX_PARTS`` parts and ``MAX_CHARS`` characters. A request the store refuses for its
  size (``TooBig``) is split in two and each half asked; a single part still refused is reported
  as over the store's limit, never retried as it is.
- **Raw samples** (``select_many``): an instant ``selector[range]`` keeps each series' metric
  name, so the selectors of several metrics with no other matchers go as one
  ``{__name__=~"a|b|c"}``, up to ``RAW_SERIES`` series a request.

A part that fails is reported by its key with why; the others are used. Requests go out
``concurrency`` at a time."""

from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from . import Labels, PastDeadline, Points, Source, SourceError
from .transport import TooBig

PART_LABEL = "orchestra_part"
OVER_LIMIT = "over the store's per-query series limit"
MAX_PARTS = 40
MAX_CHARS = 16000
RAW_SERIES = 60                  # series per batched raw read
NAME = re.compile(r"^[a-zA-Z_:][a-zA-Z0-9_:]*$")


@dataclass
class Part:
    key: object                  # the caller's
    expr: str                    # an instant-vector expression
    series: int = 1              # the series it touches, as far as the listing says


def limit_of(source: Source) -> int:
    spec = getattr(source, "spec", None)
    own = int(getattr(spec, "series_per_query", 0) or 0) or 10**9
    named = getattr(source, "series_limit", None)
    return max(1, min(own, int(0.9 * named) if named else own))


def _tagged(i: int, expr: str) -> str:
    return f'label_replace({expr}, "{PART_LABEL}", "{i}", "", "")'


def pack(parts: list[Part], limit: int) -> list[list[Part]]:
    """Parts into requests: each under ``limit`` series, ``MAX_PARTS`` parts and ``MAX_CHARS``."""
    out: list[list[Part]] = []
    cur: list[Part] = []
    n = chars = 0
    for p in sorted(parts, key=lambda p: -p.series):
        size, length = max(1, p.series), len(p.expr) + 60
        if cur and (n + size > limit or len(cur) >= MAX_PARTS or chars + length > MAX_CHARS):
            out.append(cur)
            cur, n, chars = [], 0, 0
        cur.append(p)
        n, chars = n + size, chars + length
    if cur:
        out.append(cur)
    return out


def _one(source: Source, group: list[Part], start: float, end: float, step: float, until: float | None,
         got: dict, failed: dict) -> None:
    if len(group) == 1:
        q = group[0].expr
    else:
        q = " or ".join(_tagged(i, p.expr) for i, p in enumerate(group))
    try:
        rows = source.query_range(q, start, end, step, until=until, narrow=False)
    except TooBig as e:
        if len(group) == 1:
            failed[group[0].key] = f"{OVER_LIMIT}: {e}"
            return
        half = len(group) // 2
        _one(source, group[:half], start, end, step, until, got, failed)
        _one(source, group[half:], start, end, step, until, got, failed)
        return
    except SourceError as e:              # PastDeadline included: those parts are not read
        for p in group:
            failed[p.key] = str(e) if not isinstance(e, PastDeadline) else f"late: {e}"
        return
    for p in group:
        got.setdefault(p.key, [])
    for labels, pts in rows:
        if len(group) == 1:
            got[group[0].key].append((labels, pts))
            continue
        i = labels.pop(PART_LABEL, None)
        if i is not None and i.isdigit() and int(i) < len(group):
            got[group[int(i)].key].append((labels, pts))


def run(source: Source, parts: list[Part], start: float, end: float, step: float, until: float | None = None,
        concurrency: int = 4) -> tuple[dict[object, list[tuple[Labels, Points]]], dict[object, str]]:
    """Every part evaluated over [start, end] at ``step``: (results by key, why by key for the
    parts that could not be read)."""
    got: dict[object, list] = {}
    failed: dict[object, str] = {}
    groups = pack(parts, limit_of(source))
    with ThreadPoolExecutor(max(1, concurrency)) as pool:
        list(pool.map(lambda g: _one(source, g, start, end, step, until, got, failed), groups))
    return got, failed


def select_many(source: Source, selectors: list[tuple[str, int]], start: float, end: float, until: float | None = None,
                concurrency: int = 4) -> tuple[dict[str, list[tuple[Labels, Points]]], dict[str, str]]:
    """Raw samples of each selector (with its series count from the listing): a bare metric name
    goes with others as one ``{__name__=~"…"}`` read; the results by selector, and why for those
    that could not be read."""
    bare = [(s, n) for s, n in selectors if NAME.match(s)]
    other = [(s, n) for s, n in selectors if not NAME.match(s)]
    groups: list[list[str]] = []
    cur, total = [], 0
    for s, n in sorted(bare, key=lambda x: x[1]):
        if cur and total + max(1, n) > RAW_SERIES:
            groups.append(cur)
            cur, total = [], 0
        cur.append(s)
        total += max(1, n)
    if cur:
        groups.append(cur)
    jobs = [("names", g) for g in groups] + [("one", [s]) for s, _ in other]
    got: dict[str, list] = {}
    failed: dict[str, str] = {}

    def do(job):
        how, names = job
        sel = names[0] if how == "one" or len(names) == 1 else '{__name__=~"' + "|".join(re.escape(n) for n in names) + '"}'
        try:
            rows = source.select(sel, start, end, until=until)
        except SourceError as e:
            for n in names:
                failed[n] = str(e)
            return
        for n in names:
            got.setdefault(n, [])
        for labels, pts in rows:
            if how == "one":
                got[names[0]].append((labels, pts))
            elif labels.get("__name__") in got:
                got[labels["__name__"]].append((labels, pts))
    with ThreadPoolExecutor(max(1, concurrency)) as pool:
        list(pool.map(do, jobs))
    return got, failed
