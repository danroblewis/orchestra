"""What a remote store holds, read from its schema: metric names, families, label aliases, which
labels name a reporting thing (identity) and which group (grouping), and how often series report.

1. **Families.** Names that differ only by a statistic suffix (``_max``, ``_p95``, …) are one
   family with a statistic dimension, and so is a metric whose statistic is a label (``stat``,
   ``statistic``, ``quantile``). A histogram's ``_bucket``/``_count``/``_sum`` are one family (its
   ``_count`` is read as a counter). A recording rule (``level:metric:sum``, ``metric:avg``,
   ``…:sum_rate5m``, ``job:metric:rate5m``) is a view of its base metric by that function: it
   joins the base's family when the base is there (and is preferred to the base's own view of
   the same function), else the rules of one base make one family of their own.
2. **Aliases.** Each family's real labels are renamed to canonical names by ``[sources.labels]``:
   the first spelling a metric has wins. Queries use the real label; results are renamed.
3. **Roles.** A label is **identity** (a pod: aggregated away or counted, never kept) when its
   canonical name is one of the source's ``identity`` names, when its values churn (on average a
   fifth of the values seen in the window are not reporting at a given moment), or when it has
   more than ``HIGH_CARDINALITY`` values; a label with one value is **constant**; the rest are
   **grouping** labels (service, region).
4. **Resolution.** The reporting interval, from a short raw read of a few series: the median gap
   between samples.

The store's series listing may count values by day (VictoriaMetrics' index), so cardinality and
churn are measured from samples within the window instead."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from itertools import pairwise
from statistics import median

from . import Labels, Source, SourceError
from .spec import SourceSpec

STAT_SUFFIX = re.compile(r"^(?P<base>.+)_(?P<stat>max|min|avg|mean|median|p\d{2,3})$")
STAT_LABELS = ("stat", "statistic", "quantile")
HIST_PART = re.compile(r"^(?P<base>.+)_(?P<part>bucket|count|sum)$")
ROLLUP = re.compile(r"^(?:(?P<level>[a-zA-Z_][a-zA-Z0-9_]*):)?(?P<base>[a-zA-Z_][a-zA-Z0-9_]*):"
                    r"(?P<ops>(?P<fn>sum|avg|max|min|count)(?:_(?:rate|irate|increase)[a-zA-Z0-9_]*)?|(?P<rfn>rate|irate|increase)[a-zA-Z0-9_]*)$")
SKIP_LABELS = {"__name__", "le"}
HIGH_CARDINALITY = 50
CHURN = 0.2
SCHEMA_LIMIT = 20000        # label sets read from the listing
CHURN_POINTS = 24           # samples of the window when measuring churn


def stat_name(v: str) -> str:
    """One spelling per statistic: mean is avg, median is p50, a quantile 0.95 is p95."""
    v = v.lower()
    try:
        q = float(v)
        if 0 < q < 1:
            return f"p{round(q * 100)}" if round(q * 100) * 10 == round(q * 1000) else f"p{round(q * 1000)}"
    except ValueError:
        pass
    return {"mean": "avg", "average": "avg", "median": "p50"}.get(v, v)


@dataclass
class LabelInfo:
    real: str
    cardinality: int
    churn: float
    role: str                    # identity | grouping | constant


@dataclass
class Family:
    name: str                    # the base metric
    kind: str                    # gauge | counter | histogram | rollup
    metrics: dict[str, str | None]            # real metric name -> the statistic it holds (suffix families)
    stat_label: str | None = None             # the label holding the statistic, when it is a label
    stat_values: dict[str, str] = field(default_factory=dict)   # statistic -> the label's real value
    labels: dict[str, LabelInfo] = field(default_factory=dict)  # canonical -> info
    series: int = 0              # label sets of one statistic
    resolution_s: float | None = None
    unit: str | None = None
    help: str | None = None
    rollup: dict | None = None   # {"of", "fn", "rate", "level"}: a family made of recording rules, its first one
    rollups: dict[str, dict] = field(default_factory=dict)      # function -> {"metric", "of", "fn", "rate", "level", "labels"}: its rules
    constants: dict[str, str] = field(default_factory=dict)     # canonical -> the one value of a constant label

    @property
    def stats(self) -> list[str]:
        return sorted(self.stat_values) if self.stat_label else sorted(s for s in self.metrics.values() if s)

    def selector(self, stat: str | None = None) -> str:
        """The selector for one statistic of this family (or its one metric)."""
        if self.stat_label and stat:
            return f'{self.first_metric()}{{{self.stat_label}="{self.stat_values[stat]}"}}'
        if stat:
            return next(m for m, s in self.metrics.items() if s == stat)
        return self.first_metric()

    def first_metric(self) -> str:
        return next(iter(self.metrics))

    def role(self, role: str) -> list[str]:
        return [c for c, i in self.labels.items() if i.role == role]


@dataclass
class Schema:
    families: list[Family]
    notes: list[str] = field(default_factory=list)


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


def _group(names: dict[str, list[Labels]], meta: dict[str, dict]) -> list[Family]:
    """Metric names into families (step 1)."""
    out: list[Family] = []
    taken: set[str] = set()
    rules: dict[str, list[dict]] = {}
    for n in sorted(names):
        if ":" in n:
            if r := rule_of(n):
                r["labels"] = sorted({k for lab in names[n] for k in lab} - SKIP_LABELS)
                rules.setdefault(r["of"], []).append(r)
            else:
                out.append(Family(n, "gauge", {n: None}))
            taken.add(n)
    hist = {}
    for n in names:
        if n not in taken and (m := HIST_PART.match(n)) and m["part"] == "bucket":
            hist[m["base"]] = Family(m["base"] + "_count", "counter", {})
    for base, fam in hist.items():
        for part in ("bucket", "count", "sum"):
            if f"{base}_{part}" in names:
                taken.add(f"{base}_{part}")
        if f"{base}_count" in names:
            fam.metrics[f"{base}_count"] = None
            fam.help = f"the count of a histogram ({base}); its buckets and _sum are not read"
            out.append(fam)
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
        kind = "counter" if typ == "counter" or (typ in (None, "", "unknown") and n.endswith("_total")) else "gauge"
        if stat_label:
            kind = "gauge"
        fam = Family(n, kind, {n: None}, stat_label)
        if stat_label:
            fam.stat_values = {stat_name(lab[stat_label]): lab[stat_label] for lab in names[n] if stat_label in lab}
        out.append(fam)
    _join_rules(out, rules)
    for fam in out:
        md = meta.get(fam.first_metric()) or {}
        fam.unit = fam.unit or md.get("unit") or None
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


def _resolution(source: Source, fam: Family, sets: list[Labels], end: float, window: float) -> float | None:
    """The reporting interval: the median gap between samples of up to three series."""
    gaps: list[float] = []
    picks = [sets[0], sets[len(sets) // 2], sets[-1]] if sets else []
    for lab in picks:
        sel = "{" + ",".join(f'{k}="{_esc(v)}"' for k, v in sorted(lab.items())) + "}"
        for span in (min(window, 1800.0), window):
            got = source.select(sel, end - span, end)
            ts = sorted({t for _, pts in got for t, _ in pts})
            if len(ts) >= 3:
                gaps += [b - a for a, b in pairwise(ts)]
                break
        if len(gaps) >= 6:
            break
    return round(median(gaps), 3) if gaps else None


def _esc(v: str) -> str:
    return v.replace("\\", "\\\\").replace('"', '\\"')


def _churn(source: Source, sel: str, real: str, r: float, start: float, end: float) -> tuple[int, float]:
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


def read(source: Source, spec: SourceSpec, start: float, end: float) -> Schema:
    """The families of what ``spec.match`` selects, with aliases, roles and resolution."""
    sets = source.series(spec.match, start, end, SCHEMA_LIMIT)
    notes = [f"the listing was cut at {SCHEMA_LIMIT} series; narrow match to infer from all"] if len(sets) >= SCHEMA_LIMIT else []
    names: dict[str, list[Labels]] = {}
    for lab in sets:
        n = lab.get("__name__")
        if n:
            names.setdefault(n, []).append({k: v for k, v in lab.items() if k != "__name__"})
    meta = source.metadata()
    families = _group(names, meta)
    for fam in families:
        fam_sets = [lab for m in fam.metrics for lab in names.get(m, [])]
        real = {k for lab in fam_sets for k in lab} - SKIP_LABELS - ({fam.stat_label} if fam.stat_label else set())
        one = [lab for lab in names.get(fam.first_metric(), []) if not fam.stat_label or lab.get(fam.stat_label) == next(iter(fam.stat_values.values()), None)]
        fam.series = len({tuple(sorted((k, v) for k, v in lab.items() if k != fam.stat_label)) for lab in one}) or len(fam_sets)
        try:
            fam.resolution_s = _resolution(source, fam, [{"__name__": fam.first_metric(), **x} for x in one or fam_sets], end, end - start)
        except SourceError as e:
            notes.append(f"{fam.name}: could not read its reporting interval: {e}")
        r = 1.5 * (fam.resolution_s or 60.0)
        sel = fam.selector(fam.stats[0] if fam.stats else None)
        for canonical, rl in _aliases(real, spec).items():
            values = {lab[rl] for lab in fam_sets if rl in lab}
            if canonical in spec.identity:
                fam.labels[canonical] = LabelInfo(rl, len(values), 0.0, "identity")
                continue
            if len(values) <= 1:
                fam.labels[canonical] = LabelInfo(rl, len(values), 0.0, "constant")
                if values:
                    fam.constants[canonical] = next(iter(values))
                continue
            try:
                card, churn = _churn(source, sel, rl, r, start, end)
            except SourceError as e:
                notes.append(f"{fam.name}: could not measure {rl}'s churn: {e}")
                card, churn = len(values), 0.0
            role = "identity" if (churn >= CHURN and card > 3) or card > HIGH_CARDINALITY else ("grouping" if card > 1 else "constant")
            fam.labels[canonical] = LabelInfo(rl, card, churn, role)
            if role == "constant" and len(values) == 1:
                fam.constants[canonical] = next(iter(values))
    return Schema(families, notes)
