"""The web UI's authentication: one ASGI middleware in front of every route, Orchestra's and the
plugins' alike (pages, ``/api/*``, static files, the websocket), so no page or plugin does it.

- **The credential** is the project's web token, ``<state>/web.token`` (owner-only, never in the
  configuration; ``orchestra web token`` prints it, ``--rotate`` replaces it). It is re-read when the
  file changes, so a rotation takes effect at once and ends every session.
- **Browsers** log in once at ``/login`` with the token and keep a session cookie: signed with a key
  derived from the token (HMAC-SHA256), HttpOnly, SameSite=Strict, valid for ``SESSION_S``.
  ``POST /logout`` drops it. **Programs** send ``Authorization: Bearer <token>`` on every request.
- **CSRF**: a request carried by the cookie that is not GET, HEAD or OPTIONS (and every websocket)
  must come from the page's own origin: ``Origin`` (or ``Referer``) names the host the request was
  sent to, and ``Sec-Fetch-Site`` is not cross-site or same-site. A bearer request needs no check:
  a browser never adds that header by itself.
- **Guessing** the token (a wrong bearer token, a failed login) is limited per peer address:
  ``FAIL_MAX`` failures in ``FAIL_WINDOW_S`` and further tries are refused (429) until the oldest
  ages out. The peer is the socket's, never ``X-Forwarded-For``; a session cookie still works while
  its peer is limited.
- ``[web] auth = "off"`` is allowed only on a loopback bind, and then a request that came through a
  proxy or tunnel (a forwarding header, or a Host that is not a loopback name) is refused, so a
  tunnel in front of it is closed, not open.

``/health`` stays open."""

from __future__ import annotations

import hashlib
import hmac
import html
import ipaddress
import json
import threading
import time
from collections import deque
from pathlib import Path
from urllib.parse import parse_qs, quote, urlsplit

from starlette.datastructures import Headers
from starlette.requests import cookie_parser
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from starlette.websockets import WebSocketClose

from ..config import ConfigError, Project
from ..tokens import owner_only, rotate

SESSION_S = 14 * 24 * 3600
FAIL_MAX = 5
FAIL_WINDOW_S = 60.0
LOGIN_BODY_MAX = 8192
SAFE = frozenset({"GET", "HEAD", "OPTIONS"})
FORWARDED = ("forwarded", "x-forwarded-for", "x-forwarded-host", "x-real-ip", "cf-connecting-ip", "cf-ray")
LOGIN_PAGE = Path(__file__).parent / "static" / "login.html"


def token_file(project: Project) -> Path:
    return project.state_dir / "web.token"


def token(project: Project) -> str:
    """The project's web token, made the first time it is asked for."""
    return owner_only(token_file(project))


def rotate_token(project: Project) -> str:
    return rotate(token_file(project))


def bearer(project: Project) -> dict[str, str]:
    """The header a program sends: ``{"Authorization": "Bearer <token>"}``."""
    return {"Authorization": f"Bearer {token(project)}"}


def is_loopback(host: str) -> bool:
    h = (host or "").strip().strip("[]").lower()
    if h == "localhost":
        return True
    try:
        return ipaddress.ip_address(h).is_loopback
    except ValueError:
        return False


def enabled(project: Project, host: str) -> bool:
    """Whether the web UI served on ``host`` asks for the token: ``[web] auth``, on unless set off,
    and off only on a loopback bind."""
    v = project.config.web_auth
    word = str(v).strip().lower() if v is not None else "on"
    if word in ("on", "true"):
        return True
    if word not in ("off", "false"):
        raise ConfigError(f'[web] auth must be "on" or "off", not {v!r}')
    if not is_loopback(host):
        raise ConfigError(f'[web] auth = "off" serves only on a loopback address, not {host!r}: '
                          "anyone who reaches the address could use every page")
    return False


class Secret:
    """The token and the session key derived from it, re-read when the file changes."""

    def __init__(self, project: Project):
        self.project = project
        self._seen: tuple[int, int] | None = None
        self.value = ""
        self.key = b""

    def current(self) -> Secret:
        path = token_file(self.project)
        try:
            st = path.stat()
            seen = (st.st_mtime_ns, st.st_ino)
        except FileNotFoundError:
            seen = None
        if seen is None or seen != self._seen:
            self.value = token(self.project)
            self.key = hmac.new(self.value.encode(), b"orchestra web session v1", hashlib.sha256).digest()
            st = path.stat()
            self._seen = (st.st_mtime_ns, st.st_ino)
        return self

    def matches(self, given: str) -> bool:
        return hmac.compare_digest(given.strip().encode(), self.current().value.encode())

    def session(self, now: float | None = None) -> str:
        body = f"v1.{int((now or time.time()) + SESSION_S)}"
        return f"{body}.{self._sign(body)}"

    def valid_session(self, value: str | None, now: float | None = None) -> bool:
        parts = (value or "").split(".")
        if len(parts) != 3 or parts[0] != "v1" or not parts[1].isdigit():
            return False
        body = f"{parts[0]}.{parts[1]}"
        return hmac.compare_digest(parts[2], self._sign(body)) and int(parts[1]) > (now or time.time())

    def _sign(self, body: str) -> str:
        return hmac.new(self.current().key, body.encode(), hashlib.sha256).hexdigest()


