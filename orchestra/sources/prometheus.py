"""A source that answers the Prometheus HTTP query API (Prometheus, VictoriaMetrics, Thanos, Mimir,
Chronosphere), over the standard library.

Reads only: ``query_range`` for evaluated queries (in chunks of fewer than ``max_points`` points
per series, joined), an instant ``query`` of ``selector[range]`` for raw samples at their real
times, ``series`` for the schema, ``metadata`` and ``status/buildinfo`` where the server keeps
them. Every request carries the source's auth (``auth.py``) and its timeout; a failure raises
``SourceError`` naming the server and what it said, never a credential. Queries go as POSTed
forms, which every one of these servers accepts, so long selectors do not hit URL limits.

A managed store is busy, rate-limited and size-limited, and says so:

- **429, 502, 503, 504** are waited out and retried: after the ``Retry-After`` the server gave (in
  seconds or as a date), else 1, 2, 4 s, at most ``RETRIES`` times and never past the read's
  deadline. A body that is not JSON (a load balancer's HTML page) is no Prometheus answer and is
  named by its status, never parsed.
- **422 or a "too many series" refusal** (a per-query limit) is not worked around by asking for
  less of the answer; the read is narrowed instead and the parts joined: a ``series`` listing is
  split by matcher, then by metric name (from ``label/__name__/values``), then by halving the time
  range; a range query and a raw read by halving their time range. A part that is still refused at
  ``MIN_SPAN`` is left out and named in ``left_out`` (series) or raised (queries: their selector
  must be narrowed with label matchers).
- A request that times out says so with the source's ``timeout``."""

from __future__ import annotations

import email.utils
import json
import math
import re
import time
import urllib.error
import urllib.parse
import urllib.request

from . import Health, Labels, PastDeadline, Points, SourceError
from .auth import Auth
from .spec import SourceSpec

ENDPOINTS = {"query_range": ("/api/v1/query_range", {"query": "up", "start": "0", "end": "60", "step": "60"}),
             "query": ("/api/v1/query", {"query": "up"}),
             "series": ("/api/v1/series", {"match[]": "up", "start": "0", "end": "60"}),
             "labels": ("/api/v1/labels", None),
             "metadata": ("/api/v1/metadata", None),
             "buildinfo": ("/api/v1/status/buildinfo", None)}


RETRY = {429, 502, 503, 504}         # busy or rate-limited: wait and ask again
RETRIES = 4
BACKOFF = (1.0, 2.0, 4.0, 8.0)       # without a Retry-After
MAX_WAIT = 30.0                      # the longest single wait a Retry-After is believed for
MIN_SPAN = 600.0                     # the shortest time range a refused read is split down to
TOO_BIG = re.compile(r"(?i)too many|exceed|limit of|maximum number|max(imum)?[ _]?series|unique (time)?series")


class TooBig(SourceError):
    """The store refused a read for its size (a per-query series limit): narrow it, do not retry it."""


def retry_after(value: str | None, now: float | None = None) -> float | None:
    """Seconds to wait from a ``Retry-After`` header: a number of seconds or an HTTP date."""
    if not value:
        return None
    v = value.strip()
    try:
        return max(0.0, float(v))
    except ValueError:
        pass
    try:
        when = email.utils.parsedate_to_datetime(v).timestamp()
    except (TypeError, ValueError, IndexError):
        return None
    return max(0.0, when - (time.time() if now is None else now))


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
        try:
            x = float(v)
        except (TypeError, ValueError):
            continue
        if math.isfinite(x):                    # staleness NaNs and ±Inf are dropped
            out.append((float(t), x))
    return out


def _dur(seconds: float) -> str:
    return f"{max(1, math.ceil(seconds))}s"


def _origin(url: str) -> tuple:
    u = urllib.parse.urlsplit(url)
    return u.scheme.lower(), (u.hostname or "").lower(), u.port or {"http": 80, "https": 443}.get(u.scheme.lower())


