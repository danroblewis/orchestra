"""Candidate series for each family: the aggregations that are right for what it measures, and
counts, which switch its type.

| Family | Views |
|---|---|
| a per-pod statistic (max, min, avg, p50, p95, p99) | ``max by (G)`` of max; ``min by (G)`` of min; ``avg by (G)`` of avg (unweighted, flagged); ``max by (G)`` of p90/p95/p99 (an upper bound, flagged); never a sum, never an average of quantiles |
| a gauge with no statistic | an intensive one (latency, ratio, utilisation) ``max`` and ``avg by (G)``; any other ``sum by (G)`` |
| a counter | increments by G: ``sum by (G) (increase(x[S]))`` on discovery's grid, read server-side (``fetch.py``) |
| a native histogram | its count, a counter: ``histogram_count`` of the same (its ``_sum`` is not read, as for a classic one) |
| a recording rule ``…:fn`` | ``fn by (G)`` of it (a sum of sums, a max of maxes; a sum of rates), as a rate when its name says rate, read with its own interval's lookback; in its base's family, it replaces the base's own view of that function; ``level:metric:fn`` is named by its full name, so it never takes an exporter's own ``metric_fn``. A rule over a counter (a rate, a sum) counts the same events as the counter: the counter is read, the rule left out and says why (only a ``count`` rule, of reporters, is read beside it) |
| a timestamp, a clock, an info metric or a scrape's own series (``schema.UNREAD``) | none but an info metric's count of reporters: a sum of them means nothing |
| any family with an identity label | ``count by (G)`` of one statistic: the pods reporting, a level; and its turnover, the pods that started and stopped reporting, as two counters that balance it exactly |
| any family | how many values of each grouping label report: ``count(count by (L) (…))`` |

A count is made from one family per thing counted (the gauges' before a counter's), so the pods of
``search`` are counted once, not once per metric they report.

``G`` is every grouping set: none, each grouping label, and each pair whose values multiply to at
most ``PAIR_LIMIT``. Constant labels the source names (in ``[sources.labels]`` or as its
``machine``) ride along in every grouping, so "pods of authz" keeps ``service="authz"``; so does a
**unit label** (``schema.py``: ``unit``, ``resource``, or one whose values are units), in every
view, so CPU cores are never added to memory bytes. Levels are read with ``last_over_time(…[R])``,
R the larger of two and a half reporting intervals and one interval plus 30 s (``lookback``): one
missed or late scrape never drops a series from a sum, and a pod that stops reporting drops out
within a minute or so rather than lingering for the server's lookback.

Each generated definition also says how it is read (``inner``, ``agg``, ``agg_labels``), so the
views of a family that differ only by grouping are read once at the finest of them and
aggregated again exactly (``regroup.py``, ``plan.py``).

Every definition says what it merges: the grouping labels of its family it aggregates over, with
how many values each has (``merged``, and a flag), so a total over three queues says so."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from itertools import combinations
from math import prod

from .family import lookback
from .schema import INTENSIVE, UNREAD, Family
from .spec import SourceSpec

UPPER = {"p90", "p95", "p99", "p999"}
PAIR_LIMIT = 60
WEIGHT = {"count": 1.0, "starts": 1.0, "stops": 1.0, "increments": 1.0, "declared": 1.0, "script": 1.0, "sum_by": 1.0, "rollup": 0.9,
          "upper_by": 0.5, "max_by": 0.5, "distinct": 0.4, "avg_by": 0.4, "min_by": 0.3}


@dataclass
class Definition:
    """One series (or one family of result series) a source is asked for: from a view of a
    family, a query script, or a hand-written ``[[series]]``."""

    id: str
    source: str
    name: str                    # without the source's prefix
    family: str
    view: str                    # a key of WEIGHT
    kind: str                    # level | counter | rate
    query: str                   # PromQL; for "increments", the selector whose raw samples are read
    group_by: list[str] = field(default_factory=list)    # canonical labels the results keep
    by_real: list[str] = field(default_factory=list)     # ... as the store spells them
    rename: dict[str, str] = field(default_factory=dict)  # real -> canonical, applied to results
    stat: str | None = None
    unit: str | None = None
    resolution_s: float | None = None
    est_series: int = 1
    flags: list[str] = field(default_factory=list)
    origin: list[str] = field(default_factory=list)
    labels_info: dict = field(default_factory=dict)      # canonical -> {real, cardinality, churn}, for the script
    extra_labels: dict[str, str] = field(default_factory=dict)
    pin: bool = False
    score: float = 0.0
    why: str = ""
    counts: str = ""             # for a count and its turnover: what is counted, so one family counts it
    traffic: dict = field(default_factory=dict)          # counted traffic, when a definition says so (traffic.py)
    merged: dict[str, int] = field(default_factory=dict)  # grouping labels of its family it aggregates over -> how many values
    inner: str = ""              # the expression its aggregation is over, when generated (regroup.py); "" for a query as written
    agg: str = ""                # sum | count | max | min | avg | distinct | increase (a counter's increments)
    agg_labels: list[str] = field(default_factory=list)  # distinct: the labels whose values are counted
    touched: int = 0             # series its selector touches, from the listing (to size batched reads)
    unit_label: str | None = None  # the label that names each series' unit, when the family has one
    counter_form: str = ""       # "native": a native histogram, read by its count; "delta": each sample a count (family.py)
    left: str = ""               # left out before ranking, and why (a rule over a counter: the counter is read)
    stock: dict = field(default_factory=dict)            # a declared stock's level or flow ({"name", "role"}; spec.DeclaredSeries)


count_window = lookback


def _by(fn: str, by_real: list[str], inner: str) -> str:
    return f"{fn} by ({', '.join(by_real)}) ({inner})" if by_real else f"{fn}({inner})"


def _slug(s: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_]+", "_", s).strip("_").lower()


def groupings(fam: Family) -> list[list[str]]:
    """Every grouping set, coarsest first."""
    g = sorted(fam.role("grouping"), key=lambda c: fam.labels[c].cardinality)
    out: list[list[str]] = [[]] + [[c] for c in g]
    out += [list(p) for p in combinations(g, 2) if prod(fam.labels[c].cardinality for c in p) <= PAIR_LIMIT]
    return out


def views(fam: Family, spec: SourceSpec) -> list[Definition]:
    plain = [c for c in fam.role("constant") if c in spec.labels or c == spec.machine]   # kept by every view but a count
    identity = fam.role("identity")
    rename = {fam.labels[c].real: c for c in fam.labels}
    info = {c: {"real": i.real, "cardinality": i.cardinality, "churn": i.churn, "role": i.role} for c, i in fam.labels.items()}
    r = f"{lookback(fam.resolution_s)}s"
    out: list[Definition] = []
    units = fam.role("unit")
    kept = plain + [c for c in units if c not in plain]        # a unit label too: never summed across
    unit_label = fam.labels[units[0]].real if units else None
    touched = max(1, fam.series * max(1, len(fam.metrics)))

    grouping = {c: fam.labels[c].cardinality for c in fam.role("grouping")}
    noted = [f"{fam.name}: {fam.retyped}"] if fam.retyped else []

    def add(name: str, view: str, kind: str, query: str, group: list[str], *, stat=None, unit=None, flags=(), origin="", counts="",
            constants: bool = True, resolution_s: float | None = None, inner: str = "", agg: str = "", agg_labels=(), left: str = ""):
        counted = view in ("count", "starts", "stops", "distinct")     # reporters are counted once, whatever the unit
        canon = (plain if counted else kept if constants else [c for c in kept if c in units]) + group
        merged = {c: n for c, n in grouping.items() if c not in group}
        said = [f"merges {', '.join(f'{c} ({n} values)' for c, n in merged.items())}"] if merged and view != "distinct" else []
        out.append(Definition(counts=counts,
            id="", source=spec.name, name=_slug(name), family=fam.name, view=view, kind=kind, query=query,
            group_by=canon, by_real=[fam.labels[c].real for c in canon], rename=rename, stat=stat,
            unit=unit or fam.unit, resolution_s=resolution_s or fam.resolution_s,
            est_series=prod(fam.labels[c].cardinality for c in group) if group else 1, flags=list(flags) + said,
            origin=[f"inferred from {fam.name}: {origin}", *noted, *fam.notes], labels_info=info,
            merged=merged if view != "distinct" else {}, inner=inner, agg=agg, agg_labels=list(agg_labels), touched=touched,
            unit_label=unit_label if view not in ("count", "starts", "stops", "distinct") else None, counter_form=fam.counter_form, left=left))

    rules = fam.rollups or ({fam.rollup["fn"]: {**fam.rollup, "metric": fam.name, "resolution_s": fam.resolution_s}} if fam.rollup else {})
    covered = set(rules)                            # the base's own views of these functions give way to the rules

    def rule_view(fn: str, rule: dict, by: list[str], group: list[str], gtext: str, constants: bool = True) -> None:
        outer = {"count": "sum", "avg": "avg", "rate": "sum"}.get(fn, fn)
        left = (f"the same events as its counter {fam.name}, which is read instead: a rule over a counter and the counter are one flow"
                if fam.kind == "counter" and fn != "count" else "")
        flags = ["an unweighted average of the rule's averages"] if fn == "avg" else []
        if rule["rate"] and "increase" in rule["metric"].rpartition(":")[2]:
            flags.append("an increase over the rule's window read as a per-second rate: its size is off by that window")
        res = rule.get("resolution_s") or fam.resolution_s       # a rule's own interval: it is evaluated on its own clock
        name = rule["metric"] if rule.get("level") else f"{rule['of']}_{fn}"    # level:metric:fn by its full name, never the base's own name
        inner = f"last_over_time({rule['metric']}[{lookback(res)}s])"
        add(name, "rollup", "rate" if rule["rate"] else "level", _by(outer, by, inner),
            group, flags=flags, origin=f"a recording rule ({rule['metric']}), {fn} of {rule['of']}; {outer}{gtext}", constants=constants,
            resolution_s=res, inner=inner, agg=outer, left=left)

    served: set[str] = set()
    for group in groupings(fam):
        by = [fam.labels[c].real for c in kept + group]
        gtext = f" by {', '.join(group)}" if group else ""
        for fn, rule in sorted(rules.items()):
            if "labels" in rule and not set(by) <= set(rule["labels"]):
                continue                            # the rule keeps fewer labels than this grouping needs
            rule_view(fn, rule, by, group, gtext)
            served.add(fn)
        if fam.kind == "rollup" or fam.kind in UNREAD:
            pass                                    # rules only: their views are the rules'; the others are no level and no flow
        elif fam.kind == "counter":
            add(fam.name, "increments", "counter", fam.selector(), group, inner=fam.selector(), agg="increase",
                origin=f"increments{gtext}" + {"native": ", of a native histogram's count", "delta": ", each sample a count (delta temporality)"}.get(fam.counter_form, ""))
        elif fam.stats:
            for stat in fam.stats:
                sel = f"last_over_time({fam.selector(stat)}[{r}])"
                if stat in covered:
                    continue
                if stat in ("max", "min"):
                    add(f"{fam.name}_{stat}", f"{stat}_by", "level", _by(stat, by, sel), group, stat=stat, origin=f"{stat} of {stat}{gtext}",
                        inner=sel, agg=stat)
                elif stat == "avg":
                    add(f"{fam.name}_avg", "avg_by", "level", _by("avg", by, sel), group, stat=stat, inner=sel, agg="avg",
                        flags=["an unweighted average of each reporter's average"] if identity else [], origin=f"avg of avg{gtext}")
                elif stat in UPPER:
                    add(f"{fam.name}_{stat}_max", "upper_by", "level", _by("max", by, sel), group, stat=stat, inner=sel, agg="max",
                        flags=[f"an upper bound: the largest {identity[0] if identity else 'series'}'s {stat}, not the {stat} of all"],
                        origin=f"max of {stat}{gtext}")
        elif INTENSIVE.search(fam.name):
            sel = f"last_over_time({fam.selector()}[{r}])"
            if "max" not in covered:
                add(f"{fam.name}_max", "max_by", "level", _by("max", by, sel), group, origin=f"max{gtext}", inner=sel, agg="max")
            if "avg" not in covered:
                add(f"{fam.name}_avg", "avg_by", "level", _by("avg", by, sel), group, inner=sel, agg="avg",
                    flags=["an unweighted average"] if identity else [], origin=f"avg{gtext}")
        elif "sum" not in covered:
            sel = f"last_over_time({fam.selector()}[{r}])"
            add(fam.name, "sum_by", "level", _by("sum", by, sel), group, origin=f"sum{gtext}", inner=sel, agg="sum")
        if identity and fam.kind not in ("rollup", "timestamp", "clock", "scrape"):
            stat = "p50" if "p50" in fam.stats else (fam.stats[0] if fam.stats else None)
            who, base = next((c for c in spec.identity if c in identity), identity[0]), fam.name.removesuffix("_total")
            thing = "|".join([who, *(f"{c}={fam.constants.get(c, '?')}" for c in plain), *group])
            sel = f"last_over_time({fam.selector(stat)}[{r}])"
            by_n = [fam.labels[c].real for c in plain + group]
            add(f"{base}_{who}s", "count", "level", _by("count", by_n, sel), group, inner=sel, agg="count",
                stat=stat, unit=f"{who}s", origin=f"{who}s reporting{gtext}, counted from {fam.name}", counts=thing)
            for view, verb in (("starts", "started"), ("stops", "stopped")):
                add(f"{base}_{who}s_{verb}_total", view, "counter", fam.selector(stat), group, stat=stat, unit=f"{who}s",
                    origin=f"{who}s that {verb} reporting{gtext}, from {fam.name}'s raw samples", counts=thing)
    for fn, rule in sorted(rules.items()):
        if fn not in served:                        # a rule at another level (job:…) than any grouping of its base: its total
            rule_view(fn, rule, [], [], "", constants=False)
    kept_real = [fam.labels[c].real for c in plain]
    for c in fam.role("grouping") if fam.kind not in ("timestamp", "clock", "scrape") else []:
        sel = f"last_over_time({fam.selector(fam.stats[0] if fam.stats else None)}[{r}])"
        inner = _by("count", [fam.labels[c].real, *kept_real], sel)
        add(f"{fam.name.removesuffix('_total')}_{c}s", "distinct", "level", _by("count", kept_real, inner), [], inner=sel, agg="distinct",
            agg_labels=[fam.labels[c].real],
            unit=f"{c}s", origin=f"how many {c} values report", counts="|".join([c, *(f"{k}={fam.constants.get(k, '?')}" for k in plain)]))
    return out


def one_count_per_thing(defs: list[Definition], families: list[Family]) -> list[Definition]:
    """Counts (and their turnover) of the same thing from one family only: a family with
    statistics before a plain gauge, a gauge before a counter, then by name."""
    rank = {f.name: (0 if f.stats else 1 if f.kind == "gauge" else 2, f.name) for f in families}
    best: dict[str, tuple] = {}
    for d in defs:
        if d.counts:
            r = rank.get(d.family, (3, d.family))
            best[d.counts] = min(best.get(d.counts, r), r)
    return [d for d in defs if not d.counts or rank.get(d.family, (3, d.family)) == best[d.counts]]
