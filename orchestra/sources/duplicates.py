"""The same measurement twice, found from the data and kept once.

1. **A label that duplicates** (``duplicated``): a family whose series under one value of a
   label the collection adds (``schema.COLLECTION_LABELS``: a job, a replica) are the series under
   another, value for value. Two scrape jobs of one exporter
   (``job="node-exporter"`` and ``job="integrations/node_exporter"``), two replicas of one
   Prometheus: summing over that label counts everything twice. The label's values are compared
   as sets of series, whatever their other labels (two jobs label their targets differently): each
   value's series, sorted, must match the other's one for one, within ``TOLERANCE`` at almost every
   point. Equal constants prove nothing (two deployments of 2 pods each), so it takes either a
   series that moves or at least two different series that match.
2. **Counts of the same things** (``same_shape``): the pods of a service are counted from every
   family they report, under each family's own labels; two counts whose series match at almost
   every point count the same things, and one is enough. So do two counters of different
   families equal at every point (a histogram's ``_count`` and the counter of the same requests)."""

from __future__ import annotations

TOLERANCE = 0.005       # relative, per point
AGREE = 0.9             # of the points


def _close(a: float, b: float, tol: float) -> bool:
    return abs(a - b) <= tol * max(abs(a), abs(b), 1e-9)


def matches(a: list[float | None], b: list[float | None], tol: float = TOLERANCE, agree: float = AGREE) -> bool:
    """Whether two series on one grid agree at almost every point both have."""
    both = [(x, y) for x, y in zip(a, b, strict=False) if x is not None and y is not None]
    return len(both) >= 3 and sum(_close(x, y, tol) for x, y in both) >= agree * len(both)


def _key(v: list[float | None]) -> tuple:
    vals = [x for x in v if x is not None]
    return (vals[-1], vals[0]) if vals else (0.0, 0.0)


def moves(v: list[float | None]) -> bool:
    vals = [x for x in v if x is not None]
    return len(set(vals)) > 1


def duplicated(series: list[tuple[dict[str, str], list[float | None]]], label: str) -> tuple[str, list[str]] | None:
    """(the value kept, the values that only repeat it) when ``label`` duplicates the family's
    series (``series``: labels and values on one grid), else None. The value kept is the one with
    the most series, then the first by name; a value whose series differ is not a repeat."""
    by: dict[str, list[list[float | None]]] = {}
    for lab, v in series:
        if label in lab:
            by.setdefault(lab[label], []).append(v)
    if len(by) < 2:
        return None
    order = sorted(by, key=lambda x: (-len(by[x]), x))
    keep = order[0]
    a = sorted(by[keep], key=_key)
    evidence = any(moves(v) for v in a) or len({tuple(v) for v in a}) >= 2
    if not evidence:
        return None
    dropped = []
    for other in order[1:]:
        b = sorted(by[other], key=_key)
        if len(b) == len(a) and all(matches(x, y) for x, y in zip(a, b, strict=True)):
            dropped.append(other)
    return (keep, dropped) if dropped else None


def same_shape(a: list[list[float | None]], b: list[list[float | None]], *, exact: bool = False) -> bool:
    """Whether two results (each a list of series on one grid) hold the same series, one for one,
    and one of them moves: counts agree to the pod (an absolute tolerance of a half) at almost
    every point; with ``exact``, counters agree at every point (two counters of the same events
    are equal; started and handled differ by what is in flight, now and then, and stay two)."""
    if not a or len(a) != len(b) or not any(moves(v) for v in a):
        return False
    a, b = sorted(a, key=_key), sorted(b, key=_key)
    for x, y in zip(a, b, strict=True):
        both = [(p, q) for p, q in zip(x, y, strict=False) if p is not None and q is not None]
        ok = [_close(p, q, 1e-9) if exact else abs(p - q) <= 0.5 for p, q in both]
        if len(both) < 3 or sum(ok) < (len(both) if exact else AGREE * len(both)):
            return False
    return True
