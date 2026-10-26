"""The default bus: one JSONL file, one event per line. Offsets are line numbers.

Several processes (the host, the machines, the web server) append to the same file;
each append is one write of one line in append mode, so lines never interleave."""

from __future__ import annotations

import json
import threading
from pathlib import Path


class FileBus:
    name = "file"

    def __init__(self, path: Path):
        self.path = Path(path)
        self._lock = threading.Lock()

    def append(self, event: dict) -> None:
        line = json.dumps(event) + "\n"
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as f:
                f.write(line)

    def read(self, since: int = 0, limit: int = 500) -> tuple[list[dict], int]:
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
        return (out[-limit:] if limit else []), n

    def end(self) -> int:
        if not self.path.exists():
            return 0
        with self.path.open("rb") as f:
            return sum(1 for _ in f)

    def close(self) -> None:
        pass
