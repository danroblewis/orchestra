"""One read at the finest grouping serves every coarser one, exactly.

A family's views differ only by grouping (the total, by service, by service and region) and by
aggregation. ``fn by (G) (inner)`` for every G of a family is ``fn by (∪G) (inner)`` read once
and aggregated again here: a sum of sums, a max of maxes, a min of mins and a sum of counts are
exact, an average is the sum of sums over the sum of counts, and how many values of a label
report (``count(count by (L) (…))``) is how many distinct values of L the finer groups with a
count hold. So a family is read once per aggregation, not once per view (``plan``)."""

from __future__ import annotations

from . import Labels, Points

BASES = {"sum": ("sum",), "count": ("count",), "max": ("max",), "min": ("min",), "avg": ("sum", "count"),
         "distinct": ("count",)}

Rows = list[tuple[Labels, Points]]


def _key(labels: Labels, by: list[str]) -> tuple:
    return tuple((k, labels[k]) for k in by if k in labels)


def regroup(rows: Rows, by: list[str], fn: str) -> Rows:
    """Rows of a finer grouping aggregated by ``by`` with ``fn`` (sum, max, min) at each time."""
    red = {"sum": sum, "max": max, "min": min}[fn]
    groups: dict[tuple, dict[float, list[float]]] = {}
    for labels, pts in rows:
        g = groups.setdefault(_key(labels, by), {})
        for t, v in pts:
            g.setdefault(t, []).append(v)
    return [(dict(k), sorted((t, float(red(vs))) for t, vs in g.items())) for k, g in groups.items()]


def average(sums: Rows, counts: Rows, by: list[str]) -> Rows:
    s = {_key(lab, by): pts for lab, pts in regroup(sums, by, "sum")}
    c = {_key(lab, by): dict(pts) for lab, pts in regroup(counts, by, "sum")}
    out = []
    for k, pts in s.items():
        n = c.get(k, {})
        out.append((dict(k), [(t, v / n[t]) for t, v in pts if n.get(t)]))
    return [(lab, pts) for lab, pts in out if pts]


def distinct(counts: Rows, by: list[str], labels: list[str]) -> Rows:
    """How many distinct values of ``labels`` report, by ``by``, at each time."""
    groups: dict[tuple, dict[float, set]] = {}
    for lab, pts in counts:
        g = groups.setdefault(_key(lab, by), {})
        val = tuple(lab.get(x, "") for x in labels)
        for t, v in pts:
            if v > 0:
                g.setdefault(t, set()).add(val)
    return [(dict(k), sorted((t, float(len(vs))) for t, vs in g.items())) for k, g in groups.items()]


def derive(fine: dict[str, Rows], agg: str, by: list[str], labels: list[str] | None = None) -> Rows:
    """A view's rows from its finer reads by base aggregation (``fine["sum"]``, …)."""
    if agg in ("sum", "max", "min"):
        return regroup(fine[agg], by, agg)
    if agg == "count":
        return regroup(fine["count"], by, "sum")
    if agg == "avg":
        return average(fine["sum"], fine["count"], by)
    if agg == "distinct":
        return distinct(fine["count"], by, labels or [])
    raise ValueError(agg)


def fine_by(defs_by: list[list[str]]) -> list[str]:
    """The finest grouping that serves every one of ``defs_by``: their union, in first-seen order."""
    return list(dict.fromkeys(x for by in defs_by for x in by))


def expr(fn: str, by: list[str], inner: str) -> str:
    return f"{fn} by ({', '.join(by)}) ({inner})" if by else f"{fn}({inner})"
