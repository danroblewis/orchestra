"""The events endpoint's HTTP server, run by the host that launches (``orchestra.host``): the
events, and beside them the model and experiments (``api.py``), behind one token.

A stdlib ``ThreadingHTTPServer``, one thread per request, so a long poll never holds up a publish.
Everything goes through the ``Events`` it is given: it never touches a bus backend itself
(AGENTS.md rule 5), and it writes the envelope with ``orchestra.events.envelope`` (rule 3).

**Idempotency.** No bus backend refuses a repeated id, so the endpoint does: the ids of the last
``SEEN_MAX`` events on the bus when it started, and of every event posted to it since, are kept,
and a post with an id among them is answered as a duplicate (200, the id) and not written again.
A retry after a lost answer is therefore safe while the host runs, and across a restart for an
event among the bus's last ``SEEN_MAX``."""

from __future__ import annotations

import hmac
import json
import socket
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

from .. import runtime
from ..config import Project
from ..events import Events
from . import RECORD_KEY, api
from .validate import MAX_BODY, Invalid, check, number, parse, types_filter

SEEN_MAX = 10_000
WAIT_MAX_S = 30.0
LIMIT_DEFAULT = 1000
LIMIT_MAX = 10_000
POLL_S = 0.2
DRAIN_MAX = 16 * MAX_BODY     # a body this large is read and thrown away before it is refused


class EventsEndpoint:
    def __init__(self, project: Project, events: Events, listen: tuple[str, int], token: str,
                 log: Callable[[str], None] = print):
        self.project = project
        self.events = events
        self.listen = listen
        self.token = token
        self.log = log
        self.url: str | None = None
        self._seen: OrderedDict[str, None] = OrderedDict()
        self._lock = threading.Lock()          # around every use of the bus: not every client library is thread-safe
        self._stop = threading.Event()
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    # ---- what it does ----
    def publish(self, body: bytes) -> tuple[int, dict]:
        fields = check(parse(body))
        with self._lock:
            if (eid := fields.get("id")) is not None and eid in self._seen:
                return 200, {"ok": True, "id": eid, "duplicate": True}
            ev = self.events.publish(fields.pop("type"), fields.pop("data"), source=fields.pop("source"), **fields)
            self._remember(ev["id"])
        return 201, {"ok": True, "id": ev["id"], "duplicate": False, "event": ev}

    def read(self, query: dict[str, list[str]]) -> dict:
        one = {k: v[-1] for k, v in query.items()}
        unknown = sorted(set(one) - {"after", "types", "wait", "limit"})
        if unknown:
            raise Invalid(f"unknown parameter{'s' if len(unknown) > 1 else ''} {', '.join(unknown)}; "
                          "GET /events takes after, types, wait and limit")
        types = types_filter(one.get("types"))
        wait = number(one.get("wait"), "wait", 0.0, 0.0, WAIT_MAX_S)
        limit = int(number(one.get("limit"), "limit", LIMIT_DEFAULT, 1, LIMIT_MAX, integer=True))
        after = one.get("after", "0")
        offset = self._end() if after == "end" else int(number(after, "after", 0, 0, 2**62, integer=True))
        deadline = time.monotonic() + wait
        while True:
            if self._end() != offset:
                with self._lock:
                    evs, nxt = self.events.after(offset)
                if len(evs) > limit:              # offsets count events, so the page ends limit past the start
                    evs, nxt = evs[:limit], offset + limit
                offset = nxt
                if types is not None:
                    evs = [e for e in evs if e.get("type") in types]
                if evs:
                    return {"ok": True, "events": evs, "next": offset}
            if time.monotonic() >= deadline or self._stop.is_set():
                return {"ok": True, "events": [], "next": offset}
            self._stop.wait(min(POLL_S, max(0.0, deadline - time.monotonic())))

    def _end(self) -> int:
        with self._lock:
            return self.events.end()

    def _remember(self, eid) -> None:
        if not isinstance(eid, str):
            return
        self._seen[eid] = None
        self._seen.move_to_end(eid)
        while len(self._seen) > SEEN_MAX:
            self._seen.popitem(last=False)

    def authorized(self, header: str | None) -> bool:
        scheme, _, given = (header or "").partition(" ")
        return scheme.lower() == "bearer" and hmac.compare_digest(given.strip().encode(), self.token.encode())

    # ---- serving ----
    def start(self) -> str:
        """Bind, record the address and serve in the background; returns the URL."""
        try:
            recent, _ = self.events.read(0, limit=SEEN_MAX)
            for ev in recent:
                self._remember(ev.get("id"))
        except Exception as e:  # noqa: BLE001 - idempotency then covers only what is posted from now on
            self.log(f"events endpoint: cannot read the bus's recent ids: {type(e).__name__}: {e}")
        host, port = self.listen
        server_cls = _Server6 if ":" in host else _Server
        self._server = server_cls((host, port), _handler(self))
        bound = self._server.server_address[1]
        shown = "127.0.0.1" if host in ("0.0.0.0", "") else ("::1" if host == "::" else host)
        self.url = f"http://[{shown}]:{bound}" if ":" in shown else f"http://{shown}:{bound}"
        self._thread = threading.Thread(target=self._server.serve_forever, kwargs={"poll_interval": 0.2},
                                        name="events-endpoint", daemon=True)
        self._thread.start()
        runtime.update(self.project, lambda d: d.__setitem__(RECORD_KEY, {"url": self.url, **runtime.me()}))
        return self.url

    def stop(self) -> None:
        self._stop.set()
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
        mine = runtime.me()["pid"]
        runtime.update(self.project, lambda d: d.pop(RECORD_KEY, None)
                       if (d.get(RECORD_KEY) or {}).get("pid") == mine else None)


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


