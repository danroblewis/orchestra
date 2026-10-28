"""What was read of a source, kept, so the next read of a sliding window asks only for what is new.

Discovery reads the same hour every few minutes, and the web server the same hour every few
seconds: all but the newest steps were read before. A ``ReadCache`` keeps, per query on its grid
(an evaluated query: ``q|<step>|<expr>``) or per selector (raw samples: ``s|<selector>``), each
result series' points and the stretch ``[a, b]`` they cover. A read of ``[start, end]`` then asks
the store only for ``[b − resettle, end]`` (``plan``), aligned to the grid, and splices the answer
in (``put``): the points it covers are replaced, the others kept. The re-read stretch
(``resettle``: two steps, the source's ``settle``, and at least ``RESETTLE`` seconds) takes in
samples written late. Everything is read whole again:
- when the cache does not reach back to the window's start, or does not meet its end;
- every ``REFILL`` seconds (an hour), so samples written later than the re-read stretch are not
  missed for longer than that;
- when the source's store or definitions change (a new query is a new entry; another store, a
  file of no use).

A read the store **refused for its size** is remembered (``refuse``) and not asked again for
``REFILL`` seconds (``refusal``): a definition over the store's per-query limit costs one refusal an
hour, not one a round, and reads as failed meanwhile, with why.

The host's discovery keeps its cache in ``<state>/sources/<name>.reads.json`` (``load``/``save``),
and every other reader of the project (the web server, the judge, ``orchestra sd show``) takes
what is there into its own (``absorb``) before asking the store: they read the host's latest
discovery first, and the store only for what is newer. A read that fails leaves the cache as it
was. Points before the window's start are dropped (``trim``), and entries no read asked for are
not saved."""

from __future__ import annotations

import json
import math
import os
import tempfile
import threading
import time
from pathlib import Path

from . import Labels, Points

RESETTLE = 120.0             # seconds re-read at the end of what is kept, at least: samples written late
REFILL = 3600.0              # a kept entry is read whole again this long after it was


def _key(labels: Labels) -> str:
    return json.dumps(sorted(labels.items()))


class Entry:
    def __init__(self, a: float, b: float, rows: dict[str, tuple[Labels, dict[float, float]]], filled: float):
        self.a, self.b, self.rows, self.filled = a, b, rows, filled

    def to_json(self) -> dict:
        return {"a": self.a, "b": self.b, "filled": self.filled,
                "rows": [[labels, [[t, v] for t, v in sorted(pts.items())]] for labels, pts in self.rows.values()]}

    @classmethod
    def from_json(cls, d: dict) -> Entry:
        rows = {}
        for labels, pts in d["rows"]:
            rows[_key(labels)] = (dict(labels), {float(t): float(v) for t, v in pts})
        return cls(float(d["a"]), float(d["b"]), rows, float(d.get("filled") or 0.0))


