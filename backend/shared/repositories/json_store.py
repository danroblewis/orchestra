"""Low-level flat-JSON persistence behind the Repository pattern.

Stores one collection as a key on a single JSON document. All reads and writes
are atomic (write to a temp file, then rename) so a crash mid-write never
corrupts the store. This is the only place that touches the file system, so
swapping in a database later means only this class changes.
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any


class JsonStore:
    """A single JSON document with named collections, written atomically."""

    def __init__(self, path: str | os.PathLike[str]):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Serializes writes so concurrent writers (e.g. a collaborative run with
        # several agent threads) never clobber each other's ``.tmp`` file.
        self._lock = threading.Lock()
        if not self.path.exists():
            self._write({"_collections": {}})

    def _read(self) -> dict[str, Any]:
        with open(self.path, "r", encoding="utf-8") as f:
            raw = f.read().strip()
        if not raw:
            return {"_collections": {}}
        return json.loads(raw)

    def _unique_tmp(self) -> Path:
        """Return a write-unique temp path so concurrent writers don't clash."""
        import time as _time
        return self.path.with_name(
            f".tmp-{os.getpid()}-{_time.time_ns()}-{id(self)}.json"
        )

    def _write(self, doc: dict[str, Any]) -> None:
        with self._lock:
            tmp = self._unique_tmp()
            try:
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(doc, f, indent=2)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp, self.path)  # atomic on POSIX and Windows
            finally:
                if tmp.exists():
                    try:
                        tmp.unlink()
                    except OSError:
                        pass

    def get(self, collection: str) -> list[Any]:
        doc = self._read()
        return doc.get("_collections", {}).get(collection, [])

    def set(self, collection: str, values: list[Any]) -> None:
        doc = self._read()
        doc.setdefault("_collections", {})[collection] = values
        self._write(doc)

    def append(self, collection: str, value: Any) -> None:
        values = self.get(collection)
        values.append(value)
        self.set(collection, values)
