"""Owner-only secrets in the state directory: the events endpoint's token (``events.token``) and
the web UI's (``web.token``). Made the first time one is asked for, readable by its owner only
(0600), and kept, so what uses it keeps working across restarts. Never in the configuration."""

from __future__ import annotations

import os
import secrets
from pathlib import Path


def owner_only(path: Path) -> str:
    """The secret in ``path``, made (32 random bytes, URL-safe) if there is none yet."""
    try:
        return path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        pass
    path.parent.mkdir(parents=True, exist_ok=True)
    made = secrets.token_urlsafe(32)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:                   # another process made it first: theirs stands
        return path.read_text(encoding="utf-8").strip()
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(made + "\n")
    return made


def rotate(path: Path) -> str:
    """A new secret in place of the old one, written owner-only and swapped in atomically."""
    path.parent.mkdir(parents=True, exist_ok=True)
    made = secrets.token_urlsafe(32)
    tmp = path.with_name(f".{path.name}.{os.getpid()}")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(made + "\n")
    os.replace(tmp, path)
    return made