class _Server6(_Server):
    address_family = socket.AF_INET6


def _handler(ep: EventsEndpoint) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "orchestra-events"
        protocol_version = "HTTP/1.1"

        def log_message(self, *args) -> None:        # requests are not logged; refusals of note are
            pass

        def _send(self, status: int, body: dict, headers: dict | None = None) -> None:
            raw = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            for k, v in (headers or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(raw)

        def _route(self) -> str | None:
            path = urlsplit(self.path).path.rstrip("/") or "/"
            if path == "/health":
                return path
            if path != "/events" and not api.known(path):
                self._send(404, {"ok": False, "error": f"no {path} here: POST /events, GET /events, GET /health, and the model "
                                                       "and experiments (GET /model, /experiments, ...: USING_ORCHESTRA.md §5.9)"})
                return None
            if not ep.authorized(self.headers.get("Authorization")):
                self._send(401, {"ok": False, "error": "needs Authorization: Bearer <token> (ORCHESTRA_EVENTS_TOKEN, "
                                                       "or `orchestra events endpoint`)"},
                           {"WWW-Authenticate": "Bearer"})
                return None
            return path

        def _api(self, method: str, path: str, body: bytes = b"") -> None:
            try:
                status, out = api.handle(ep.project, method, path, urlsplit(self.path).query, body)
            except Exception as e:  # noqa: BLE001 - a fault of ours: said, and the endpoint stays up
                ep.log(f"events endpoint: {method} {path} failed: {type(e).__name__}: {e}")
                status, out = 500, {"ok": False, "error": f"{type(e).__name__}: {e}"}
            self._send(status, out)

        def _refuse(self) -> None:
            self._send(405, {"ok": False, "error": f"{self.command} is not served: GET and POST only"})

        do_PUT = do_DELETE = do_PATCH = _refuse

        def do_GET(self) -> None:
            path = self._route()
            if path == "/health":
                self._send(200, {"ok": True})
            elif path is not None and path != "/events":
                self._api("GET", path)
            elif path == "/events":
                try:
                    self._send(200, ep.read(parse_qs(urlsplit(self.path).query, keep_blank_values=True)))
                except Invalid as e:
                    self._send(e.status, {"ok": False, "error": str(e)})
                except Exception as e:  # noqa: BLE001 - the bus failed; the machine retries
                    self._send(503, {"ok": False, "error": f"the event bus cannot be read: {type(e).__name__}: {e}"})

        def do_POST(self) -> None:
            path = self._route()
            if path is None:
                return
            if path == "/health":
                self._send(405, {"ok": False, "error": "GET /health"})
                return
            length = self.headers.get("Content-Length")
            if length is None or not length.isdigit():
                self._send(411, {"ok": False, "error": "needs Content-Length"}, {"Connection": "close"})
                self.close_connection = True
                return
            if int(length) > MAX_BODY:
                if int(length) <= DRAIN_MAX:          # read it, so the client hears the answer, not a broken pipe
                    self.rfile.read(int(length))
                self._send(413, {"ok": False, "error": f"the body is {length} bytes; at most {MAX_BODY}"},
                           {"Connection": "close"})
                self.close_connection = True
                return
            body = self.rfile.read(int(length))
            if path != "/events":
                self._api("POST", path, body)
                return
            try:
                status, out = ep.publish(body)
            except Invalid as e:
                status, out = e.status, {"ok": False, "error": str(e)}
            except Exception as e:  # noqa: BLE001 - the bus failed; the machine retries with the same id
                ep.log(f"events endpoint: publish failed: {type(e).__name__}: {e}")
                status, out = 503, {"ok": False, "error": f"the event bus refused it: {type(e).__name__}: {e}"}
            self._send(status, out)

    return Handler
