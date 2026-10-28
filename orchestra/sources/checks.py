"""What a family's labels and listing say of it, without reading its samples (``schema.py``):
which series to sample (``pick``), its reporting interval from samples read, whether a label
names one object rather than a group (``is_object``), whether it names a unit (``is_unit``), and
the unit a metric's name gives (``name_unit``). The reads themselves, batched across families,
are ``census.py``."""

from __future__ import annotations

import re
from itertools import pairwise
from statistics import median

from . import Labels, Points
from .family import esc

CHURN = 0.1
OBJECT_LABEL = re.compile(r"(?i)(?:^|_)(?:u?uid|guid|id|ip|mac|hostname|nodename|pod|pod_name|container|container_name|version|revision|"
                          r"image|image_spec|hash|commit|sha)$")
COLLECTION_LABELS = {"job", "prometheus", "prometheus_replica", "replica", "__replica__", "scrape_job", "exported_job"}   # labels the collection adds
OBJECT_VALUE = re.compile(r"(?i)^(?:[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}|[0-9a-f]{12,}|"
                          r"\d{1,3}(?:\.\d{1,3}){3}(?::\d+)?|[a-z][a-z0-9+.-]*://.*|v?\d+\.\d+(?:\.\d+)?(?:[-+.].*)?)$")
UNIT_LABELS = {"unit", "units", "resource"}
UNIT_VALUES = {"byte", "bytes", "core", "cores", "cpu", "memory", "second", "seconds", "ms", "milliseconds", "ratio", "percent",
               "celsius", "kib", "mib", "gib", "kb", "mb", "gb", "count", "requests", "integer", "ephemeral_storage", "pods",
               "nvidia_com_gpu", "storage", "hugepages_2mi", "hugepages_1gi"}
NAME_UNITS = (("_bytes_total", "bytes"), ("_bytes", "bytes"), ("_seconds_total", "seconds"), ("_seconds", "seconds"),
              ("_milliseconds", "milliseconds"), ("_cores", "cores"), ("_cpu", "cores"), ("_ratio", "ratio"),
              ("_percent", "percent"), ("_celsius", "celsius"), ("_total", "events"))
PICKS = 6                   # series whose raw samples are read, at most, for a family's interval and behaviour
DUPLICATE_POINTS = 30       # points of the window at which a label's values are compared (duplicates.py)
DUPLICATE_SERIES = 5000     # a family with more series is not checked for a duplicating label
CHURN_POINTS = 24           # samples of the window when measuring churn
HIGH_CARDINALITY = 50


def order(n: int) -> list[int]:
    """Indices of a listing of ``n`` series in the order they are sampled: spread over it."""
    return list(dict.fromkeys([0, n // 2, n - 1, n // 4, (3 * n) // 4, n // 8, (5 * n) // 8, (7 * n) // 8, (3 * n) // 8,
                               n // 16, (9 * n) // 16, (13 * n) // 16]))


def pick(metric: str, sets: list[Labels], n: int) -> tuple[str, int]:
    """A selector for about ``n`` (up to ``2n``) of the series ``sets`` names, spread over the
    listing, and how many it selects: the metric alone when it has few series, else the values of
    its most varied label at the sampled positions (a listing by day names series with no samples
    in the window, so twice as many are asked for as are needed)."""
    if len(sets) <= 2 * n:
        return metric, len(sets)
    labels = {k for s in sets for k in s}
    best = max(sorted(labels), key=lambda k: len({s.get(k) for s in sets}))
    vals: list[str] = []
    for i in order(len(sets)):
        v = sets[i].get(best)
        if v is not None and v not in vals:
            vals.append(v)
        if sum(1 for s in sets if s.get(best) in vals) >= 2 * n:
            break
    count = sum(1 for s in sets if s.get(best) in vals)
    if count > 8 * n:                       # one value names too many: the first sampled series exactly
        first = sets[order(len(sets))[0]]
        return metric + "{" + ",".join(f'{k}="{esc(v)}"' for k, v in sorted(first.items())) + "}", 1
    rx = "|".join(re.escape(v) for v in vals)
    return f'{metric}{{{best}=~"{esc(rx)}"}}', count


def interval(series: list[Points]) -> float | None:
    """The reporting interval: the largest of the series' median gaps between samples, so a
    lookback sized from it finds every series of the family, the slowest included."""
    medians = [median(b - a for a, b in pairwise(t for t, _ in p)) for p in series if len(p) >= 3]
    return round(max(medians), 3) if medians else None


def is_object(canonical: str, real: str, values: set[str]) -> bool:
    """Whether a label names one object, not a group: its name says an id, an address, a pod, a
    container or a version, or most of its values look like ids (a UUID, a long hex string, an IP
    address, a URL, a version number)."""
    if OBJECT_LABEL.search(canonical) or OBJECT_LABEL.search(real):
        return True
    return bool(values) and sum(1 for v in values if OBJECT_VALUE.match(v)) >= 0.5 * len(values)


def is_unit(canonical: str, real: str, values: set[str]) -> bool:
    """Whether a label says what unit each series is in (``unit``, ``resource``, or values that are
    units: ``cpu``/``memory``, ``core``/``byte``): a sum over it adds cores to bytes."""
    if canonical in UNIT_LABELS or real in UNIT_LABELS:
        return True
    return len(values) > 1 and all(v.lower().replace(".", "_").replace("/", "_") in UNIT_VALUES for v in values)


def name_unit(name: str) -> str | None:
    """The unit a metric's name ends with, by Prometheus' naming convention."""
    n = name.lower()
    return next((u for suffix, u in NAME_UNITS if n.endswith(suffix)), None)
