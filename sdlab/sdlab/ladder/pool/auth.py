"""The pool's shared secret: ~/.sdlab/pool.token (or $SDLAB_POOL_TOKEN_FILE), mode 0600, made on first use.
Every endpoint that writes or hands out work or code checks it (the X-Pool-Token header, or
`Authorization: Bearer <token>`); the public site proxies to this server, so nothing else stops a
stranger."""

from __future__ import annotations

import hmac
import os
import secrets
from pathlib import Path

from fastapi import HTTPException, Request

HEADER = "X-Pool-Token"


def path() -> Path:
    return Path(os.environ.get("SDLAB_POOL_TOKEN_FILE") or Path.home() / ".sdlab" / "pool.token")


def token(create: bool = True) -> str | None:
    p = path()
    try:
        t = p.read_text().strip()
        if t:
            return t
    except OSError:
        pass
    if not create:
        return None
    p.parent.mkdir(parents=True, exist_ok=True)
    t = secrets.token_urlsafe(32)
    fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(t + "\n")
    os.chmod(p, 0o600)
    return t


def ok(given: str | None) -> bool:
    want = token()
    return bool(given) and bool(want) and hmac.compare_digest(given.encode(), want.encode())


def require(request: Request) -> None:
    """FastAPI dependency: 401 unless the request carries the token."""
    given = request.headers.get(HEADER)
    if not given:
        auth = request.headers.get("Authorization") or ""
        given = auth[7:].strip() if auth.lower().startswith("bearer ") else None
    if not ok(given):
        raise HTTPException(401, f"the pool's token is required ({HEADER} header)")
