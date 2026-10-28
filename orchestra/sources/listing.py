"""What a store holds, listed cheaply and under its per-query series limit.

1. **Names** from ``label/__name__/values`` with the source's ``match[]`` and the window: one
   request, whatever the tenant's size. A store without that endpoint is listed as before, by
   ``series`` with ``match``.
2. **Series** by batches of names, ``{__name__=~"a|b|…"}`` within each of ``match``, but for a
   histogram's ``_bucket`` beside its ``_count``: buckets are never read, and are most of a
   tenant's series, so only their name is kept (with no label sets). A batch the
   store refuses for its size (a 422) is split in two and each half asked, down to one name; a
   name too big alone is not listed and is named, with the store's message, in ``too_big``
   (inference leaves it out and says to narrow ``match`` or declare it by hand).

Batches go out ``concurrency`` at a time."""

from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from . import Labels, Source, SourceError
from .transport import TooBig

UNSUPPORTED = re.compile(r"HTTP (400|404|405|501)\b")
BATCH = 24                   # names a listing request starts with
LIMIT = 20000                # label sets read, at most, in all


@dataclass
class Listing:
    names: dict[str, list[Labels]] = field(default_factory=dict)   # metric -> its label sets, without __name__
    too_big: dict[str, str] = field(default_factory=dict)          # metric -> why it was not listed
    failed: dict[str, str] = field(default_factory=dict)           # metric -> why its listing failed (not too big)
    notes: list[str] = field(default_factory=list)
    requests: int = 0


def with_names(match: str, names: list[str]) -> str:
    """``match`` narrowed to ``names``: a matcher on ``__name__`` added inside its braces (a second
    one is ANDed with any it has)."""
    rx = "|".join(re.escape(n) for n in names)
    s = match.strip()
    if not s.startswith("{"):                # it names its metric already
        return s
    inner = s[1:].strip()
    return '{__name__=~"' + rx + '"' + ("}" if inner == "}" else "," + inner)


def _names(source: Source, match: list[str], start: float, end: float, until: float | None) -> list[str] | None:
    fn = getattr(source, "names", None)
    if fn is None:
        return None
    try:
        return sorted(set(fn(match, start, end)))
    except TooBig:
        raise
    except SourceError as e:
        if UNSUPPORTED.search(str(e)):
            return None                      # no such endpoint: the listing by series below
        raise


def _split(source: Source, match: str, names: list[str], start: float, end: float, out: Listing) -> None:
    try:
        sets = source.series([with_names(match, names)], start, end, narrow=False)
    except TooBig as e:
        if len(names) == 1:
            out.too_big[names[0]] = str(e)
            return
        half = len(names) // 2
        _split(source, match, names[:half], start, end, out)
        _split(source, match, names[half:], start, end, out)
        return
    except SourceError as e:
        for n in names:
            out.failed[n] = str(e)
        return
    for lab in sets:
        n = lab.get("__name__")
        if n:
            out.names.setdefault(n, []).append({k: v for k, v in lab.items() if k != "__name__"})


def listing(source: Source, match: list[str], start: float, end: float, *, until: float | None = None,
            concurrency: int = 4) -> Listing:
    out = Listing()
    names = _names(source, match, start, end, until)
    if names is None:
        sets = source.series(match, start, end, LIMIT)
        if len(sets) >= LIMIT:
            out.notes.append(f"the listing was cut at {LIMIT} series; narrow match to infer from all")
        out.notes += [f"refused by the store even when narrowed, so left out: {x}" for x in getattr(source, "left_out", [])]
        for lab in sets:
            n = lab.get("__name__")
            if n:
                out.names.setdefault(n, []).append({k: v for k, v in lab.items() if k != "__name__"})
        return out
    unread = {n for n in names if n.endswith("_bucket") and f"{n.removesuffix('_bucket')}_count" in names}
    out.names.update({n: [] for n in unread})
    names = [n for n in names if n not in unread]
    jobs = []
    for m in match:
        bare = m.strip().partition("{")[0].strip()
        if bare:                             # a selector naming its metric: listed as it is
            jobs.append((m, [bare]))
            continue
        jobs += [(m, names[i:i + BATCH]) for i in range(0, len(names), BATCH)]
    with ThreadPoolExecutor(max(1, concurrency)) as pool:
        list(pool.map(lambda j: _split(source, j[0], j[1], start, end, out), jobs))
    for n in out.names:
        out.failed.pop(n, None)
    total = sum(len(v) for v in out.names.values())
    if total > LIMIT:
        out.notes.append(f"{total} series listed; only the first {LIMIT} by name are inferred from: narrow match")
        kept, n = {}, 0
        for k in sorted(out.names):
            if n + len(out.names[k]) > LIMIT:
                break
            kept[k], n = out.names[k], n + len(out.names[k])
        out.names = kept
    if out.too_big:
        out.notes.append(f"{len(out.too_big)} metric(s) have more series than the store answers in one query, so are not read: "
                         f"{', '.join(sorted(out.too_big)[:10])}; narrow match, or declare them with label matchers in [[series]]")
    if out.failed:
        out.notes.append(f"{len(out.failed)} metric(s) could not be listed: {next(iter(out.failed.values()))}")
    return out
