"""A source that answers the Prometheus HTTP query API (Prometheus, VictoriaMetrics, Thanos, Mimir,
Chronosphere), over the standard library.

Reads only: ``query_range`` for evaluated queries (in chunks of fewer than ``max_points`` points
per series, joined), an instant ``query`` of ``selector[range]`` for raw samples at their real
times, ``series`` for the schema, ``metadata`` and ``status/buildinfo`` where the server keeps
them. Every request carries the source's auth (``auth.py``) and its timeout; a failure raises
``SourceError`` naming the server and what it said, never a credential. Queries go as POSTed
forms, which every one of these servers accepts, so long selectors do not hit URL limits."""

from __future__ import annotations

import json
import math
import time
import urllib.error
import urllib.parse
import urllib.request

from . import Health, Labels, Points, SourceError
from .auth import Auth
from .spec import SourceSpec

ENDPOINTS = {"query_range": ("/api/v1/query_range", {"query": "up", "start": "0", "end": "60", "step": "60"}),
             "query": ("/api/v1/query", {"query": "up"}),
             "series": ("/api/v1/series", {"match[]": "up", "start": "0", "end": "60"}),
             "labels": ("/api/v1/labels", None),
             "metadata": ("/api/v1/metadata", None),
             "buildinfo": ("/api/v1/status/buildinfo", None)}


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
        self._opener: urllib.request.OpenerDirector | None = None

    def _open(self, req: urllib.request.Request):
        if self._opener is None:
            self._opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=self.auth.ssl_context()),
                                                       SameOriginRedirects())
        return self._opener.open(req, timeout=self.spec.timeout)

    def _call(self, path: str, form: dict | None = None, *, post: bool = True) -> dict | list:
        url = self.spec.url + path
        body = None
        if form is not None and post:
            body = urllib.parse.urlencode(form, doseq=True).encode()
        elif form is not None:
            url += "?" + urllib.parse.urlencode(form, doseq=True)
        headers = {"Accept": "application/json", **self.auth.headers()}
        if body is not None:
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        req = urllib.request.Request(url, data=body, headers=headers, method="POST" if body is not None else "GET")
        self.requests += 1
        try:
            with self._open(req) as r:
                raw = r.read()
        except urllib.error.HTTPError as e:
            raise SourceError(f"{self.spec.where()}{path}: {self._said(e)}") from None
        except OSError as e:
            raise SourceError(f"{self.spec.where()}{path}: {getattr(e, 'reason', None) or e}") from None
        except ValueError:                  # the HTTP library refusing a header: its message would carry the value
            raise SourceError(f"{self.spec.where()}{path}: invalid request header (a credential is malformed)") from None
        try:
            doc = json.loads(raw)
        except ValueError as e:
            raise SourceError(f"{self.spec.where()}{path}: the answer is not JSON ({e})") from None
        if not isinstance(doc, dict) or doc.get("status") != "success":
            raise SourceError(f"{self.spec.where()}{path}: {doc.get('error') if isinstance(doc, dict) else 'not a Prometheus answer'}")
        return doc.get("data")

    def _results(self, path: str, form: dict) -> list[dict]:
        """The ``result`` list of a query's answer; ``SourceError`` when the answer has another shape."""
        data = self._call(path, form)
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
            err = json.loads(e.read()).get("error")
        except (ValueError, AttributeError, OSError):
            err = None
        return f"HTTP {e.code}" + (f": {err}" if err else "")

    def query_range(self, query: str, start: float, end: float, step: float) -> list[tuple[Labels, Points]]:
        span = (self.spec.max_points - 1) * step
        merged: dict[tuple, tuple[Labels, dict[float, float]]] = {}
        t = start
        while t <= end:
            hi = min(end, t + span)
            for r in self._results("/api/v1/query_range", {"query": query, "start": f"{t:.3f}", "end": f"{hi:.3f}", "step": f"{step:g}"}):
                labels = {k: v for k, v in (r.get("metric") or {}).items() if k != "__name__"}
                g = merged.setdefault(tuple(sorted(labels.items())), (labels, {}))
                g[1].update(_points(r.get("values") or []))
            t = hi + step
        out = [(labels, sorted(pts.items())) for labels, pts in merged.values()]
        self.points += sum(len(p) for _, p in out)
        return out

    def select(self, selector: str, start: float, end: float) -> list[tuple[Labels, Points]]:
        out = []
        for r in self._results("/api/v1/query", {"query": f"{selector}[{_dur(end - start)}]", "time": f"{end:.3f}"}):
            pts = [(t, v) for t, v in _points(r.get("values") or []) if start <= t <= end]
            if pts:
                out.append((dict(r.get("metric") or {}), pts))
        self.points += sum(len(p) for _, p in out)
        return out

    def series(self, match: list[str], start: float, end: float, limit: int = 0) -> list[Labels]:
        form = {"match[]": list(match), "start": f"{start:.3f}", "end": f"{end:.3f}"}
        if limit:
            form["limit"] = str(limit)
        data = self._call("/api/v1/series", form)
        if not isinstance(data, list) or not all(isinstance(x, dict) for x in data):
            raise SourceError(f"{self.spec.where()}/api/v1/series: not a Prometheus answer")
        return [dict(x) for x in data][: limit or None]

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
