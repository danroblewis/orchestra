"""The default bus: one JSONL file, one event per line. Offsets are line numbers.

Several processes (the host, the machines, the web server) append to the same file;
each append is one write of one line in append mode, so lines never interleave.

A long log is not read from its start on every call: the bus remembers how many complete lines it
has counted and the byte where they end, with a checkpoint every ``CHECKPOINT`` lines, so ``end``
reads only what was appended since and ``read(since)`` starts at the checkpoint at or before
``since``. What it remembers is dropped when the file shrank, was replaced, or no longer ends, at
the remembered byte, with the bytes it remembered there. Offsets and what is returned are the same
as reading from the start: a malformed line is skipped but counted, and a last line still being
written counts as a line."""

from __future__ import annotations

import bisect
import json
import os
import threading
from pathlib import Path

CHECKPOINT = 4096          # lines between remembered (line, byte) positions
TAIL = 64                  # bytes before the remembered end that must still be there


class FileBus:
    name = "file"

    def __init__(self, path: Path):
        self.path = Path(path)
        self._lock = threading.Lock()
        self._index_lock = threading.Lock()
        self._forget()

    def _forget(self) -> None:
        self._stamp: tuple | None = None            # (inode, size, mtime_ns) when last counted
        self._lines, self._pos, self._tail = 0, 0, b""
        self._marks: list[tuple[int, int]] = [(0, 0)]   # (complete lines before, byte where they end)
        self._partial = False

    def append(self, event: dict) -> None:
        line = json.dumps(event) + "\n"
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as f:
                f.write(line)

    def _count(self) -> int | None:
        """Bring the remembered count up to the file's end; returns the number of lines (a last
        line still being written included), or None when there is no file."""
        try:
            st = os.stat(self.path)
        except FileNotFoundError:
            with self._index_lock:
                self._forget()
            return None
        stamp = (st.st_ino, st.st_size, st.st_mtime_ns)
        with self._index_lock:
            if stamp == self._stamp:
                return self._lines + self._partial
            if self._stamp is not None and (st.st_ino != self._stamp[0] or st.st_size < self._pos):
                self._forget()
            with self.path.open("rb") as f:
                if self._tail:
                    f.seek(self._pos - len(self._tail))
                    if f.read(len(self._tail)) != self._tail:      # rewritten in place: count again
                        self._forget()
                f.seek(self._pos)
                lines, pos, partial = self._lines, self._pos, False
                for line in f:
                    if not line.endswith(b"\n"):
                        partial = True                  # still being written: counted, not remembered
                        break
                    lines += 1
                    pos += len(line)
                    if lines % CHECKPOINT == 0:
                        self._marks.append((lines, pos))
                if pos != self._pos:
                    f.seek(max(0, pos - TAIL))
                    self._tail = f.read(pos - max(0, pos - TAIL))
            self._lines, self._pos, self._partial, self._stamp = lines, pos, partial, stamp
            return lines + partial

    def read(self, since: int = 0, limit: int = 500) -> tuple[list[dict], int]:
        if self._count() is None:
            return [], 0
        with self._index_lock:
            start, at = self._marks[bisect.bisect_right(self._marks, (since, float("inf"))) - 1]
        out: list[dict] = []
        n = start
        with self.path.open("rb") as f:
            f.seek(at)
            for n, line in enumerate(f, start=start + 1):
                if n <= since:
                    continue
                try:
                    out.append(json.loads(line))
                except ValueError:
                    continue
        return (out[-limit:] if limit else []), n

    def end(self) -> int:
        return self._count() or 0

    def close(self) -> None:
        pass