class Failures:
    """Failed token checks per peer address, in a sliding window."""

    def __init__(self, most: int = FAIL_MAX, window_s: float = FAIL_WINDOW_S, peers_max: int = 10_000):
        self.most, self.window_s, self.peers_max = most, window_s, peers_max
        self._by: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def wait(self, peer: str, now: float | None = None) -> float:
        """Seconds until ``peer`` may try again (0: it may now)."""
        now = time.monotonic() if now is None else now
        with self._lock:
            q = self._by.get(peer)
            if q is None:
                return 0.0
            while q and q[0] <= now - self.window_s:
                q.popleft()
            if not q:
                del self._by[peer]
                return 0.0
            return max(0.0, q[0] + self.window_s - now) if len(q) >= self.most else 0.0

    def fail(self, peer: str, now: float | None = None) -> None:
        now = time.monotonic() if now is None else now
        with self._lock:
            if peer not in self._by and len(self._by) >= self.peers_max:
                self._by.pop(next(iter(self._by)))
            self._by.setdefault(peer, deque(maxlen=self.most)).append(now)


def same_origin(h: Headers, required: bool) -> bool:
    """Whether a browser sent this from a page of the server's own origin. Without ``Origin`` or
    ``Referer`` (not a browser's unsafe request): ``not required``."""
    if h.get("sec-fetch-site") in ("cross-site", "same-site"):
        return False
    origin = h.get("origin") or h.get("referer")
    if not origin:
        return not required
    if origin == "null":
        return False
    return urlsplit(origin).netloc.lower() == (h.get("host") or "").lower()


def safe_next(value: str | None) -> str:
    """A path on this server to go to after logging in; anything else is ``/``."""
    v = value or "/"
    ok = v.startswith("/") and not v.startswith(("//", "/\\", "/login", "/logout"))
    return v if ok else "/"


