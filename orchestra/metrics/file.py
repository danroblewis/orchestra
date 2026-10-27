"""The default metrics store: one JSONL file, one point per line. Fine for one machine and
Orchestra's volumes (thousands of points a day); reads scan the file."""

from __future__ import annotations

import json
import threading
from pathlib import Path

from . import Point, step_sample


def _matches(rec: dict, series: str, labels: dict[str, str] | None) -> bool:
    return rec["s"] == series and all(rec["l"].get(k) == v for k, v in (labels or {}).items())


class FileMetrics:
    name = "file"

    def __init__(self, path: Path):
        self.path = Path(path)
        self._lock = threading.Lock()

    def _records(self):
        if not self.path.exists():
            return
        with self.path.open(encoding="utf-8") as f:
            for line in f:
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue

    def write(self, points: list[Point]) -> None:
        if not points:
            return
        lines = "".join(json.dumps({"s": p.series, "l": p.labels, "t": p.ts, "v": p.value}) + "\n" for p in points)
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as f:
                f.write(lines)

    def raw(self, series, labels=None, start=None, end=None):
        pts = [(r["t"], r["v"]) for r in self._records() if _matches(r, series, labels)
               and (start is None or r["t"] >= start) and (end is None or r["t"] <= end)]
        return sorted(pts, key=lambda p: p[0])

    def range(self, series, labels, start, end, step):
        return step_sample(self.raw(series, labels, None, end), start, end, step)

    def latest(self, series, labels=None):
        pts = self.raw(series, labels)
        return pts[-1] if pts else None

    def series(self, prefix="", labels=None):
        seen: dict[tuple, tuple[str, dict]] = {}
        for r in self._records():
            if r["s"].startswith(prefix) and all(r["l"].get(k) == v for k, v in (labels or {}).items()):
                seen.setdefault((r["s"], tuple(sorted(r["l"].items()))), (r["s"], r["l"]))
        return sorted(seen.values(), key=lambda x: (x[0], sorted(x[1].items())))

    def dump(self, prefix="", labels=None):
        groups: dict[tuple, tuple[str, dict, list]] = {}
        for r in self._records():
            if r["s"].startswith(prefix) and all(r["l"].get(k) == v for k, v in (labels or {}).items()):
                g = groups.setdefault((r["s"], tuple(sorted(r["l"].items()))), (r["s"], r["l"], []))
                g[2].append((r["t"], r["v"]))
        return [(n, lab, sorted(pts, key=lambda p: p[0])) for n, lab, pts in sorted(groups.values(), key=lambda g: (g[0], sorted(g[1].items())))]

    def delete(self, series_prefix, labels=None):
        with self._lock:
            keep = [r for r in self._records()
                    if not (r["s"].startswith(series_prefix) and all(r["l"].get(k) == v for k, v in (labels or {}).items()))]
            if self.path.exists():
                tmp = self.path.with_suffix(".tmp")
                tmp.write_text("".join(json.dumps(r) + "\n" for r in keep), encoding="utf-8")
                tmp.replace(self.path)

    def close(self) -> None:
        pass
