"""The metrics store: the history of every measured series. Stocks' current values are queries.

A series is a name plus labels, like Prometheus. Orchestra's series all start with ``orchestra_``
and carry a ``project`` label, so they never collide with anyone else's in a shared store.
Collectors (``orchestra.collectors``) write points; models and fitting read ranges.

Backends, chosen by ``[metrics] url`` in ``orchestra.toml`` or ``ORCHESTRA_METRICS_URL``:
``file`` (the default: ``<state>/metrics.jsonl``) and ``http://host:port`` (VictoriaMetrics, or
anything that speaks its JSON-lines import and the Prometheus query API).

Reading a range uses the last value at or before each step (a stock holds its level until the
next change), the same rule Prometheus-style stores use within their lookback window. The file
backend carries a value forward without limit; ask VictoriaMetrics for ranges with a step no
longer than its lookback (5 minutes by default, ``-search.maxStalenessInterval``) or query raw."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from ..config import Project


class MetricsError(Exception):
    pass


@dataclass(frozen=True)
class Point:
    series: str
    value: float
    ts: float                                   # unix seconds
    labels: dict[str, str] = field(default_factory=dict)

    def key(self) -> tuple:
        return (self.series, tuple(sorted(self.labels.items())))


class MetricsStore(Protocol):
    name: str

    def write(self, points: list[Point]) -> None: ...

    def raw(self, series: str, labels: dict[str, str] | None = None, start: float | None = None,
            end: float | None = None) -> list[tuple[float, float]]:
        """Every stored (ts, value) of the one series matching ``series`` and ``labels``, in time order."""

    def range(self, series: str, labels: dict[str, str] | None, start: float, end: float,
              step: float) -> list[tuple[float, float]]:
        """The series sampled every ``step`` seconds from ``start`` to ``end``: the last value at or
        before each step; steps before the first point are left out."""

    def latest(self, series: str, labels: dict[str, str] | None = None) -> tuple[float, float] | None: ...

    def series(self, prefix: str = "orchestra_") -> list[tuple[str, dict[str, str]]]: ...

    def dump(self, prefix: str = "orchestra_", labels: dict[str, str] | None = None
             ) -> list[tuple[str, dict[str, str], list[tuple[float, float]]]]:
        """Every series whose name starts with ``prefix`` (and matches ``labels``), with all its
        points in time order, in one pass: for catalogues and exploration."""

    def delete(self, series_prefix: str, labels: dict[str, str] | None = None) -> None:
        """Remove every series whose name starts with ``series_prefix`` (and matches ``labels``)."""

    def close(self) -> None: ...


def open_metrics(url: str | None, *, file_path: Path) -> MetricsStore:
    if not url or url == "file":
        from .file import FileMetrics
        return FileMetrics(file_path)
    if url.startswith(("http://", "https://")):
        from .victoria import VictoriaMetrics
        return VictoriaMetrics(url)
    raise MetricsError(f"unknown metrics URL {url!r}: use file or http://host:port (VictoriaMetrics)")


def for_project(project: Project) -> MetricsStore:
    url = os.environ.get("ORCHESTRA_METRICS_URL") or project.config.metrics_url
    return open_metrics(url, file_path=project.state_dir / "metrics.jsonl")


def step_sample(points: list[tuple[float, float]], start: float, end: float, step: float) -> list[tuple[float, float]]:
    """Last value at or before each step from start to end (points sorted by time)."""
    out: list[tuple[float, float]] = []
    i, last = 0, None
    t = start
    while t <= end + 1e-9:
        while i < len(points) and points[i][0] <= t:
            last = points[i][1]
            i += 1
        if last is not None:
            out.append((t, last))
        t += step
    return out