class AuthMiddleware:
    """Every request but ``/health`` passes here first (see the module's docstring)."""

    def __init__(self, app, *, project: Project, on: bool):
        self.app, self.on, self.project = app, on, project
        self.secret = Secret(project)
        self.failures = Failures()
        self.cookie = f"orchestra_{project.key}"

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] not in ("http", "websocket"):
            return await self.app(scope, receive, send)
        ws = scope["type"] == "websocket"
        h = Headers(scope=scope)
        path, method = scope["path"], scope.get("method", "GET")
        unsafe = ws or method not in SAFE
        if path == "/health" and not ws:
            return await self.app(scope, receive, send)
        if not self.on:
            why = through_proxy(h)
            if why is None and unsafe and not same_origin(h, required=False):
                why = "a request from another site"
            if why:
                return await refuse(scope, receive, send, 403, f"refused: {why} (auth is off, so only this computer is served)")
            if path in ("/login", "/logout"):
                return await RedirectResponse("/", 303)(scope, receive, send)
            if path == "/api/session":
                return await JSONResponse({"ok": True, "auth": False})(scope, receive, send)
            return await self.app(scope, receive, send)
        if path == "/login" and not ws:
            return await self.login(scope, receive, send, h, method)
        if path == "/logout" and not ws:
            return await self.logout(scope, receive, send, h, method)
        via = None
        scheme, _, given = (h.get("authorization") or "").partition(" ")
        if scheme.lower() == "bearer":
            peer = (scope.get("client") or ("",))[0]
            if wait := self.failures.wait(peer):
                return await refuse(scope, receive, send, 429, "too many wrong tokens; try again later", retry=wait)
            if not self.secret.matches(given):
                self.failures.fail(peer)
                return await refuse(scope, receive, send, 401, "the wrong token")
            via = "bearer"
        elif self.secret.valid_session(cookie_parser(h.get("cookie") or "").get(self.cookie)):
            if unsafe and not same_origin(h, required=True):
                return await refuse(scope, receive, send, 403, "refused: not sent from this site's own pages")
            via = "cookie"
        if via is None:
            if not ws and method in ("GET", "HEAD") and not path.startswith("/api/") and "text/html" in (h.get("accept") or ""):
                there = path + (f"?{scope['query_string'].decode('latin-1')}" if scope.get("query_string") else "")
                return await RedirectResponse(f"/login?next={quote(there, safe='')}", 303)(scope, receive, send)
            return await refuse(scope, receive, send, 401, "log in at /login, or send Authorization: Bearer <token> "
                                                           "(`orchestra web token`)")
        if path == "/api/session" and not ws:
            return await JSONResponse({"ok": True, "auth": True, "via": via})(scope, receive, send)
        return await self.app(scope, receive, send)

    async def login(self, scope, receive, send, h: Headers, method: str) -> None:
        query = parse_qs(scope.get("query_string", b"").decode("latin-1"))
        nxt = safe_next((query.get("next") or ["/"])[-1])
        if method in ("GET", "HEAD"):
            if self.secret.valid_session(cookie_parser(h.get("cookie") or "").get(self.cookie)):
                return await RedirectResponse(nxt, 303)(scope, receive, send)
            return await login_page(nxt, "", 200)(scope, receive, send)
        if method != "POST":
            return await refuse(scope, receive, send, 405, "GET or POST /login")
        if not same_origin(h, required=False):
            return await login_page(nxt, "Refused: the form was sent from another site.", 403)(scope, receive, send)
        body = await read_body(receive, LOGIN_BODY_MAX)
        form = parse_qs(body.decode("utf-8", "replace")) if body is not None else {}
        nxt = safe_next((form.get("next") or [nxt])[-1])
        peer = (scope.get("client") or ("",))[0]
        if wait := self.failures.wait(peer):
            return await login_page(nxt, f"Too many wrong tokens. Try again in {int(wait) + 1} s.", 429)(scope, receive, send)
        if not self.secret.matches((form.get("token") or [""])[-1]):
            self.failures.fail(peer)
            return await login_page(nxt, "That is not this project's token.", 401)(scope, receive, send)
        resp = RedirectResponse(nxt, 303)
        resp.headers.append("Set-Cookie", self.set_cookie(scope, h, self.secret.session(), SESSION_S))
        return await resp(scope, receive, send)

    async def logout(self, scope, receive, send, h: Headers, method: str) -> None:
        if method != "POST":
            return await refuse(scope, receive, send, 405, "POST /logout")
        if not same_origin(h, required=True):
            return await refuse(scope, receive, send, 403, "refused: not sent from this site's own pages")
        resp = RedirectResponse("/login", 303)
        resp.headers.append("Set-Cookie", self.set_cookie(scope, h, "", 0))
        return await resp(scope, receive, send)

    def set_cookie(self, scope, h: Headers, value: str, max_age: int) -> str:
        """Secure when the browser reached it over HTTPS (directly, or through a tunnel that says
        so: only the cookie's flag follows the header, never a decision to let a request in)."""
        https = scope.get("scheme") == "https" or h.get("x-forwarded-proto") == "https"
        return (f"{self.cookie}={value}; Path=/; Max-Age={max_age}; HttpOnly; SameSite=Strict"
                + ("; Secure" if https else ""))


def through_proxy(h: Headers) -> str | None:
    """Why a request did not come straight from this computer, or None."""
    if any(k in h for k in FORWARDED):
        return "a request through a proxy or tunnel"
    try:
        host = urlsplit("//" + (h.get("host") or "")).hostname or ""
    except ValueError:
        host = ""
    if not is_loopback(host):
        return f"a request for {h.get('host')!r}, not a loopback address"
    return None


async def read_body(receive, most: int) -> bytes | None:
    """The request's body, or None when it is longer than ``most``."""
    out = bytearray()
    while True:
        msg = await receive()
        out += msg.get("body", b"")
        if len(out) > most:
            return None
        if not msg.get("more_body"):
            return bytes(out)


def login_page(nxt: str, error: str, status: int) -> Response:
    page = (LOGIN_PAGE.read_text(encoding="utf-8").replace("{{next}}", html.escape(nxt, quote=True))
            .replace("{{error}}", html.escape(error)).replace("{{error_class}}", "err" if error else "err none"))
    return HTMLResponse(page, status, headers={"Cache-Control": "no-store", "X-Frame-Options": "DENY"})


async def refuse(scope, receive, send, status: int, why: str, retry: float | None = None) -> None:
    if scope["type"] == "websocket":
        return await WebSocketClose(code=1008, reason=why[:120])(scope, receive, send)
    headers = {"Cache-Control": "no-store"}
    if status == 401:
        headers["WWW-Authenticate"] = "Bearer"
    if retry:
        headers["Retry-After"] = str(int(retry) + 1)
    return await Response(json.dumps({"ok": False, "error": why}), status, headers=headers,
                          media_type="application/json")(scope, receive, send)
