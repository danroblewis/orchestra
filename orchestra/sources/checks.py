"""What a family's samples say of it, read from the store for inference (``schema.py``): its
reporting interval, a label's churn, its behaviour against its type (``behaviour.py``), a label of
the collection whose values repeat each other (``duplicates.py``), and whether a label names one
object rather than a group."""

from __future__ import annotations

import re
from itertools import pairwise
from statistics import median

from . import Labels, Points, Source
from .behaviour import classify
from .duplicates import duplicated
from .family import UNREAD, Family, LabelInfo, esc

CHURN = 0.1
OBJECT_LABEL = re.compile(r"(?i)(?:^|_)(?:u?uid|guid|id|ip|mac|hostname|nodename|pod|pod_name|container|container_name|version|revision|"
                          r"image|image_spec|hash|commit|sha)$")
COLLECTION_LABELS = {"job", "prometheus", "prometheus_replica", "replica", "__replica__", "scrape_job"}   # labels the collection adds
OBJECT_VALUE = re.compile(r"(?i)^(?:[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}|[0-9a-f]{12,}|"
                          r"\d{1,3}(?:\.\d{1,3}){3}(?::\d+)?|[a-z][a-z0-9+.-]*://.*|v?\d+\.\d+(?:\.\d+)?(?:[-+.].*)?)$")
PICKS = 6                   # series whose raw samples are read, at most, for a family's interval and behaviour
DUPLICATE_POINTS = 8        # points of the window at which a label's values are compared (duplicates.py)
DUPLICATE_SERIES = 5000     # a family with more series is not checked for a duplicating label
CHURN_POINTS = 24           # samples of the window when measuring churn
HIGH_CARDINALITY = 50


def samples(source: Source, sets: list[Labels], start: float, end: float, *, more: bool = False) -> list[Points]:
    """The raw samples of a few of the series ``sets`` names, over the window: of the first, middle
    and last that have samples in it (a listing by day names series that have none); with
    ``more``, of up to ``PICKS``, until two that move are read (a family's behaviour is judged from
    series that move)."""
    if not sets:
        return []
    n = len(sets)
    order = list(dict.fromkeys([0, n // 2, n - 1, n // 4, (3 * n) // 4, n // 8, (5 * n) // 8, (7 * n) // 8, (3 * n) // 8,
                                n // 16, (9 * n) // 16, (13 * n) // 16]))
    out: list[Points] = []
    for i in order[: 2 * PICKS]:
        sel = "{" + ",".join(f'{k}="{esc(v)}"' for k, v in sorted(sets[i].items())) + "}"
        for _, pts in source.select(sel, start, end):
            if pts:
                out.append(sorted(pts))
        moving = sum(1 for p in out if len({v for _, v in p}) > 1)
        if len(out) >= (PICKS if more else 3) or (not more and sum(max(0, len(p) - 1) for p in out) >= 6) or (more and moving >= 2):
            break
    return out


def interval(series: list[Points]) -> float | None:
    """The reporting interval: the largest of the series' median gaps between samples, so a
    lookback sized from it finds every series of the family, the slowest included."""
    medians = [median(b - a for a, b in pairwise(t for t, _ in p)) for p in series if len(p) >= 3]
    return round(max(medians), 3) if medians else None


def churn(source: Source, sel: str, real: str, r: float, start: float, end: float) -> tuple[int, float]:
    """Values of ``real`` with samples in the window, and the share of them not reporting at an
    average moment of it."""
    seen = source.query_range(f"count(count by ({real}) (count_over_time({sel}[{int(end - start) + 1}s])))", end, end, 60)
    distinct = int(seen[0][1][-1][1]) if seen and seen[0][1] else 0
    if distinct <= 1:
        return distinct, 0.0
    step = max(r, (end - start) / CHURN_POINTS)
    now = source.query_range(f"count(count by ({real}) (last_over_time({sel}[{int(r) + 1}s])))", start + step, end, step)
    vals = [v for _, pts in now for _, v in pts]
    steps = max(1, int((end - start - step) // step) + 1)
    present = (sum(vals) / steps) if vals else 0.0
    return distinct, round(max(0.0, 1.0 - present / distinct), 3)


def behave(source: Source, fam: Family, raw: list[Points], typ: str | None, start: float, end: float) -> None:
    """The family's kind checked against its samples (behaviour.py); the least and largest value of
    all its series are read only when every sample read is 1 (an info metric must be 1 throughout)."""
    low = high = None
    if all(v == 1.0 for p in raw for _, v in p):
        w, sel = f"{int(end - start) + 1}s", fam.selector()
        lo = source.query_range(f"min(min_over_time({sel}[{w}]))", end, end, 60)
        hi = source.query_range(f"max(max_over_time({sel}[{w}]))", end, end, 60)
        low = lo[0][1][-1][1] if lo and lo[0][1] else None
        high = hi[0][1][-1][1] if hi and hi[0][1] else None
    kind, why = classify(fam.first_metric(), "counter" if fam.kind == "counter" else typ, fam.help, raw, low=low, high=high)
    if kind and kind != fam.kind:
        fam.kind, fam.retyped = kind, why


def dedupe(source: Source, fam: Family, start: float, end: float) -> None:
    """A label the collection adds (a scrape job, a Prometheus replica: ``COLLECTION_LABELS``) of
    two to four values whose values only repeat each other's series (duplicates.py): only one
    value is read from then on, and the label is constant. Other labels are never merged so: two
    nodes of one size or two message types counted alike are two things that happen to agree."""
    cands = [c for c, i in fam.labels.items() if i.role == "grouping" and 2 <= i.cardinality <= 4 and i.real in COLLECTION_LABELS]
    if not cands or fam.series > DUPLICATE_SERIES or fam.kind in (*UNREAD, "rollup"):
        return
    step = max(1.0, (end - start) / (DUPLICATE_POINTS - 1))
    r = int(1.5 * (fam.resolution_s or 60.0)) + 1
    got = source.query_range(f"last_over_time({fam.selector(fam.stats[0] if fam.stats else None)}[{r}s])", start, end, step)
    grid = [start + k * step for k in range(DUPLICATE_POINTS)]
    series = []
    for lab, pts in got:
        at = dict(pts)
        series.append((lab, [next((at[t] for t in at if abs(t - g) < step / 2), None) for g in grid]))
    for c in cands:
        real = fam.labels[c].real
        if (dup := duplicated(series, real)) is None:
            continue
        keep, dropped = dup
        fam.where[real] = keep
        fam.labels[c] = LabelInfo(real, 1, 0.0, "constant")
        fam.constants[c] = keep
        fam.series = max(1, fam.series // (1 + len(dropped)))
        fam.notes.append(f"{real}={', '.join(dropped)} only repeats {real}={keep}, series for series: only {keep} is read")
        series = [(lab, v) for lab, v in series if lab.get(real) not in dropped]


def is_object(canonical: str, real: str, values: set[str]) -> bool:
    """Whether a label names one object, not a group: its name says an id, an address, a pod, a
    container or a version, or most of its values look like ids (a UUID, a long hex string, an IP
    address, a URL, a version number)."""
    if OBJECT_LABEL.search(canonical) or OBJECT_LABEL.search(real):
        return True
    return bool(values) and sum(1 for v in values if OBJECT_VALUE.match(v)) >= 0.5 * len(values)
