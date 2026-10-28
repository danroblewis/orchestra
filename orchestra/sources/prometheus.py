"""A source that answers the Prometheus HTTP query API (Prometheus, VictoriaMetrics, Thanos, Mimir,
Chronosphere), over the standard library.

Reads only: ``query_range`` for evaluated queries (in chunks of fewer than ``max_points`` points
per series, joined), an instant ``query`` of ``selector[range]`` for raw samples at their real
times, ``label/__name__/values`` and ``series`` for the schema, ``metadata`` and
``status/buildinfo`` where the server keeps them. Queries go as POSTed forms, which every one of
these servers accepts, so long selectors do not hit URL limits. How each request is asked (auth,
rate, budget, retries, a busy store's refusals) is ``transport.py``.

A read the store refuses for its size (``TooBig``: a per-query series limit) is narrowed and the
parts joined: a ``series`` listing by matcher, then by metric name, then by halving the time
range; a range query and a raw read by halving their time range. A part still refused at
``MIN_SPAN`` is named in ``left_out`` (series) or raised (queries: the caller asks for less).

A **native histogram** (``histogram``/``histograms`` in an answer, Prometheus 2.40+) is read as
its count, a counter; the names seen so are kept in ``native``, so inference reads them with
``histogram_count`` rather than as a gauge."""

from __future__ import annotations

import math
import time

from . import Health, Labels, PastDeadline, Points, SourceError
from .limits import RateLimit
from .spec import SourceSpec
from .transport import RETRIES, RETRY, SameOriginRedirects, TooBig, Transport, retry_after

__all__ = ["RETRIES", "RETRY", "PastDeadline", "PrometheusSource", "SameOriginRedirects", "TooBig", "retry_after"]

ENDPOINTS = {"query_range": ("/api/v1/query_range", {"query": "up", "start": "0", "end": "60", "step": "60"}),
             "query": ("/api/v1/query", {"query": "up"}),
             "series": ("/api/v1/series", {"match[]": "up", "start": "0", "end": "60"}),
             "labels": ("/api/v1/labels", None),
             "metadata": ("/api/v1/metadata", None),
             "buildinfo": ("/api/v1/status/buildinfo", None)}
MIN_SPAN = 600.0                     # the shortest time range a refused read is split down to


def _with_name(selector: str, name: str) -> str | None:
    """``selector`` narrowed to one metric name: ``{a="b"}`` becomes ``{__name__="n",a="b"}``; None
    when the selector names its metric already (it cannot be split by name)."""
    s = selector.strip()
    if not s.startswith("{"):
        return None
    inner = s[1:].lstrip()
    esc = name.replace("\\", "\\\\").replace('"', '\\"')
    return '{__name__="' + esc + '"' + ("," + inner if not inner.startswith("}") else "}")


def _points(values: list) -> Points:
    out = []
    for t, v in values:
        if isinstance(v, dict):                 # a native histogram's sample: its count
            v = v.get("count")
        try:
            x = float(v)
        except (TypeError, ValueError):
            continue
        if math.isfinite(x):                    # staleness NaNs and ±Inf are dropped
            out.append((float(t), x))
    return out


def _samples(r: dict) -> list:
    """A result's samples: floats, or a native histogram's (``histograms``)."""
    return list(r.get("values") or []) + list(r.get("histograms") or [])


def _dur(seconds: float) -> str:
    return f"{max(1, math.ceil(seconds))}s"