class ReadCache:
    def __init__(self, store: str = "", path: Path | None = None, *, clock=time.time):
        self.store, self.path = store, Path(path) if path else None
        self.entries: dict[str, Entry] = {}
        self.refused: dict[str, dict] = {}     # key -> {"why", "at"}: refused for its size
        self.used: set[str] = set()
        self._clock = clock
        self._lock = threading.Lock()
        self._absorbed: float | None = None

    # -- what to ask the store for ------------------------------------------------------------
    def plan(self, key: str, start: float, end: float, step: float, resettle: float = 0.0) -> tuple[float, float] | None:
        """The stretch of ``[start, end]`` to read for ``key`` (None: nothing; it is all kept)."""
        with self._lock:
            self.used.add(key)
            e = self.entries.get(key)
            if (e is None or e.a > start + 1e-6 or e.b < start or self._clock() - e.filled > REFILL):
                return start, end
            if e.b >= end - 1e-6:
                return None
            back = max(2 * step, resettle, RESETTLE)
            a = max(start, math.floor((e.b - back) / step) * step) if step > 0 else max(start, e.b - back)
            return a, end

    def refusal(self, key: str) -> str | None:
        """Why the store refused ``key`` for its size, when it did within ``REFILL``."""
        with self._lock:
            self.used.add(key)
            r = self.refused.get(key)
            if r is None or self._clock() - r["at"] > REFILL:
                return None
            return (f"{r['why']} (refused at {time.strftime('%H:%M', time.localtime(r['at']))}; not asked again before "
                    f"{time.strftime('%H:%M', time.localtime(r['at'] + REFILL))})")

    def refuse(self, key: str, why: str) -> None:
        with self._lock:
            self.used.add(key)
            self.refused[key] = {"why": why, "at": self._clock()}

    def put(self, key: str, rows: list[tuple[Labels, Points]], a: float, b: float, *, whole: bool = False) -> None:
        """What a read of ``[a, b]`` returned, spliced in (``whole``: it was the window's full read)."""
        with self._lock:
            e = self.entries.get(key)
            if e is None or whole or a > e.b + 1e-6 or b < e.a - 1e-6:
                e = self.entries[key] = Entry(a, b, {}, self._clock())
            else:
                for _, pts in e.rows.values():
                    for t in [t for t in pts if a - 1e-6 <= t <= b + 1e-6]:
                        del pts[t]
                e.a, e.b = min(e.a, a), max(e.b, b)
            for labels, pts in rows:
                got = e.rows.setdefault(_key(labels), (dict(labels), {}))[1]
                got.update((float(t), float(v)) for t, v in pts if a - 1e-6 <= t <= b + 1e-6)

    def get(self, key: str, start: float, end: float) -> list[tuple[Labels, Points]]:
        """The kept series of ``key`` in ``[start, end]`` (those with a point in it)."""
        with self._lock:
            e = self.entries.get(key)
            if e is None:
                return []
            out = []
            for labels, pts in e.rows.values():
                p = sorted((t, v) for t, v in pts.items() if start - 1e-6 <= t <= end + 1e-6)
                if p:
                    out.append((dict(labels), p))
            return out

    def trim(self, before: float) -> None:
        """Points before ``before`` dropped; series left with none, too."""
        with self._lock:
            for e in self.entries.values():
                if e.a < before:
                    for k, (_, pts) in list(e.rows.items()):
                        for t in [t for t in pts if t < before]:
                            del pts[t]
                        if not pts:
                            del e.rows[k]
                    e.a = max(e.a, before)

    # -- the host's file ----------------------------------------------------------------------
    def load(self) -> None:
        """The entries the file keeps, when it is of this store."""
        if self.path is None:
            return
        try:
            d = json.loads(self.path.read_text())
        except (OSError, ValueError):
            return
        if d.get("store") != self.store:
            return
        with self._lock:
            for k, v in (d.get("entries") or {}).items():
                try:
                    self.entries[k] = Entry.from_json(v)
                except (KeyError, TypeError, ValueError):
                    continue
            self.refused.update({k: v for k, v in (d.get("refused") or {}).items() if isinstance(v, dict) and "at" in v})

    def save(self) -> None:
        """The entries read this time, written whole and moved into place."""
        if self.path is None:
            return
        with self._lock:
            body = json.dumps({"store": self.store, "at": self._clock(),
                               "entries": {k: e.to_json() for k, e in self.entries.items() if k in self.used},
                               "refused": {k: r for k, r in self.refused.items() if k in self.used and self._clock() - r["at"] <= REFILL}})
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=f".{self.path.name}.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as fh:
                fh.write(body)
            os.replace(tmp, self.path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise

    def absorb(self, path: Path) -> None:
        """What the host's file keeps (``path``), taken in where it reaches further than what is
        kept here; read again only when the file changed."""
        try:
            mtime = path.stat().st_mtime
        except OSError:
            return
        if mtime == self._absorbed:
            return
        self._absorbed = mtime
        other = ReadCache(self.store, path)
        other.load()
        with self._lock:
            for k, r in other.refused.items():
                if r["at"] > self.refused.get(k, {}).get("at", 0):
                    self.refused[k] = r
        for k, e in other.entries.items():
            mine = self.entries.get(k)
            if mine is None or (e.b > mine.b and e.a <= mine.b + 1e-6):
                rows = [(labels, sorted(pts.items())) for labels, pts in e.rows.values()]
                self.put(k, rows, e.a, e.b, whole=mine is None)
                with self._lock:
                    self.entries[k].filled = max(self.entries[k].filled, e.filled) if mine is not None else e.filled
