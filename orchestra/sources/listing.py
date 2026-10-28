"""What a store holds, listed cheaply and under its per-query series limit.

1. **Names** from ``label/__name__/values`` with the source's ``match[]`` and the window: one
   request, whatever the tenant's size (no ``match[]`` for the match-everything default, and at
   most ``max_names`` + 1 asked). **A big store is not listed whole:** when ``match`` selects more
   than ``max_names`` names, the listing is refused (``TooManyNames``) with what to narrow, before
   a single series is listed. A store without that endpoint is listed as before, by ``series``
   with ``match``, cut at ``LIMIT``.
2. **Series** by batches of names, ``{__name__=~"a|b|…"}`` within each of ``match``, but for a
   histogram's ``_bucket`` beside its ``_count``: buckets are never read, and are most of a
   tenant's series, so only their name is kept (with no label sets). A batch the
   store refuses for its size (a 422) is split in two and each half asked, down to one name; a
   name too big alone is not listed and is named, with the store's message, in ``too_big``
   (inference leaves it out and says to narrow ``match`` or declare it by hand). **The cap is
   applied while listing:** once ``LIMIT`` label sets are in, no further batch is asked.
3. **An HA pair's name too big across its replicas** (a label ``REPLICA_LABELS`` names, with two
   or more values among what was listed) is asked again at one replica (``{__name__="x",
   prometheus_replica="a"}``): listed so, it is in ``pinned`` and read at that replica only; the
   replicas repeat each other, and one is under the limit when both are not.
4. **What was too big is remembered** (``known``: the last rounds' ``too_big`` and ``pinned``,
   for ``REMEMBER`` seconds): a name too big is not asked again, a pinned one is listed at its
   replica at once, so a round does not pay the same refusals every hour.

Batches go out ``concurrency`` at a time."""

from __future__ import annotations

import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from . import Labels, Source, SourceError
from .family import esc
from .transport import TooBig

UNSUPPORTED = re.compile(r"HTTP (400|404|405|501)\b")
BATCH = 24                   # names a listing request starts with
LIMIT = 20000                # label sets read, at most, in all
MAX_NAMES = 2000             # names a match may select for the listing to go on (the source's max_names)
REPLICA_LABELS = ("prometheus_replica", "replica", "__replica__")   # labels that name one replica of an HA pair
REMEMBER = 86400.0           # how long a name too big (or listed at one replica) is remembered
EVERYTHING = re.compile(r"""^\{\s*__name__\s*(=~\s*["']\.[+*]["']|!=\s*["']["'])\s*\}$""")


class TooManyNames(SourceError):
    """``match`` selects more metric names than a listing is made of (the store is large)."""


@dataclass
class Listing:
    names: dict[str, list[Labels]] = field(default_factory=dict)   # metric -> its label sets, without __name__
    too_big: dict[str, str] = field(default_factory=dict)          # metric -> why it was not listed
    failed: dict[str, str] = field(default_factory=dict)           # metric -> why its listing failed (not too big)
    pinned: dict[str, dict[str, str]] = field(default_factory=dict)  # metric -> {replica label: value} it was listed at
    notes: list[str] = field(default_factory=list)
    requests: int = 0
    cut: bool = False            # the cap stopped the listing before every name was asked


def everything(match: list[str]) -> bool:
    """Whether ``match`` selects every series (the default)."""
    return all(EVERYTHING.match(m.strip()) for m in match)


def with_names(match: str, names: list[str]) -> str:
    """``match`` narrowed to ``names``: a matcher on ``__name__`` added inside its braces (a second
    one is ANDed with any it has)."""
    rx = "|".join(re.escape(n) for n in names)
    s = match.strip()
    if not s.startswith("{"):                # it names its metric already
        return s
    inner = s[1:].strip()
    return '{__name__=~"' + rx + '"' + ("}" if inner == "}" else "," + inner)


def _names(source: Source, match: list[str], start: float, end: float, until: float | None, limit: int = 0) -> list[str] | None:
    fn = getattr(source, "names", None)
    if fn is None:
        return None
    try:
        return sorted(set(fn(match, start, end, limit) if limit else fn(match, start, end)))
    except TooBig:
        raise
    except SourceError as e:
        if UNSUPPORTED.search(str(e)):
            return None                      # no such endpoint: the listing by series below
        raise


class _Cap:
    """The label sets listed so far, against the cap: a batch is not asked once it is reached."""

    def __init__(self, limit: int):
        self.limit, self.n = limit, 0
        self.lock = threading.Lock()

    def full(self) -> bool:
        with self.lock:
            return self.n >= self.limit

    def add(self, n: int) -> None:
        with self.lock:
            self.n += n


def _split(source: Source, match: str, names: list[str], start: float, end: float, out: Listing, cap: _Cap | None = None) -> None:
    if cap is not None and cap.full():
        out.cut = True
        return
    try:
        sets = source.series([with_names(match, names)], start, end, narrow=False)
    except TooBig as e:
        if len(names) == 1:
            out.too_big[names[0]] = str(e)
            return
        half = len(names) // 2
        _split(source, match, names[:half], start, end, out, cap)
        _split(source, match, names[half:], start, end, out, cap)
        return
    except SourceError as e:
        for n in names:
            out.failed[n] = str(e)
        return
    if cap is not None:
        cap.add(len(sets))
    for lab in sets:
        n = lab.get("__name__")
        if n:
            out.names.setdefault(n, []).append({k: v for k, v in lab.items() if k != "__name__"})


