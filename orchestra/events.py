"""Append-only event log plus in-process subscribers. SPEC.md section 6.5."""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any, Callable

from .model import now


class Events:
    def __init__(self, path: Path):
        self.path = path
        self._subs: list[Callable[[dict], None]] = []
        self._lock = threading.Lock()

    def subscribe(self, fn: Callable[[dict], None]) -> None:
        self._subs.append(fn)

    def emit(self, type: str, **data: Any) -> dict:
        ev = {"ts": now(), "type": type, **data}
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(ev) + "\n")
        for fn in list(self._subs):
            try:
                fn(ev)
            except Exception:
                pass
        return ev

    def read(self, since: int = 0, limit: int = 500) -> tuple[list[dict], int]:
        """Return (events, next_offset) where offsets are line numbers."""
        if not self.path.exists():
            return [], 0
        out: list[dict] = []
        n = 0
        with self.path.open(encoding="utf-8") as f:
            for n, line in enumerate(f, start=1):
                if n <= since:
                    continue
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return out[-limit:], n
