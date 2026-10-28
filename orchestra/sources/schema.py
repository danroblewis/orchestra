"""What a remote store holds, read from its schema: metric names, families, label aliases, which
labels name a reporting thing (identity) and which group (grouping), how often series report, and
what their samples say they are.

1. **Families.** Names that differ only by a statistic suffix (``_max``, ``_p95``, …) are one
   family with a statistic dimension, and so is a metric whose statistic is a label (``stat``,
   ``statistic``, ``quantile``), colon in its name or not. A histogram's
   ``_bucket``/``_count``/``_sum`` are one family (its ``_count`` is read as a counter), and so are
   a summary's ``_count``/``_sum``: the store may keep a summary's or a histogram's type under its
   base name only (VictoriaMetrics does), and a ``_count`` with a ``_sum`` beside it and no type of
   its own is one too. A recording rule (``level:metric:sum``, ``metric:avg``, ``…:sum_rate5m``,
   ``job:metric:rate5m``) is a view of its base metric by that function: it joins the base's
   family when the base is there (and is preferred to the base's own view of the same function),
   else the rules of one base make one family of their own. Its name is a hint: a rule named a
   rate of a base that is no counter and whose name is intensive (a utilisation) is a gauge.
2. **Aliases.** Each family's real labels are renamed to canonical names by ``[sources.labels]``:
   the first spelling a metric has wins. Queries use the real label; results are renamed.
3. **Roles.** A label is **identity** (a pod: aggregated away or counted, never kept) when its
   canonical name is one of the source's ``identity`` names, when it names one object (an id, a
   UUID, an address, a pod, a container, a version: ``checks.is_object``), when its values churn (on
   average a tenth of the values seen in the window are not reporting at a given moment), or when
   it has more than ``HIGH_CARDINALITY`` values; a label with one value is **constant**; the rest
   are **grouping** labels (service, queue, phase). A grouping label whose values only repeat each
   other's series (two scrape jobs of one exporter: ``duplicates.py``) is read at one value.
   A label that names a **unit** (``unit``, ``resource``, or values such as ``cpu``/``memory``:
   ``checks.is_unit``) is kept in every view, never summed across.
4. **Resolution.** The reporting interval, from a raw read of a few series: the largest of their
   median gaps between samples. A recording rule's is its own (rules are evaluated on their own
   interval, often slower than their base is scraped).
5. **Behaviour.** The same samples check the family's type (``behaviour.py``): a gauge that only
   rises but by resets is a counter, a counter that falls by halves is a gauge, and timestamps,
   clocks and info metrics are read as neither levels nor flows; nor are Prometheus' own series
   about each scrape (``up``, ``scrape_*``: ``SCRAPE_SERIES``), which measure the collection. A
   family the window cannot judge is judged over the source's longer ``history`` too, and a type
   once judged changes only when the samples decide it, never on a name alone. A metric typed a
   histogram with no classic parts is a **native histogram**, read by its count.
6. **Units.** The store's metadata, else the name's suffix (``_bytes``, ``_seconds``, ``_total``):
   each definition carries its unit, and its unit label when a label says it.

Every read of samples is batched across families (``census.py``, ``survey.py``). A family that
cannot be read in a round (a refusal that outlasted the retries, the round's deadline or budget)
**keeps what the last round found of it**; one never judged is **unknown**, listed and left out,
never given a type its data did not show.

The store's series listing may count values by day (VictoriaMetrics' index), so cardinality and
churn are measured from samples within the window instead."""

from __future__ import annotations

import re

from . import Labels, Source
from .checks import COLLECTION_LABELS, name_unit
from .family import UNREAD, Family, LabelInfo, Schema, stat_name
from .spec import SourceSpec

__all__ = ["COLLECTION_LABELS", "UNREAD", "Family", "LabelInfo", "Schema", "read", "rule_of", "stat_name"]

