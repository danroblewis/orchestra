"""The project's own metrics store as a source: the same four reads as a remote, answered by the
PromQL subset (``metrics/promql.py``) over the store's dump of the project's series. Discovery
reads the own store's series as they are (``catalogue.py``); this is what lets one conformance
suite, and the preview, treat every source alike."""

from __future__ import annotations

import time

from ..metrics import MetricsStore, promql
from . import Health, Labels, Points, SourceError

OWN = "own"


class OwnSource:
    name = OWN

    def __init__(self, metrics: MetricsStore, project_key: str):
        self.metrics, self.project = metrics, project_key

    def dump(self) -> list[tuple[str, Labels, Points]]:
        return self.metrics.dump("", {"project": self.project})

    def query_range(self, query: str, start: float, end: float, step: float) -> list[tuple[Labels, Points]]:
        try:
            return [({k: v for k, v in lab.items() if k not in ("__name__", "project")}, pts)
                    for lab, pts in promql.query_range(self.dump(), query, start, end, step)]
        except promql.PromQLError as e:
            raise SourceError(f"own store: {e}") from None

    def select(self, selector: str, start: float, end: float) -> list[tuple[Labels, Points]]:
        try:
            return [({k: v for k, v in lab.items() if k != "project"}, pts)
                    for lab, pts in promql.select(self.dump(), selector, start, end)]
        except promql.PromQLError as e:
            raise SourceError(f"own store: {e}") from None

    def series(self, match: list[str], start: float, end: float, limit: int = 0) -> list[Labels]:
        seen: dict[tuple, Labels] = {}
        for m in match:
            for lab, _ in self.select(m, start, end):
                seen.setdefault(tuple(sorted(lab.items())), lab)
        out = sorted(seen.values(), key=lambda x: sorted(x.items()))
        return out[:limit] if limit else out

    def metadata(self) -> dict[str, dict]:
        return {}

    def health(self) -> Health:
        began = time.perf_counter()
        try:
            self.metrics.series("", {"project": self.project})
        except Exception as e:  # noqa: BLE001 - any backend failure is the source's health
            return Health(ok=False, error=f"{type(e).__name__}: {e}")
        return Health(ok=True, endpoints={"query_range": True, "query": True, "series": True},
                      latency_ms=round(1000 * (time.perf_counter() - began), 1))
