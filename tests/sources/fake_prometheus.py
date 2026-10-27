"""A stdlib fake of the Prometheus HTTP query API, evaluating with Orchestra's PromQL subset
(``orchestra/metrics/promql.py``) over points held in memory.

Injectable: a required bearer token (or an ``API-Token`` header), mTLS, latency, failures (an HTTP
status for every request, or for the next N), endpoints that are missing (404), NaN samples, and
metadata. It records every query it was asked, so tests can check what went out."""

from __future__ import annotations

import json
import re
import ssl
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from orchestra.metrics import promql

RAW = re.compile(r"^(?P<sel>.*)\[(?P<n>\d+)(?P<u>[smhd])\]\s*$", re.DOTALL)
UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400}


class FakePrometheus:
    def __init__(self, dump=None, *, token: str | None = None, header: str = "Authorization", tls=None):
        self.dump = list(dump or [])            # (name, labels, [(t, v)])
        self.token, self.header = token, header
        self.latency = 0.0
        self.fail_status: int | None = None     # every request answers this
        self.fail_next = 0                      # the next N requests answer 500
        self.missing: set[str] = set()          # endpoint names answering 404: query_range, query, series, labels, metadata, buildinfo
        self.nan_at: set[float] = set()         # sample times served as NaN
        self.meta: dict[str, list[dict]] = {}
        self.queries: list[str] = []
        self.requests = 0
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        if tls is not None:                     # (server cert, server key, CA of the clients it accepts): mTLS
            ctx = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH, cafile=str(tls[2]))
            ctx.load_cert_chain(str(tls[0]), str(tls[1]))
            ctx.verify_mode = ssl.CERT_REQUIRED
            self.server.socket = ctx.wrap_socket(self.server.socket, server_side=True)
        self.url = f"{'https' if tls else 'http'}://127.0.0.1:{self.server.server_address[1]}"
        self._thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self._thread.start()

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()

    def _authorized(self, headers) -> bool:
        if self.token is None:
            return True
        want = f"Bearer {self.token}" if self.header == "Authorization" else self.token
        return headers.get(self.header) == want

    def _value(self, t: float, v: float) -> str:
        return "NaN" if t in self.nan_at else repr(float(v))

    def _matrix(self, results) -> dict:
        return {"resultType": "matrix", "result": [{"metric": lab, "values": [[t, self._value(t, v)] for t, v in pts]} for lab, pts in results]}

    def answer(self, endpoint: str, form: dict[str, list[str]]):
        one = lambda k, d=None: (form.get(k) or [d])[0]
        if endpoint == "query_range":
            q = one("query")
            self.queries.append(q)
            return self._matrix(promql.query_range(self.dump, q, float(one("start")), float(one("end")), float(one("step"))))
        if endpoint == "query":
            q, at = one("query"), float(one("time", time.time()))
            self.queries.append(q)
            if m := RAW.match(q):
                d = int(m["n"]) * UNITS[m["u"]]
                return self._matrix([(lab, [(t, v) for t, v in pts if t > at - d]) for lab, pts in promql.select(self.dump, m["sel"], at - d, at)])
            res = promql.query_range(self.dump, q, at, at, 60)
            return {"resultType": "vector", "result": [{"metric": lab, "value": [at, self._value(at, pts[-1][1])]} for lab, pts in res]}
        if endpoint == "series":
            start, end = float(one("start", 0)), float(one("end", time.time()))
            seen = {}
            for m in form.get("match[]") or []:
                for lab, _ in promql.select(self.dump, m, start, end):
                    seen.setdefault(tuple(sorted(lab.items())), lab)
            out = sorted(seen.values(), key=lambda x: sorted(x.items()))
            return out[: int(one("limit"))] if one("limit") else out
        if endpoint == "labels":
            return sorted({k for _, lab, _ in self.dump for k in lab} | {"__name__"})
        if endpoint == "metadata":
            return self.meta
        if endpoint == "buildinfo":
            return {"version": "fake-1.0", "revision": "test"}
        raise KeyError(endpoint)

    def _handler(self):
        fake = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _go(self, form: dict):
                fake.requests += 1
                if fake.latency:
                    time.sleep(fake.latency)
                path = urllib.parse.urlsplit(self.path).path
                endpoint = {"/api/v1/query_range": "query_range", "/api/v1/query": "query", "/api/v1/series": "series",
                            "/api/v1/labels": "labels", "/api/v1/metadata": "metadata", "/api/v1/status/buildinfo": "buildinfo"}.get(path)
                if not fake._authorized(self.headers):
                    return self._send(401, {"status": "error", "error": "unauthorized"})
                if fake.fail_status:
                    return self._send(fake.fail_status, {"status": "error", "error": "injected failure"})
                if fake.fail_next > 0:
                    fake.fail_next -= 1
                    return self._send(500, {"status": "error", "error": "injected failure"})
                if endpoint is None or endpoint in fake.missing:
                    return self._send(404, {"status": "error", "error": "not found"})
                try:
                    data = fake.answer(endpoint, form)
                except promql.PromQLError as e:
                    return self._send(400, {"status": "error", "errorType": "bad_data", "error": str(e)})
                self._send(200, {"status": "success", "data": data})

            def _send(self, code: int, body: dict):
                raw = json.dumps(body).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def do_GET(self):
                self._go(urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query))

            def do_POST(self):
                n = int(self.headers.get("Content-Length") or 0)
                self._go(urllib.parse.parse_qs(self.rfile.read(n).decode()))

        return H
