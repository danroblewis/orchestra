"""Every request Orchestra sends to a source, logged: ``<state>/sources/<name>.requests.jsonl``.

One line per HTTP request the transport sends (``transport.py``), a retried one included, and one
per read refused before anything was sent (the round's budget, the daily cap, the deadline, the
Core page's guard): ``t`` (unix seconds), ``endpoint`` (the API path), ``query`` (the query, the
``match[]`` selectors or the metric asked about), ``window`` (``[start, end]``, or ``[time]`` for
an instant), ``step``, ``series`` and ``points`` in the answer, ``ms``, ``by`` (who asked:
``host`` for discovery's reads, ``infer`` for an inference round, ``page`` for the Core page's
box, ``web`` for the web server's reads of the model's series, ``cli`` for ``orchestra sources``,
``explore`` for ``orchestra sources explore``'s survey beyond the match, ``exploring.py``),
``sent`` (false for a refusal never sent), ``error``, ``bytes`` (the answer's size, when one came)
and ``run`` (the discovery run or inference round that asked, ``sd/runs.py``, which derives each
run's cost from the lines it tagged). Never a header, so never a credential.

The log keeps the last ``KEEP`` lines: once it holds a tenth more, it is cut back to them (the
newest kept), so it never grows past ``KEEP`` + ``KEEP``/10 lines. It never stops a read: a write
that fails is dropped. ``last`` and ``today`` read it back for the Core page and ``orchestra
sources check``."""

from __future__ import annotations

import json
import os
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

KEEP = 10_000                 # lines kept
SLACK = KEEP // 10            # ... and at most this many more before the log is cut back
BYS = ("host", "infer", "page", "web", "cli", "explore")
_LOCK = threading.Lock()
_COUNTS: dict[str, int] = {}  # path -> lines, as this process last counted them


def path(state_dir: Path | str, name: str) -> Path:
    return Path(state_dir) / "sources" / f"{name}.requests.jsonl"


def _lines(p: Path) -> int:
    try:
        with p.open("rb") as f:
            return sum(1 for _ in f)
    except OSError:
        return 0


def _cut(p: Path) -> None:
    """The newest ``KEEP`` lines kept, the rest dropped, replaced atomically."""
    with p.open("rb") as f:
        keep = f.readlines()[-KEEP:]
    tmp = p.with_name(p.name + f".{os.getpid()}.tmp")
    with tmp.open("wb") as f:
        f.writelines(keep)
    tmp.replace(p)
    _COUNTS[str(p)] = len(keep)


def append(state_dir: Path | str, name: str, entry: dict) -> None:
    """One line, with ``t`` now unless given; the log cut back when it holds ``KEEP`` + ``SLACK``."""
    p = path(state_dir, name)
    line = json.dumps({"t": round(time.time(), 3), **entry}, ensure_ascii=False, default=str) + "\n"
    try:
        with _LOCK:
            p.parent.mkdir(parents=True, exist_ok=True)
            key = str(p)
            if key not in _COUNTS:
                _COUNTS[key] = _lines(p)
            with p.open("a", encoding="utf-8") as f:
                f.write(line)
            _COUNTS[key] += 1
            if _COUNTS[key] > KEEP + SLACK:
                _COUNTS[key] = _lines(p)          # other processes append too
                if _COUNTS[key] > KEEP + SLACK:
                    _cut(p)
    except OSError:
        pass


def _read(state_dir: Path | str, name: str) -> list[dict]:
    try:
        raw = path(state_dir, name).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    out = []
    for line in raw:
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def lines_since(state_dir: Path | str, name: str, since: float) -> list[dict]:
    """The lines logged at or after ``since``, oldest first (read from the end back to it)."""
    out: list[dict] = []
    for x in reversed(_read(state_dir, name)):
        if (x.get("t") or 0) < since:
            break
        out.append(x)
    return out[::-1]


def last(state_dir: Path | str, name: str, n: int = 20) -> list[dict]:
    """The newest ``n`` lines, oldest first."""
    try:
        with path(state_dir, name).open("rb") as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - 2000 * (n + 1)))
            raw = f.read().decode("utf-8", "replace").splitlines()[-n:]
    except OSError:
        return []
    out = []
    for line in raw:
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def midnight(now: float | None = None) -> float:
    d = datetime.fromtimestamp(time.time() if now is None else now, UTC)
    return d.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()


def today(state_dir: Path | str, name: str, now: float | None = None) -> dict:
    """Today's (UTC) requests in the log: those sent, by who asked, and those refused unsent."""
    since = midnight(now)
    sent, refused, by = 0, 0, {}
    for x in _read(state_dir, name):
        if (x.get("t") or 0) < since:
            continue
        if x.get("sent") is False:
            refused += 1
            continue
        sent += 1
        by[x.get("by") or "?"] = by.get(x.get("by") or "?", 0) + 1
    return {"sent": sent, "refused": refused, "by": by}


def answer_size(data) -> tuple[int | None, int | None]:
    """(series, points) of an answer: a query's results and their samples; a list's length."""
    if isinstance(data, dict) and isinstance(data.get("result"), list):
        res = data["result"]
        if data.get("resultType") == "scalar":
            return 1, 1
        pts = sum(len(r.get("values") or []) + len(r.get("histograms") or []) + (1 if "value" in r else 0)
                  for r in res if isinstance(r, dict))
        return len(res), pts
    if isinstance(data, list):
        return len(data), None
    return None, None


def asked_about(form: dict | None) -> tuple[str | list | None, list | None, float | None]:
    """(query, window, step) of a request's form: its query, its match[] or the metric it names."""
    if not form:
        return None, None, None
    q = form.get("query") or form.get("match[]") or form.get("metric")
    win = ([_num(form["start"]), _num(form.get("end"))] if "start" in form else [_num(form["time"])] if "time" in form else None)
    return q, win, _num(form.get("step"))


def _num(v) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None