STAT_SUFFIX = re.compile(r"^(?P<base>.+)_(?P<stat>max|min|avg|mean|median|p\d{2,3})$")
STAT_LABELS = ("stat", "statistic", "quantile")
HIST_PART = re.compile(r"^(?P<base>.+)_(?P<part>bucket|count|sum)$")
ROLLUP = re.compile(r"^(?:(?P<level>[a-zA-Z_][a-zA-Z0-9_]*):)?(?P<base>[a-zA-Z_][a-zA-Z0-9_]*):"
                    r"(?P<ops>(?P<fn>sum|avg|max|min|count)(?:_(?:rate|irate|increase)[a-zA-Z0-9_]*)?|(?P<rfn>rate|irate|increase)[a-zA-Z0-9_]*)$")
SKIP_LABELS = {"__name__", "le"}
INTENSIVE = re.compile(r"(?i)latency|duration|seconds|ratio|percent|utili[sz]ation|temperature|_p\d\d")
SCRAPE_SERIES = {"up", "scrape_duration_seconds", "scrape_samples_scraped", "scrape_samples_post_metric_relabeling", "scrape_series_added",
                 "scrape_timeout_seconds", "scrape_sample_limit", "scrape_body_size_bytes"}   # Prometheus' own, one per target per scrape



def rule_of(name: str) -> dict | None:
    """A recording rule's name read: its base metric, the function it applies, and whether it is
    a rate; None when the name is not ``[level:]metric:operations`` with a known function."""
    m = ROLLUP.match(name)
    if not m:
        return None
    fn = m["fn"] or "rate"                       # rate, irate and increase: a rate, summed across series
    return {"metric": name, "of": m["base"], "fn": fn, "rate": fn == "rate" or "rate" in m["ops"] or "increase" in m["ops"],
            "level": m["level"]}


def _join_rules(out: list[Family], rules: dict[str, list[dict]]) -> None:
    """Each base's recording rules into its family when the base is there (as ``rollups``, one
    per function), else into one family of the rules of that base."""
    by_name = {f.name: f for f in out}
    for base, rs in sorted(rules.items()):
        fam = by_name.get(base) or by_name.get(f"{base}_total")
        for r in rs:
            if fam is None:
                fam = Family(r["metric"], "rollup", {r["metric"]: None}, rollup={k: r[k] for k in ("of", "fn", "rate", "level")})
                out.append(fam)
            if r["fn"] in fam.rollups:               # the same function at another level: a family of its own
                out.append(Family(r["metric"], "rollup", {r["metric"]: None}, rollup={k: r[k] for k in ("of", "fn", "rate", "level")},
                                  rollups={r["fn"]: r}))
            else:
                fam.rollups[r["fn"]] = r


def _counter_known(base: str, names: dict[str, list[Labels]], meta: dict[str, dict]) -> bool:
    """Whether ``base`` is a counter in the store: typed so, or named ``…_total``, under its own
    name or with ``_total``."""
    return any(n in names and ((meta.get(n) or {}).get("type") == "counter" or n.endswith("_total")) for n in (base, f"{base}_total"))


def _a_rule(n: str, names: dict[str, list[Labels]], meta: dict[str, dict]) -> dict | None:
    """A recording rule read from its name, unless its data says otherwise: a rule named a rate
    (``…:rate5m``) of a base that is no counter in the store and whose name says it is intensive
    (``instance:node_cpu_utilisation:rate5m``, a 0–1 ratio) is a gauge; so is a rule whose series
    carry a statistic label (``quantile``)."""
    r = rule_of(n)
    if r is None or any(sl in lab for sl in STAT_LABELS for lab in names[n]):
        return None
    if r["rate"] and INTENSIVE.search(r["of"]) and not _counter_known(r["of"], names, meta):
        return None
    return r


