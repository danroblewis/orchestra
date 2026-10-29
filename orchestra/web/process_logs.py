"""The logs of the processes the host launches (orchestra/launcher.py), for the Core page.

The launcher writes each process's output to ``<state>/logs/machines/<name>.log`` (rotated to
``.log.1`` past ``LOG_MAX``). These are processes, not machines (AGENTS.md rule 2): a plugin's
scheduler or host shows here and never on the Machines page. A log is found by the process's
name, never by a path anyone gave, and read only when its real path lies within the state
directory or the repository (``machine_logs.readable``). Reads are bounded: the tail is read by
seeking from the end, never more than ``MAX_BYTES``. A missing or unreadable log is a note, not
an error. This imports nothing but the standard library and ``machine_logs``, so the Core page
keeps it (AGENTS.md rule 8)."""

from __future__ import annotations

import re
from pathlib import Path

from .machine_logs import readable

MAX_LINES = 2000
MAX_BYTES = 1_000_000          # the most read from the end of a log, however many lines are asked for
HINT_LINES = 40                # the last lines looked at for an error
HINT_BYTES = 16_000
NAME = re.compile(r"^[A-Za-z0-9_-][A-Za-z0-9._-]*$")
ERROR = re.compile(r"Traceback \(most recent call last\)|\b(?:ERROR|CRITICAL|FATAL)\b|\b\w*(?:Error|Exception)\b|"
                   r"\berror:|\bfailed\b|\bcommand not found\b|\bnot on PATH\b|\bgave up\b|\bgiving up\b|"
                   r"\bexited with code (?:[1-9]|-)")


def directory(logs_dir: Path) -> Path:
    return logs_dir / "machines"


def names(logs_dir: Path) -> list[str]:
    """The processes with a log, whether or not the host runs them now."""
    try:
        return sorted(p.name[:-4] for p in directory(logs_dir).glob("*.log") if NAME.match(p.name[:-4]))
    except OSError:
        return []


def _tail(path: Path, lines: int, max_bytes: int) -> tuple[list[str], bool, int]:
    """The last ``lines`` lines, whether there is more before them, and the file's size."""
    with path.open("rb") as f:
        f.seek(0, 2)
        size = f.tell()
        start = max(0, size - max_bytes)
        f.seek(start)
        chunk = f.read(size - start)
    text = chunk.decode("utf-8", "replace").splitlines()
    if start > 0 and text:
        text = text[1:]                                   # the first line read is probably cut
    return text[-lines:], start > 0 or len(text) > lines, size


def error_line(lines: list[str]) -> str | None:
    """The last of these lines that looks like an error or a traceback, if any (a cheap guess)."""
    return next((ln.strip()[:300] for ln in reversed(lines) if ERROR.search(ln)), None)


def read(name: str, logs_dir: Path, roots: list[Path], lines: int = 200, max_bytes: int = MAX_BYTES) -> dict:
    """A process's log tail: ``lines`` (oldest first), ``more`` (whether the file holds more before
    them), ``size``, ``path``, ``error`` (the last error-like line of the tail) and ``note`` when it
    cannot be read."""
    lines = max(1, min(int(lines), MAX_LINES))
    out: dict = {"name": name, "lines": [], "more": False, "size": None, "path": None, "error": None, "note": None,
                 "previous": None}
    if not NAME.match(name or ""):
        out["note"] = "not a process name"
        return out
    want = directory(logs_dir) / f"{name}.log"
    out["path"] = str(want)
    if (old := want.with_suffix(".log.1")).is_file():
        out["previous"] = str(old)                        # rotated away by the launcher past its size limit
    if not want.exists():
        out["note"] = f"no log yet: {want} is written when the host starts {name}"
        return out
    path, why = readable(str(want), roots)
    if path is None:
        out["note"] = why
        return out
    try:
        out["lines"], out["more"], out["size"] = _tail(path, lines, max_bytes)
    except OSError as e:
        out["note"] = f"cannot read {want}: {type(e).__name__}: {e}"
        return out
    out["error"] = error_line(out["lines"][-HINT_LINES:])
    if not out["lines"]:
        out["note"] = f"{want} is empty"
    return out


def hint(name: str, logs_dir: Path, roots: list[Path]) -> str | None:
    """The last error-like line among a log's last few lines, read cheaply, or None."""
    got = read(name, logs_dir, roots, HINT_LINES, HINT_BYTES)
    return got["error"]
