"""The declared layer's append-only JSON-lines files (``journal.jsonl``, ``requests.jsonl``): one
object a line. An append first ends a torn last line (a write cut short), so it never swallows the
next record; a line that does not parse is passed over on read."""

from __future__ import annotations

import json
from pathlib import Path


def append(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a+b") as fh:
        fh.seek(0, 2)
        if fh.tell():
            fh.seek(-1, 2)
            if fh.read(1) != b"\n":
                fh.write(b"\n")
        fh.write((json.dumps(record) + "\n").encode("utf-8"))


def records(path: Path) -> list[dict]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    out = []
    for line in text.splitlines():
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if isinstance(r, dict):
            out.append(r)
    return out


def rewrite(path: Path, keep) -> None:
    """Rewrite the file with only the records ``keep`` accepts (an unparsable line is dropped)."""
    kept = [r for r in records(path) if keep(r)]
    tmp = path.with_suffix(".tmp")
    tmp.write_text("".join(json.dumps(r) + "\n" for r in kept), encoding="utf-8")
    tmp.replace(path)