class SameOriginRedirects(urllib.request.HTTPRedirectHandler):
    """Follows a redirect only to the same scheme, host and port. urllib's default copies every
    header, the credentials included, to wherever a redirect points (another host, or https to
    http); this refuses instead, so they never leave the server they were meant for."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        target = urllib.parse.urljoin(req.full_url, newurl)
        if _origin(target) != _origin(req.full_url):
            s, h, p = _origin(target)
            raise urllib.error.HTTPError(req.full_url, code, f"redirected to {s}://{h}:{p}, another server; not followed, "
                                         "so the credentials are not sent there", headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class PrometheusSource:
    def __init__(self, spec: SourceSpec):
        self.spec = spec
        self.name = spec.name
        self.auth = Auth(spec.auth, spec.insecure)
        self.requests = 0
        self.points = 0
        self.retries = 0                 # requests asked again after a 429/5xx
        self.narrowed = 0                # reads split because the store refused their size
        self.left_out: list[str] = []    # parts of a series listing still refused at MIN_SPAN
        self._sleep = time.sleep
        self._opener: urllib.request.OpenerDirector | None = None

    def _open(self, req: urllib.request.Request):
        if self._opener is None:
            self._opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=self.auth.ssl_context()),
                                                       SameOriginRedirects())
        return self._opener.open(req, timeout=self.spec.timeout)

    def _call(self, path: str, form: dict | None = None, *, post: bool = True, until: float | None = None) -> dict | list:
        url = self.spec.url + path
        body = None
        if form is not None and post:
            body = urllib.parse.urlencode(form, doseq=True).encode()
        elif form is not None:
            url += "?" + urllib.parse.urlencode(form, doseq=True)
        for attempt in range(RETRIES + 1):
            headers = {"Accept": "application/json", **self.auth.headers()}
            if body is not None:
                headers["Content-Type"] = "application/x-www-form-urlencoded"
            req = urllib.request.Request(url, data=body, headers=headers, method="POST" if body is not None else "GET")
            self.requests += 1
            try:
                with self._open(req) as r:
                    raw = r.read()
                break
            except urllib.error.HTTPError as e:
                if e.code in RETRY and attempt < RETRIES:
                    self._wait(e, attempt, path, until)
                    continue
                said = self._said(e)
                if e.code == 422 or (400 <= e.code < 500 and e.code not in (401, 403, 404) and TOO_BIG.search(said)):
                    raise TooBig(f"{self.spec.where()}{path}: {said}") from None
                raise SourceError(f"{self.spec.where()}{path}: {said}") from None
            except TimeoutError:
                raise SourceError(f"{self.spec.where()}{path}: no answer within the source's timeout of "
                                  f"{self.spec.timeout:g} s (set timeout on the [[sources]] entry, or narrow the read)") from None
            except OSError as e:
                reason = getattr(e, "reason", None)
                if isinstance(reason, TimeoutError):
                    raise SourceError(f"{self.spec.where()}{path}: no answer within the source's timeout of "
                                      f"{self.spec.timeout:g} s (set timeout on the [[sources]] entry, or narrow the read)") from None
                raise SourceError(f"{self.spec.where()}{path}: {reason or e}") from None
            except ValueError:                  # the HTTP library refusing a header: its message would carry the value
                raise SourceError(f"{self.spec.where()}{path}: invalid request header (a credential is malformed)") from None
        try:
            doc = json.loads(raw)
        except ValueError as e:
            raise SourceError(f"{self.spec.where()}{path}: the answer is not JSON ({e})") from None
        if not isinstance(doc, dict) or doc.get("status") != "success":
            raise SourceError(f"{self.spec.where()}{path}: {doc.get('error') if isinstance(doc, dict) else 'not a Prometheus answer'}")
        return doc.get("data")

    def _wait(self, e: urllib.error.HTTPError, attempt: int, path: str, until: float | None) -> None:
        """Wait out a 429 or 5xx: the server's Retry-After (capped), else a doubling pause; never
        past ``until``."""
        told = retry_after(e.headers.get("Retry-After") if e.headers else None)
        wait = min(MAX_WAIT, told if told is not None else BACKOFF[min(attempt, len(BACKOFF) - 1)])
        try:
            e.read()                            # the body (HTML from a load balancer, often) is not needed
        except (OSError, AttributeError):
            pass
        if until is not None and time.monotonic() + wait > until:
            raise PastDeadline(f"{self.spec.where()}{path}: HTTP {e.code}, and waiting {wait:g} s to ask again would pass the deadline")
        self.retries += 1
        self._sleep(wait)

    def _results(self, path: str, form: dict, until: float | None = None) -> list[dict]:
        """The ``result`` list of a query's answer; ``SourceError`` when the answer has another shape."""
        data = self._call(path, form, until=until)
        res = data.get("result") if isinstance(data, dict) else None
        if not isinstance(res, list) or not all(isinstance(r, dict) for r in res):
            raise SourceError(f"{self.spec.where()}{path}: not a Prometheus answer")
        return res

    @staticmethod
    def _said(e: urllib.error.HTTPError) -> str:
        if 300 <= e.code < 400:
            return f"HTTP {e.code}: {e.msg}"
        if e.code in (401, 403):
            return f"HTTP {e.code}: the server refused the credentials (check the token or certificate)"
        try:
            doc = json.loads(e.read())
            err = doc.get("error") if isinstance(doc, dict) else None
        except (ValueError, AttributeError, OSError):
            err = None                          # an HTML page from a proxy: named by its status only
        return f"HTTP {e.code}" + (f": {err}" if err else "")

    def _in_time(self, until: float | None) -> None:
        if until is not None and time.monotonic() > until:
            raise PastDeadline(f"{self.spec.where()}: past the deadline")

    def query_range(self, query: str, start: float, end: float, step: float,
                    until: float | None = None) -> list[tuple[Labels, Points]]:
        span = (self.spec.max_points - 1) * step
        merged: dict[tuple, tuple[Labels, dict[float, float]]] = {}
        t = start
        while t <= end:
            self._in_time(until)                    # between chunks: a long read stops once the deadline passed
            hi = min(end, t + span)
            try:
                res = self._results("/api/v1/query_range", {"query": query, "start": f"{t:.3f}", "end": f"{hi:.3f}", "step": f"{step:g}"}, until)
            except TooBig:
                if hi - t <= max(MIN_SPAN, step):
                    raise
                span = max(MIN_SPAN, step, (hi - t) / 2)    # fewer series touched in a shorter range: ask for less, then go on
                self.narrowed += 1
                continue
            for r in res:
                labels = {k: v for k, v in (r.get("metric") or {}).items() if k != "__name__"}
                g = merged.setdefault(tuple(sorted(labels.items())), (labels, {}))
                g[1].update(_points(r.get("values") or []))
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
            pts = [(t, v) for t, v in _points(r.get("values") or []) if start <= t <= end]
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

    def series(self, match: list[str], start: float, end: float, limit: int = 0) -> list[Labels]:
        self.left_out = []
        try:
            return self._series(match, start, end, limit)[: limit or None]
        except TooBig:
            pass
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
