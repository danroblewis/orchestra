"""The same measurement twice, found from the data and kept once.

1. **A label that duplicates** (``duplicated``): a family whose series under one value of a
   label the collection adds (``checks.COLLECTION_LABELS``: a job, a replica) are the series under
   another. Two scrape jobs of one exporter (``job="node-exporter"`` and
   ``job="integrations/node_exporter"``), an agent migration, two replicas of one Prometheus:
   summing over that label counts everything twice. Matched by **target identity** first: each
   series of one value must pair, one for one, with a series of the other scraped from the same
   target (its ``instance`` without the port, an ``ip-10-0-1-1`` host name read as its address,
   or a ``node``/``hostname`` label naming it: ``target``) with the same values of the labels both
   values' series carry. Two jobs scraping different nodes never pair, whatever their values. The
   pairs are then checked by their data: a counter by its **increase over each quarter of the
   window** (its total is no evidence: two large counters agree to 0.5% whatever their rates), a
   gauge by its values, each within ``TOLERANCE`` or the series' own step-to-step change, at
   ``AGREE`` of the points (a scrape offset makes a few differ). Equal constants prove nothing (two deployments of 2 pods
   each), so it takes a series that moves or two different series that match.
2. **Counts of the same things** (``same_shape``): the pods of a service are counted from every
   family they report, under each family's own labels; two counts whose series match at almost
   every point, and at every point where either changes, count the same things, and one is
   enough (two deployments of three pods agree but at their rollouts: two things). So do two counters of different
   families equal at every point (a histogram's ``_count`` and the counter of the same requests)."""

from __future__ import annotations

import re
from itertools import pairwise
from statistics import median

TOLERANCE = 0.005       # relative, per point
AGREE = 0.8             # of the points both pair members have
COUNTER_TOLERANCE = 0.05   # relative, on a counter's increase over a quarter of the window
SHAPE_AGREE = 0.9       # of the points two counts have (and every point where either changes)
TARGET_LABELS = ("node", "nodename", "hostname", "host", "agent_hostname", "kubernetes_node", "exported_instance")
AWS_HOST = re.compile(r"^ip-(\d+)[-.](\d+)[-.](\d+)[-.](\d+)(?:\..*)?$")
PORT = re.compile(r":\d+$")


def _close(a: float, b: float, tol: float) -> bool:
    return abs(a - b) <= tol * max(abs(a), abs(b), 1e-9)


def matches(a: list[float | None], b: list[float | None], tol: float = TOLERANCE, agree: float = AGREE) -> bool:
    """Whether two series on one grid agree at almost every point both have."""
    both = [(x, y) for x, y in zip(a, b, strict=False) if x is not None and y is not None]
    return len(both) >= 3 and sum(_close(x, y, tol) for x, y in both) >= agree * len(both)


def moves(v: list[float | None]) -> bool:
    vals = [x for x in v if x is not None]
    return len(set(vals)) > 1


def target(labels: dict[str, str]) -> set[str]:
    """The names of the target a series was scraped from: its instance without the port, an EC2
    host name (``ip-10-0-1-1.…``) as its address too, and any label that names a node or host."""
    out: set[str] = set()
    for k in ("instance", *TARGET_LABELS):
        v = labels.get(k)
        if not v:
            continue
        v = PORT.sub("", v.strip().lower()).strip("[]")
        out.add(v)
        out.add(v.split(".")[0] if not v.replace(".", "").isdigit() else v)
        if m := AWS_HOST.match(v):
            out.add(".".join(m.groups()))
    return out


def _increments(v: list[float | None]) -> list[float | None]:
    return [None if a is None or b is None else (b - a if b >= a else b) for a, b in pairwise(v)]


