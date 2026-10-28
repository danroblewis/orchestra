"""Other time-series stores, read where the data lives (docs/proposals/time-series-sources.md).

A **source** is where series live: ``own`` (the project's metrics store, ``own.py``) or a server
answering the Prometheus HTTP query API (``prometheus.py``: Prometheus, VictoriaMetrics, Thanos,
Mimir, Chronosphere). Orchestra reads other stores only through this package and never writes to
them (AGENTS.md rule 5). What a remote source offers is inferred from its schema (``schema.py``),
turned into views (``views.py``), passed through the repository's query script (``transform.py``),
ranked and capped (``rank.py``), and read for discovery's window and step through one catalogue
over the own store and every remote (``catalogue.py``).

Every source answers the same four reads, which the conformance suite (``tests/sources``) holds
each to."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

Labels = dict[str, str]
Points = list[tuple[float, float]]


class SourceError(Exception):
    """A source did not answer: unreachable, refused, unauthorized, or a query it rejected. The
    message names the server (scheme, host, port) and never a credential."""


class PastDeadline(SourceError):
    """A read stopped (between its requests) because the source's deadline had passed."""


@dataclass
class Health:
    ok: bool
    endpoints: dict[str, bool] = field(default_factory=dict)   # which of the API's endpoints answered
    build: dict[str, str] = field(default_factory=dict)        # the server's build info, when it says
    latency_ms: float | None = None
    error: str | None = None


class Source(Protocol):
    name: str

    def query_range(self, query: str, start: float, end: float, step: float,
                    until: float | None = None) -> list[tuple[Labels, Points]]:
        """``query`` evaluated at every step from ``start`` to ``end``: labels (without
        ``__name__``) and points per result series. NaN and ±Inf are dropped. Past ``until`` (a
        ``time.monotonic()``), no further request is made: ``PastDeadline``."""

    def select(self, selector: str, start: float, end: float, until: float | None = None) -> list[tuple[Labels, Points]]:
        """The raw samples of every series ``selector`` matches in [start, end], at their real
        times; labels include ``__name__``. ``until`` as for ``query_range``."""

    def series(self, match: list[str], start: float, end: float, limit: int = 0) -> list[Labels]:
        """The label sets (with ``__name__``) of the series matching any of ``match`` that have
        samples in [start, end]; at most ``limit`` when it is not 0."""

    def metadata(self, names: list[str] | None = None) -> dict[str, dict]:
        """Each metric's type, unit and help, where the store keeps them (of ``names`` only, when
        given); {} when it keeps none."""

    def health(self) -> Health: ...