def _group(names: dict[str, list[Labels]], meta: dict[str, dict]) -> list[Family]:
    """Metric names into families (step 1)."""
    out: list[Family] = []
    taken: set[str] = set()
    rules: dict[str, list[dict]] = {}
    for n in sorted(names):
        if ":" in n and (r := _a_rule(n, names, meta)):
            r["labels"] = sorted({k for lab in names[n] for k in lab} - SKIP_LABELS)
            rules.setdefault(r["of"], []).append(r)
            taken.add(n)
    for n in sorted(names):
        m = HIST_PART.match(n)
        if n in taken or not m or m["part"] == "sum":
            continue
        base = m["base"]
        typ = (meta.get(base) or {}).get("type")
        own = (meta.get(f"{base}_count") or {}).get("type")
        if m["part"] == "bucket":
            what = "histogram"
        elif typ in ("summary", "histogram") or (f"{base}_sum" in names and own in (None, "", "unknown", "counter", "summary")):
            what = typ if typ in ("summary", "histogram") else "summary"
        else:
            continue
        if f"{base}_count" not in names or f"{base}_count" in taken:
            taken.update(x for x in (f"{base}_bucket", f"{base}_sum") if x in names)
            continue
        taken.update(x for x in (f"{base}_bucket", f"{base}_count", f"{base}_sum") if x in names)
        out.append(Family(f"{base}_count", "counter", {f"{base}_count": None},
                          help=f"the count of a {what} ({base}); its {'buckets and ' if what == 'histogram' else ''}_sum are not read"))
    by_base: dict[str, dict[str, str]] = {}
    for n in names:
        if n not in taken and (m := STAT_SUFFIX.match(n)):
            by_base.setdefault(m["base"], {})[n] = stat_name(m["stat"])
    for base, ms in sorted(by_base.items()):
        if len(set(ms.values())) >= 2:
            out.append(Family(base, "gauge", dict(sorted(ms.items()))))
            taken.update(ms)
    for n in sorted(set(names) - taken):
        typ = (meta.get(n) or {}).get("type")
        stat_label = next((s for s in STAT_LABELS if any(s in lab for lab in names[n])), None)
        kind = "counter" if typ in ("counter", "histogram") or (typ in (None, "", "unknown") and n.endswith("_total")) else "gauge"
        if stat_label:
            kind = "gauge"
        fam = Family(n, kind, {n: None}, stat_label)
        if typ == "histogram" and not stat_label:          # typed a histogram with no _bucket/_count: a native one
            fam.counter_form = "native"
            fam.help = "a native histogram, read by its count; its sum is not read"
        if stat_label:
            fam.stat_values = {stat_name(lab[stat_label]): lab[stat_label] for lab in names[n] if stat_label in lab}
        out.append(fam)
    _join_rules(out, rules)
    for fam in out:
        if fam.name in SCRAPE_SERIES:
            fam.kind, fam.retyped = "scrape", "Prometheus' own series about each scrape: a measurement of the collection, not of the system"
        md = meta.get(fam.first_metric()) or {}
        fam.unit = fam.unit or md.get("unit") or name_unit(fam.first_metric().removesuffix("_count")) or None
        fam.help = fam.help or md.get("help") or None
    return out


def _aliases(real: set[str], spec: SourceSpec) -> dict[str, str]:
    """canonical -> real for one family's labels (step 2): the first spelling it has wins; a
    label no alias names keeps its own name."""
    out: dict[str, str] = {}
    for canonical, spellings in spec.labels.items():
        if (hit := next((s for s in spellings if s in real), None)) is not None:
            out[canonical] = hit
    used = set(out.values())
    for r in sorted(real - used):
        out.setdefault(r, r)
    return out


def read(source: Source, spec: SourceSpec, start: float, end: float, *, until: float | None = None,
         known: dict[str, dict] | None = None) -> Schema:
    """The families of what ``spec.match`` selects, with aliases, roles and resolution, read by
    ``until`` (``time.monotonic()``); ``known``: the last round's families by name, which a family
    that cannot be read this round keeps (``survey.py``)."""
    from .survey import survey
    return survey(source, spec, start, end, until=until, known=known)
