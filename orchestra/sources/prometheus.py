"""A source that answers the Prometheus HTTP query API (Prometheus, VictoriaMetrics, Thanos, Mimir,
Chronosphere), over the standard library.

Reads only: ``query_range`` for evaluated queries (in chunks of fewer than ``max_points`` points
per series, joined), an instant ``query`` of ``selector[range]`` for raw samples at their real
times, ``label/__name__/values`` and ``series`` for the schema, ``metadata`` and
``status/buildinfo`` where the server keeps them. Queries go as POSTed forms, which every one of
these servers accepts, so long selectors do not hit URL limits. How each request is asked (auth,
rate, budget, retries, a busy store's refusals) is ``transport.py``.

A read the store refuses for its size (``TooBig``) is narrowed and the parts joined: a ``series``
listing by matcher, then by metric name; a refusal for its samples or points (not its series) by
halving the time range too, as a range query and a raw read are. A refusal for the **series** it
touches is halved by time only while that sheds series (churning pods): a half that touches
nearly the series the whole did is not halved again (``transport.time_helps``), so a stable metric
over the limit costs two refusals, not one per halving. A part still refused at
``MIN_SPAN`` is named in ``left_out`` (series) or raised (queries: the caller asks for less).

The checks are cheap whatever the tenant's size: ``health`` asks each endpoint about a name no
store has (an answer that touches no series), never all of ``up``; ``names`` always carries the
source's ``match[]`` and a ``limit`` (a source has no match-everything default: ``spec.py``).
**Nothing is asked of a store without naming what it is about:** ``metadata`` is asked metric by
metric (``metric=<name>``, one entry each by ``limit_per_metric``), of the names the listing found
under the source's ``match`` only, in sequence at the store's rate and within the round's budget
(at most ``METADATA_NAMES``, and ``METADATA_SHARE`` of the requests the round has left); the names
past that are kept in ``unasked`` (described "metadata not asked (budget)"), never asked by a
listing of the store's whole metadata. ``names``, ``label_names``/``label_values`` and ``series`` refuse a
request with no ``match[]``, or one whose every ``match[]`` selects everything.

Every request is **within the source's ``match``** (``scope.py``): its ``query`` and each of its
``match[]`` selectors carry the label matchers every ``match`` selector has, so a shared store is
never read beyond the project's part of it.

A **native histogram** (``histogram``/``histograms`` in an answer, Prometheus 2.40+) is read as
its count, a counter; the names seen so are kept in ``native``, so inference reads them with
``histogram_count`` rather than as a gauge."""

from __future__ import annotations

import math
import re
import time

from . import Health, Labels, PastDeadline, Points, SourceError
from .limits import OverBudget, RateLimit
from .scope import scope_of, scoped
from .spec import SourceSpec
from .spec import everything as names_nothing
from .transport import (
    RETRIES,
    RETRY,
    SameOriginRedirects,
    TooBig,
    Transport,
    retry_after,
    time_helps,
)

__all__ = ["RETRIES", "RETRY", "PastDeadline", "PrometheusSource", "SameOriginRedirects", "TooBig", "retry_after"]

PROBE_NAME = "orchestra_probe_no_such_metric"     # a name no store has: an endpoint answers it at no cost
ENDPOINTS = {"query_range": ("/api/v1/query_range", {"query": PROBE_NAME, "start": "0", "end": "60", "step": "60"}),
             "query": ("/api/v1/query", {"query": PROBE_NAME}),
             "series": ("/api/v1/series", {"match[]": PROBE_NAME, "start": "0", "end": "60", "limit": "1"}),
             "labels": ("/api/v1/labels", {"match[]": PROBE_NAME, "limit": "1"}),
             "metadata": ("/api/v1/metadata", {"metric": PROBE_NAME, "limit": "1"}),
             "buildinfo": ("/api/v1/status/buildinfo", None)}
LABEL_NAME = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")
MIN_SPAN = 600.0                     # the shortest time range a refused read is split down to
METADATA_NAMES = 200                 # names one round asks metadata of, at most: one request each
METADATA_SHARE = 0.25                # of the requests the round has left, at most, spent on metadata
NAMES_LIMIT = 2001                   # names one name listing asks for at most, when its caller gives none


