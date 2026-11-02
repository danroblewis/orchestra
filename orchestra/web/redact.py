"""No token reaches a log: the web server's own loggers (uvicorn's access and error logs, and
Orchestra's) pass each record through a filter that replaces the value of ``token=`` (a login
link's query or fragment, a form) and of a bearer header with ``<redacted>``. The login form's
body is never logged (web/auth.py reads it and logs nothing)."""

from __future__ import annotations

import logging
import re

SECRET = re.compile(r"(?i)((?:^|[?#&;\s\"'])(?:token|access_token)=)[^&#\s\"']+|(bearer\s+)[^\s\"']+")
LOGGERS = ("uvicorn.access", "uvicorn.error", "uvicorn", "orchestra")


def redact(text: str) -> str:
    return SECRET.sub(lambda m: f"{m.group(1) or m.group(2)}<redacted>", text)


class Redact(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            said = record.getMessage()
        except (TypeError, ValueError):   # a record whose args do not fit its message: left as it is
            return True
        if (clean := redact(said)) != said:
            record.msg, record.args = clean, ()
        return True


def install() -> None:
    """The filter on each of the web server's loggers, once (idempotent: called when the app is
    made and again at its start, after uvicorn has configured its loggers)."""
    for name in LOGGERS:
        lg = logging.getLogger(name)
        if not any(isinstance(f, Redact) for f in lg.filters):
            lg.addFilter(Redact())