def _agree(a: list[float | None], b: list[float | None], counter: bool) -> bool:
    """A pair's data agrees: a counter's increase over each quarter of the window within
    ``COUNTER_TOLERANCE`` (two scrapes offset by seconds differ by a scrape's worth over a short
    step, never over a quarter hour), or a gauge's values, each within TOLERANCE or the series' own
    typical step-to-step change, at AGREE of the points both have."""
    if counter:
        both = [(x, y) for x, y in zip(_increments(a), _increments(b), strict=False) if x is not None and y is not None]
        if len(both) < 4:
            return False
        q = len(both) / 4
        blocks = [both[round(i * q):round((i + 1) * q)] for i in range(4)]
        sums = [(sum(x for x, _ in blk), sum(y for _, y in blk)) for blk in blocks]
        return all(abs(x - y) <= max(COUNTER_TOLERANCE * max(abs(x), abs(y)), 1e-9) for x, y in sums)
    both = [(x, y) for x, y in zip(a, b, strict=False) if x is not None and y is not None]
    if len(both) < 3:
        return False
    steps = [abs(y - x) for x, y in pairwise([p for p, _ in both])]
    slack = median(steps) if steps else 0.0
    ok = sum(abs(x - y) <= max(TOLERANCE * max(abs(x), abs(y)), slack, 1e-9) for x, y in both)
    return ok >= AGREE * len(both)


def _pairs(a: list[tuple[dict, list]], b: list[tuple[dict, list]], label: str) -> list[tuple[list, list]] | None:
    """Each series of ``b`` paired with one of ``a`` from the same target, with the same values of
    the labels every series of both carries; None when they do not pair one for one."""
    if len(a) != len(b):
        return None
    shared = set.intersection(*(set(lab) for lab, _ in a + b)) - {label, "instance", *TARGET_LABELS}
    key = lambda lab: tuple(sorted((k, lab[k]) for k in shared))
    free = list(range(len(a)))
    out = []
    for lab, v in b:
        names, k = target(lab), key(lab)
        hit = next((i for i in free if key(a[i][0]) == k and (target(a[i][0]) & names or not (names or target(a[i][0])))), None)
        if hit is None:
            return None
        free.remove(hit)
        out.append((a[hit][1], v))
    return out


def duplicated(series: list[tuple[dict[str, str], list[float | None]]], label: str, *,
               counter: bool = False) -> tuple[str, list[str]] | None:
    """(the value kept, the values that only repeat it) when ``label`` duplicates the family's
    series (``series``: labels and values on one grid; ``counter``: compare increments), else
    None. The value kept is the one with the most series, then the first by name."""
    by: dict[str, list[tuple[dict, list]]] = {}
    for lab, v in series:
        if label in lab:
            by.setdefault(lab[label], []).append((lab, v))
    if len(by) < 2:
        return None
    order = sorted(by, key=lambda x: (-len(by[x]), x))
    keep = order[0]
    a = by[keep]
    if not (any(moves(v) for _, v in a) or len({tuple(v) for _, v in a}) >= 2):
        return None
    dropped = []
    for other in order[1:]:
        pairs = _pairs(a, by[other], label)
        if pairs and all(_agree(x, y, counter) for x, y in pairs):
            dropped.append(other)
    return (keep, dropped) if dropped else None


def _key(v: list[float | None]) -> tuple:
    vals = [x for x in v if x is not None]
    return (vals[-1], vals[0]) if vals else (0.0, 0.0)


def _lagged(both: list[tuple[float, float]], i: int) -> bool:
    """Two counts that differ at ``i`` only because one saw the change a point before the other
    (two exporters scraped apart): one equals the other shifted by a point, on both sides of it."""
    x, y = [p for p, _ in both], [q for _, q in both]
    near = lambda a, b: abs(a - b) <= 0.5
    for u, v in ((x, y), (y, x)):
        if 0 < i < len(x) - 1 and near(u[i], v[i - 1]) and near(u[i + 1], v[i]):
            return True
    return False


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
        if len(both) < 3 or sum(ok) < (len(both) if exact else SHAPE_AGREE * len(both)):
            return False
        if not exact and not all(ok[i] or _lagged(both, i) for i in range(1, len(both))
                                 if both[i][0] != both[i - 1][0] or both[i][1] != both[i - 1][1]):
            return False
    return True