class PrometheusSource(Transport):
    def __init__(self, spec: SourceSpec, limiter: RateLimit | None = None):
        super().__init__(spec, limiter)
        self.left_out: list[str] = []    # parts of a series listing still refused at MIN_SPAN
        self.native: set[str] = set()    # metric names answered as native histograms

    def _results(self, path: str, form: dict, until: float | None = None) -> list[dict]:
        """The ``result`` list of a query's answer; ``SourceError`` when the answer has another shape."""
        data = self._call(path, form, until=until)
        res = data.get("result") if isinstance(data, dict) else None
        if not isinstance(res, list) or not all(isinstance(r, dict) for r in res):
            raise SourceError(f"{self.spec.where()}{path}: not a Prometheus answer")
        for r in res:
            if r.get("histograms") and (r.get("metric") or {}).get("__name__"):
                self.native.add(r["metric"]["__name__"])
        return res

    def query_range(self, query: str, start: float, end: float, step: float,
                    until: float | None = None, *, names: bool = False, narrow: bool = True) -> list[tuple[Labels, Points]]:
        """``narrow``: a read refused for its size is asked again over halves of its time range
        (False: ``TooBig`` is raised, for a caller that asks for fewer series instead)."""
        span = (self.spec.max_points - 1) * step
        merged: dict[tuple, tuple[Labels, dict[float, float]]] = {}
        t = start
        while t <= end:
            self._in_time(until)                    # between chunks: a long read stops once the deadline passed
            hi = min(end, t + span)
            try:
                res = self._results("/api/v1/query_range", {"query": query, "start": f"{t:.3f}", "end": f"{hi:.3f}", "step": f"{step:g}"}, until)
            except TooBig:
                if not narrow or hi - t <= max(MIN_SPAN, step):
                    raise
                span = max(MIN_SPAN, step, (hi - t) / 2)    # fewer series touched in a shorter range: ask for less, then go on
                self.narrowed += 1
                continue
            for r in res:
                labels = {k: v for k, v in (r.get("metric") or {}).items() if names or k != "__name__"}
                g = merged.setdefault(tuple(sorted(labels.items())), (labels, {}))
                g[1].update(_points(_samples(r)))
            t = hi + step
        out = [(labels, sorted(pts.items())) for labels, pts in merged.values()]
        self.points += sum(len(p) for _, p in out)
        return out

    def select(self, selector: str, start: float, end: float, until: float | None = None) -> list[tuple[Labels, Points]]:
        self._in_time(until)
        try:
            res = self._results("/api/v1/query", {"query": f"{selector}[{_dur(end - start)}]", "time": f"{end:.3f}"}, until)
        except TooBig:
            if end - start <= MIN_SPAN:
                raise
            self.narrowed += 1
            mid = (start + end) / 2
            joined: dict[tuple, tuple[Labels, dict[float, float]]] = {}
            for labels, pts in self.select(selector, start, mid, until) + self.select(selector, mid, end, until):
                g = joined.setdefault(tuple(sorted(labels.items())), (labels, {}))
                g[1].update(pts)
            return [(labels, sorted(pts.items())) for labels, pts in joined.values()]
        out = []
        for r in res:
            pts = [(t, v) for t, v in _points(_samples(r)) if start <= t <= end]
            if pts:
                out.append((dict(r.get("metric") or {}), pts))
        self.points += sum(len(p) for _, p in out)
        return out

    def _series(self, match: list[str], start: float, end: float, limit: int) -> list[Labels]:
        form = {"match[]": list(match), "start": f"{start:.3f}", "end": f"{end:.3f}"}
        if limit:
            form["limit"] = str(limit)
        data = self._call("/api/v1/series", form)
        if not isinstance(data, list) or not all(isinstance(x, dict) for x in data):
            raise SourceError(f"{self.spec.where()}/api/v1/series: not a Prometheus answer")
        return [dict(x) for x in data]

    def names(self, match: list[str], start: float, end: float) -> list[str]:
        """The metric names that ``match`` selects in [start, end] (``label/__name__/values``)."""
        form = {"match[]": list(match), "start": f"{start:.3f}", "end": f"{end:.3f}"}
        data = self._call("/api/v1/label/__name__/values", form, post=False)
        if not isinstance(data, list):
            raise SourceError(f"{self.spec.where()}/api/v1/label/__name__/values: not a Prometheus answer")
        return [str(x) for x in data]

    def series(self, match: list[str], start: float, end: float, limit: int = 0, *, narrow: bool = True) -> list[Labels]:
        """``narrow``: a listing refused for its size is split by matcher, name and time (False:
        ``TooBig`` is raised, for a caller that splits it its own way)."""
        self.left_out = []
        try:
            return self._series(match, start, end, limit)[: limit or None]
        except TooBig:
            if not narrow:
                raise
        self.narrowed += 1
        seen: dict[tuple, Labels] = {}
        for m in match:
            for labels in self._split_series(m, start, end, limit):
                seen.setdefault(tuple(sorted(labels.items())), labels)
                if limit and len(seen) >= limit:
                    return list(seen.values())
        return list(seen.values())

    def _split_series(self, m: str, start: float, end: float, limit: int) -> list[Labels]:
        """One matcher's series, narrowed until the store answers: by metric name, then each name
        by halves of the time range down to ``MIN_SPAN``; a part refused even then is named once
        in ``left_out``."""
        try:
            return self._series([m], start, end, limit)
        except TooBig:
            pass
        try:
            names = self.names([m], start, end)
        except SourceError:
            names = []
        parts = [p for p in (_with_name(m, n) for n in names) if p] if len(names) > 1 else []
        out: list[Labels] = []
        for part in parts or [m]:
            try:
                out += self._by_time(part, start, end, limit)
            except TooBig as e:
                self.left_out.append(f"{part}: {e}")
        return out

    def _by_time(self, m: str, start: float, end: float, limit: int) -> list[Labels]:
        try:
            return self._series([m], start, end, limit)
        except TooBig:
            if end - start <= MIN_SPAN:
                raise
        mid = (start + end) / 2
        return self._by_time(m, start, mid, limit) + self._by_time(m, mid, end, limit)

    def metadata(self) -> dict[str, dict]:
        try:
            data = self._call("/api/v1/metadata", None, post=False) or {}
        except SourceError:
            return {}
        if not isinstance(data, dict):                  # metadata is optional: a store answering it oddly keeps none
            return {}
        return {name: dict(entries[0]) for name, entries in data.items() if isinstance(entries, list) and entries
                and isinstance(entries[0], dict)}

    def health(self) -> Health:
        began, ok, err = time.perf_counter(), {}, None
        build: dict = {}
        for what, (path, form) in ENDPOINTS.items():
            try:
                data = self._call(path, form, post=form is not None and what != "labels")
                ok[what] = True
                if what == "buildinfo" and isinstance(data, dict):
                    build = {k: str(v) for k, v in data.items() if k in ("version", "revision", "branch", "goVersion")}
            except SourceError as e:
                ok[what] = False
                if what in ("query_range", "query", "series") and err is None:
                    err = str(e)
        return Health(ok=all(ok.get(k) for k in ("query_range", "query", "series")), endpoints=ok, build=build,
                      latency_ms=round(1000 * (time.perf_counter() - began) / len(ENDPOINTS), 1), error=err)
