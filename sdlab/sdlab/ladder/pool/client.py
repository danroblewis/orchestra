"""A worker's HTTP client for the pool's endpoints (docs/pool.md), with the token. A server that cannot be
reached, or answers 5xx, raises Down: the worker keeps its results in the outbox and tries again later."""

from __future__ import annotations

import json
import socket
import urllib.error
import urllib.request

from . import auth


class Down(Exception):
    """The server cannot be reached now (or failed: 5xx)."""


class Client:
    def __init__(self, server: str, token: str):
        self.server = server.rstrip("/")
        self.token = token

    def _open(self, method: str, path: str, data: bytes | None, timeout: float):
        req = urllib.request.Request(self.server + path, method=method, data=data)
        req.add_header("Content-Type", "application/json")
        req.add_header(auth.HEADER, self.token)
        try:
            return urllib.request.urlopen(req, timeout=timeout)
        except urllib.error.HTTPError as e:
            if e.code >= 500:
                raise Down(f"{method} {path}: {e.code}") from None
            return e
        except (urllib.error.URLError, socket.timeout, ConnectionError, TimeoutError, OSError) as e:
            raise Down(f"{method} {path}: {getattr(e, 'reason', e)}") from None

    def call(self, method: str, path: str, body: dict | None = None, timeout: float = 60) -> tuple[int, dict]:
        r = self._open(method, path, json.dumps(body, default=str).encode() if body is not None else None, timeout)
        try:
            raw = r.read()
        except (OSError, socket.timeout) as e:
            raise Down(f"{method} {path}: {e}") from None
        code = getattr(r, "status", None) or r.getcode()
        try:
            return code, json.loads(raw or b"{}")
        except ValueError:
            return code, {"error": raw[:500].decode(errors="replace")}

    def bundle(self, want: str, have: list[str], timeout: float = 600) -> bytes:
        r = self._open("GET", f"/api/pool/code/bundle?want={want}&have={','.join(have)}", None, timeout)
        code = getattr(r, "status", None) or r.getcode()
        try:
            data = r.read()
        except (OSError, socket.timeout) as e:
            raise Down(f"bundle: {e}") from None
        if code != 200:
            raise LookupError(f"bundle of {want[:12]}: {code} {data[:300].decode(errors='replace')}")
        return data