def _named(path: str, match: list[str]) -> None:
    """Refuses a listing that names nothing: no ``match[]``, or only selectors that select everything."""
    if not match or all(names_nothing(m) for m in match):
        raise SourceError(f"{path} is never asked with no match[] naming what it is about (it would list the whole store): "
                          "give a selector, or set match on the [[sources]] entry")


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
        self.unasked: list[str] = []     # names the last metadata call left unasked (its budget)
        self.scope = scope_of(spec.match)  # the label matchers every request carries (scope.py)

    def _call(self, path: str, form: dict | None = None, **kw):
        """Every request within the source's ``match`` (``scope.py``): its query, or each of its
        ``match[]`` selectors, scoped before it is sent."""
        if form and self.scope:
            form = dict(form)
            if isinstance(form.get("query"), str):
                form["query"] = scoped(form["query"], self.scope)
            if "match[]" in form:
                ms = form["match[]"]
                form["match[]"] = [scoped(m, self.scope) for m in ms] if isinstance(ms, list) else scoped(ms, self.scope)
        return super()._call(path, form, **kw)

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
        before: TooBig | None = None
        while t <= end:
            self._in_time(until)                    # between chunks: a long read stops once the deadline passed
            hi = min(end, t + span)
            try:
                res = self._results("/api/v1/query_range", {"query": query, "start": f"{t:.3f}", "end": f"{hi:.3f}", "step": f"{step:g}"}, until)
            except TooBig as e:
                if not narrow or not time_helps(e, before) or hi - t <= max(MIN_SPAN, step):
                    raise
                before = e
                span = max(MIN_SPAN, step, (hi - t) / 2)    # fewer series touched in a shorter range: ask for less, then go on
                self.narrowed += 1
                continue
            before = None
            for r in res:
                labels = {k: v for k, v in (r.get("metric") or {}).items() if names or k != "__name__"}
                g = merged.setdefault(tuple(sorted(labels.items())), (labels, {}))
                g[1].update(_points(_samples(r)))
            t = hi + step
        out = [(labels, sorted(pts.items())) for labels, pts in merged.values()]
        self.points += sum(len(p) for _, p in out)
        return out

    def select(self, selector: str, start: float, end: float, until: float | None = None,
               _before: TooBig | None = None) -> list[tuple[Labels, Points]]:
        self._in_time(until)
        try:
            res = self._results("/api/v1/query", {"query": f"{selector}[{_dur(end - start)}]", "time": f"{end:.3f}"}, until)
        except TooBig as e:
            if not time_helps(e, _before) or end - start <= MIN_SPAN:
                raise
            self.narrowed += 1
            mid = (start + end) / 2
            joined: dict[tuple, tuple[Labels, dict[float, float]]] = {}
            for labels, pts in self.select(selector, start, mid, until, e) + self.select(selector, mid, end, until, e):
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
        _named("/api/v1/series", match)
        form = {"match[]": list(match), "start": f"{start:.3f}", "end": f"{end:.3f}"}
        if limit:
            form["limit"] = str(limit)
        data = self._call("/api/v1/series", form)
        if not isinstance(data, list) or not all(isinstance(x, dict) for x in data):
            raise SourceError(f"{self.spec.where()}/api/v1/series: not a Prometheus answer")
        return [dict(x) for x in data]

    def names(self, match: list[str], start: float, end: float, limit: int = 0) -> list[str]:
        """The metric names that ``match`` selects in [start, end] (``label/__name__/values``), at
        most ``limit`` (``NAMES_LIMIT`` when none is given); refused when ``match`` names nothing."""
        _named("/api/v1/label/__name__/values", match)
        form: dict = {"start": f"{start:.3f}", "end": f"{end:.3f}", "match[]": list(match), "limit": str(limit or NAMES_LIMIT)}
        data = self._call("/api/v1/label/__name__/values", form, post=False)
        if not isinstance(data, list):
            raise SourceError(f"{self.spec.where()}/api/v1/label/__name__/values: not a Prometheus answer")
        return [str(x) for x in data]

    def instant(self, query: str, at: float, until: float | None = None) -> list[tuple[Labels, Points]]:
        """``query`` evaluated at ``at``: labels (with ``__name__``) and the point(s) of each result
        (a range selector's raw samples; a scalar as one unlabelled point)."""
        data = self._call("/api/v1/query", {"query": query, "time": f"{at:.3f}"}, until=until)
        kind, res = (data.get("resultType"), data.get("result")) if isinstance(data, dict) else (None, None)
        if kind == "scalar" and isinstance(res, list):
            return [({}, _points([res]))]
        if not isinstance(res, list) or not all(isinstance(r, dict) for r in res):
            raise SourceError(f"{self.spec.where()}/api/v1/query: not a Prometheus answer")
        return [(dict(r.get("metric") or {}), _points([r["value"]] if "value" in r else _samples(r))) for r in res]

    def label_names(self, match: list[str], start: float, end: float, limit: int) -> list[str]:
        """``/api/v1/labels`` within ``match`` (a selector naming something: never none) over [start, end],
        at most ``limit``."""
        return self._strings("/api/v1/labels", match, start, end, limit)

    def label_values(self, label: str, match: list[str], start: float, end: float, limit: int) -> list[str]:
        """``/api/v1/label/<label>/values`` within ``match`` (a selector naming something: never none) over
        [start, end], at most ``limit``."""
        if not LABEL_NAME.match(label):
            raise SourceError(f"{label!r} is not a label name")
        return self._strings(f"/api/v1/label/{label}/values", match, start, end, limit)

    def _strings(self, path: str, match: list[str], start: float, end: float, limit: int) -> list[str]:
        _named(path, match)
        form: dict = {"start": f"{start:.3f}", "end": f"{end:.3f}", "limit": str(max(1, limit)), "match[]": list(match)}
        data = self._call(path, form, post=False)
        if not isinstance(data, list):
            raise SourceError(f"{self.spec.where()}{path}: not a Prometheus answer")
        return [str(x) for x in data][: max(1, limit)]

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

    def _by_time(self, m: str, start: float, end: float, limit: int, before: TooBig | None = None) -> list[Labels]:
        try:
            return self._series([m], start, end, limit)
        except TooBig as e:
            if not time_helps(e, before) or end - start <= MIN_SPAN:
                raise
            before = e
        mid = (start + end) / 2
        return self._by_time(m, start, mid, limit, before) + self._by_time(m, mid, end, limit, before)

    def metadata(self, names: list[str] | None = None) -> dict[str, dict]:
        """Each of ``names``' type, unit and help (one entry per metric), asked metric by metric
        (``metric=<name>``), in sequence; no names, nothing asked (never the store's whole list).
        At most ``METADATA_NAMES``, and ``METADATA_SHARE`` of what the round's budget has left; the
        names past that, or past the budget, are in ``unasked``. A store that refuses metadata
        (Chronosphere has none) is not asked again this call: none kept."""
        want = sorted(set(names or []))
        room = METADATA_NAMES
        if self.budget is not None and self.budget.requests is not None:
            room = min(room, max(0, int((self.budget.requests - self.budget.used) * METADATA_SHARE)))
        self.unasked = want[room:]
        out: dict[str, dict] = {}
        for i, name in enumerate(want[:room]):
            try:
                data = self._call("/api/v1/metadata", {"metric": name, "limit_per_metric": "1"}, post=False) or {}
            except OverBudget:
                self.unasked = want[i:]
                return out
            except SourceError:
                return out
            if not isinstance(data, dict):                  # metadata is optional: a store answering it oddly keeps none
                return out
            entries = data.get(name)
            if isinstance(entries, list) and entries and isinstance(entries[0], dict):
                out[name] = dict(entries[0])
        return out

    def health(self) -> Health:
        began, ok, err = time.perf_counter(), {}, None
        build: dict = {}
        for what, (path, form) in ENDPOINTS.items():
            try:
                data = self._call(path, form, post=form is not None and what not in ("labels", "metadata"))
                ok[what] = True
                if what == "buildinfo" and isinstance(data, dict):
                    build = {k: str(v) for k, v in data.items() if k in ("version", "revision", "branch", "goVersion")}
            except SourceError as e:
                ok[what] = False
                if what in ("query_range", "query", "series") and err is None:
                    err = str(e)
        return Health(ok=all(ok.get(k) for k in ("query_range", "query", "series")), endpoints=ok, build=build,
                      latency_ms=round(1000 * (time.perf_counter() - began) / len(ENDPOINTS), 1), error=err)
