"""A family of a remote store's metrics, as inference reads it (``schema.py``): its metrics and
statistics, its labels and their roles, its recording rules, its reporting interval, and what its
samples said of it (``checks.py``)."""

from __future__ import annotations

from dataclasses import dataclass, field

UNREAD = ("timestamp", "clock", "info", "scrape")   # kinds read as neither a level nor a flow (an info metric's reporters are counted)

def esc(v: str) -> str:
    return v.replace("\\", "\\\\").replace('"', '\\"')


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
    kind: str                    # gauge | counter | rollup; or one of UNREAD: read as neither a level nor a flow (behaviour.py)
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
    retyped: str | None = None   # why its kind is not the one its type or name gives (behaviour.py)
    where: dict[str, str] = field(default_factory=dict)         # real label -> the one value read: the others repeat it (duplicates.py)
    notes: list[str] = field(default_factory=list)              # what was found about it: duplicates dropped, ...

    @property
    def stats(self) -> list[str]:
        return sorted(self.stat_values) if self.stat_label else sorted(s for s in self.metrics.values() if s)

    def selector(self, stat: str | None = None) -> str:
        """The selector for one statistic of this family (or its one metric), restricted to the
        one value of a label whose other values only repeat it (``where``)."""
        matchers = [f'{k}="{esc(v)}"' for k, v in sorted(self.where.items())]
        if self.stat_label and stat:
            matchers.insert(0, f'{self.stat_label}="{self.stat_values[stat]}"')
            metric = self.first_metric()
        else:
            metric = next(m for m, s in self.metrics.items() if s == stat) if stat else self.first_metric()
        return f"{metric}{{{','.join(matchers)}}}" if matchers else metric

    def first_metric(self) -> str:
        return next(iter(self.metrics))

    def role(self, role: str) -> list[str]:
        return [c for c, i in self.labels.items() if i.role == role]


@dataclass
class Schema:
    families: list[Family]
    notes: list[str] = field(default_factory=list)