def _replicas(out: Listing) -> dict[str, list[str]]:
    """The replica labels among what was listed, with their values, when there are two or more."""
    vals: dict[str, set[str]] = {}
    for sets in out.names.values():
        for lab in sets:
            for r in REPLICA_LABELS:
                if r in lab:
                    vals.setdefault(r, set()).add(lab[r])
    return {r: sorted(v) for r, v in vals.items() if len(v) >= 2}


def _at_replica(source: Source, name: str, pin: dict[str, str], start: float, end: float) -> list[Labels] | None:
    """``name``'s label sets at one replica; None when it is refused there too or has none there."""
    sel = '{__name__="' + esc(name) + '",' + ",".join(f'{k}="{esc(v)}"' for k, v in pin.items()) + "}"
    try:
        sets = source.series([sel], start, end, narrow=False)
    except SourceError:
        return None
    return [{k: v for k, v in lab.items() if k != "__name__"} for lab in sets] or None


def _too_many(n: int, match: list[str], limit: int, at_least: bool) -> TooManyNames:
    more = f"at least {n}" if at_least else str(n)
    if everything(match):
        return TooManyNames(f"the store holds {more} metric names, more than the {limit} a listing is made of: its whole "
                            "schema is not listed. Set match on the [[sources]] entry to the families the model is about, e.g. "
                            "match = ['{__name__=~\"queue_.*|orders_.*\"}'], and add a label matcher (env, cluster) where "
                            "the store is shared; or set infer = false and declare the series in [[series]]")
    return TooManyNames(f"match selects {more} metric names, more than the {limit} a listing is made of. Narrow match on the "
                        "[[sources]] entry to the families the model is about (a regex of names, with label matchers), or "
                        "set infer = false and declare the series in [[series]]")


def listing(source: Source, match: list[str], start: float, end: float, *, until: float | None = None,
            concurrency: int = 4, max_names: int = MAX_NAMES, limit: int = LIMIT, known: dict | None = None) -> Listing:
    """``known``: what the last rounds found too big or listed at one replica
    (``{"too_big": {name: {"why", "at"}}, "pinned": {name: {"pin", "at"}}}``)."""
    out = Listing()
    names = _names(source, match, start, end, until, max_names + 1)
    if names is not None and len(names) > max_names:
        raise _too_many(len(names), match, max_names, len(names) == max_names + 1)
    if names is None:
        sets = source.series(match, start, end, limit)
        if len(sets) >= limit:
            out.notes.append(f"the listing was cut at {limit} series; narrow match to infer from all")
        out.notes += [f"refused by the store even when narrowed, so left out: {x}" for x in getattr(source, "left_out", [])]
        for lab in sets:
            n = lab.get("__name__")
            if n:
                out.names.setdefault(n, []).append({k: v for k, v in lab.items() if k != "__name__"})
        return out
    unread = {n for n in names if n.endswith("_bucket") and f"{n.removesuffix('_bucket')}_count" in names}
    out.names.update({n: [] for n in unread})
    names = [n for n in names if n not in unread]
    now = time.time()
    known = known or {}
    old_big = {n: k for n, k in (known.get("too_big") or {}).items() if n in names and now - float(k.get("at", 0)) < REMEMBER}
    old_pin = {n: k for n, k in (known.get("pinned") or {}).items() if n in names and now - float(k.get("at", 0)) < REMEMBER}
    for n, k in old_big.items():
        out.too_big[n] = f"{k.get('why')} (found at {time.strftime('%Y-%m-%d %H:%M', time.localtime(float(k['at'])))}; not asked again for a day)"
    names = [n for n in names if n not in old_big and n not in old_pin]
    cap = _Cap(limit)
    jobs = []
    for m in match:
        bare = m.strip().partition("{")[0].strip()
        if bare:                             # a selector naming its metric: listed as it is
            jobs.append((m, [bare]))
            continue
        jobs += [(m, names[i:i + BATCH]) for i in range(0, len(names), BATCH)]
    with ThreadPoolExecutor(max(1, concurrency)) as pool:
        list(pool.map(lambda j: _split(source, j[0], j[1], start, end, out, cap), jobs))
    for n, k in old_pin.items():             # listed at the replica an earlier round found it fits at
        if (sets := _at_replica(source, n, dict(k["pin"]), start, end)) is not None:
            out.names[n], out.pinned[n] = sets, dict(k["pin"])
        else:
            out.too_big[n] = "over the store's per-query series limit, even at one replica"
    fresh = [n for n in out.too_big if n not in old_big]
    reps = _replicas(out)
    for n in fresh:                          # an HA pair's: one replica may fit where both do not
        for r, vals in reps.items():
            if (sets := _at_replica(source, n, {r: vals[0]}, start, end)) is not None:
                out.names[n], out.pinned[n] = sets, {r: vals[0]}
                del out.too_big[n]
                break
    if out.pinned:
        out.notes.append(f"{len(out.pinned)} metric(s) over the store's per-query limit across an HA pair's replicas are listed "
                         f"and read at one replica: {', '.join(f'{n} ({next(iter(p))}={next(iter(p.values()))})' for n, p in sorted(out.pinned.items())[:10])}")
    for n in out.names:
        out.failed.pop(n, None)
    total = sum(len(v) for v in out.names.values())
    if out.cut or total > limit:
        out.notes.append(f"the listing stopped at {limit} series ({total} listed): the names after it are not inferred from: narrow match")
    if out.too_big:
        out.notes.append(f"{len(out.too_big)} metric(s) have more series than the store answers in one query, so are not read: "
                         f"{', '.join(sorted(out.too_big)[:10])}; narrow match, or declare them with label matchers in [[series]]")
    if out.failed:
        out.notes.append(f"{len(out.failed)} metric(s) could not be listed: {next(iter(out.failed.values()))}")
    return out
