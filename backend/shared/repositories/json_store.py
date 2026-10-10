"""Low-level flat-JSON persistence behind the Repository pattern.

Stores one collection as a key on a single JSON document. All reads and writes
are atomic (write to a temp file, then rename) so a crash mid-write never
corrupts the store. This is the only place that touches the file system, so
swapping in a database later means only this class changes.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


class JsonStore:
    """A single JSON document with named collections, written atomically."""

    def __init__(self, path: str | os.PathLike[str]):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self._write({"_collections": {}})

    def _read(self) -> dict[str, Any]:
        with open(self.path, "r", encoding="utf-8") as f:
            raw = f.read().strip()
        if not raw:
            return {"_collections": {}}
        return json.loads(raw)

    def _write(self, doc: dict[str, Any]) -> None:
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(doc, f, indent=2)
        os.replace(tmp, self.path)  # atomic on POSIX and Windows

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
