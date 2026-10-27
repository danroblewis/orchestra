"""The events endpoint: publishing and reading the project's events over HTTP, so a machine in
any language needs nothing of Orchestra's library (``docs/roadmap/decisions.md`` D16).

The host that launches (``orchestra.host``) serves it on ``[events] listen`` (``127.0.0.1`` and a
port the system picks, unless given), records its address in the runtime record
(``events_endpoint``) and hands it to what it launches in ``ORCHESTRA_EVENTS_ENDPOINT``, with the
project's token in ``ORCHESTRA_EVENTS_TOKEN``. A machine the host did not launch asks
``orchestra events endpoint`` for both.

- ``POST /events``: one event, ``{type, source, data?, subject?, time?, id?, correlationid?,
  causationid?}`` (or a structured-mode CloudEvent, the same fields with ``specversion`` and
  ``datacontenttype``); Orchestra writes the envelope through ``orchestra.events.Events``
  (AGENTS.md rules 3 and 5) and answers with the event's id (``validate.py``, ``server.py``);
- ``GET /events?after=<offset>&types=a,b&wait=<s>&limit=<n>``: the events after an offset, and the
  offset to read from next, waiting up to ``wait`` seconds for one to arrive;
- ``GET /health``: whether it is up, without the token.

Every request but ``/health`` carries ``Authorization: Bearer <token>``. The token is the
project's, kept in ``<state>/events.token`` (readable by its owner only), so another local user's
process can neither publish nor read."""

from __future__ import annotations

import os
import secrets

from .. import runtime
from ..config import ConfigError, Project

ENV_URL = "ORCHESTRA_EVENTS_ENDPOINT"
ENV_TOKEN = "ORCHESTRA_EVENTS_TOKEN"
DEFAULT_LISTEN = "127.0.0.1:0"
RECORD_KEY = "events_endpoint"


def token_file(project: Project):
    return project.state_dir / "events.token"


def token(project: Project) -> str:
    """The project's token, made the first time it is asked for (owner-only), and kept, so a
    machine the host did not launch keeps working across the host's restarts."""
    path = token_file(project)
    try:
        return path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        pass
    project.state_dir.mkdir(parents=True, exist_ok=True)
    made = secrets.token_urlsafe(32)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:                   # another process made it first: theirs stands
        return path.read_text(encoding="utf-8").strip()
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(made + "\n")
    return made


def listen_address(value) -> tuple[str, int] | None:
    """``[events] listen``: ``host:port`` (port 0: one the system picks), or ``off`` (or false)
    for no endpoint."""
    if value is None:
        value = DEFAULT_LISTEN
    if value is False or (isinstance(value, str) and value.strip().lower() in ("off", "false", "")):
        return None
    if not isinstance(value, str):
        raise ConfigError(f"[events] listen must be \"host:port\" or \"off\", not {value!r}")
    host, sep, port = value.strip().rpartition(":")
    if not sep or not host or not port.isdigit() or not 0 <= int(port) <= 65535:
        raise ConfigError(f"[events] listen must be \"host:port\" or \"off\", not {value!r}")
    return host.strip("[]"), int(port)


def recorded(project: Project) -> dict | None:
    """The live endpoint in the runtime record (``{"url", "pid", "since"}``), or None."""
    rec = runtime.read(project).get(RECORD_KEY)
    return rec if isinstance(rec, dict) and runtime.holds(rec) else None
