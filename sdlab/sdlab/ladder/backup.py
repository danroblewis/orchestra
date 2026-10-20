"""Backups of the result store (scripts/sdlab-backup.sh; `sdlab-ladder backup` and `sdlab-ladder restore`).

    snapshot(dest=None) -> {file, rows, bytes, raw_bytes, seconds, snapshot_seconds, compress_seconds}
        A consistent copy of results.sqlite made with SQLite's online backup API (Connection.backup: the
        watcher keeps writing meanwhile; the copy is the store as of one moment), compressed with zstd
        (gzip -9 where zstd is missing) to DEST/results-YYYYmmdd-HHMMSS.sqlite.zst, with a sidecar
        .json holding its row counts and times. The code patches results refer to
        ($SDLAB_LADDER_CACHE/code/*.patch) are copied to DEST/code/ (never deleted there). Generated
        case data is not backed up: it is made again, deterministically.
    rotate(dest=None, now=None) -> [removed files]
        Keeps every snapshot of the last 24 hours, the newest of each day for 14 days, the newest of each
        week for 8 weeks; removes the rest.
    restore(file, to) -> {path, rows}
        Decompresses a snapshot to `to` (refusing to overwrite the live store, or any file, unless
        replace=True) and checks its row counts against the sidecar.

DEST defaults to $SDLAB_BACKUPS or ~/.sdlab/backups.
"""

from __future__ import annotations

import gzip
import json
import os
import shutil
import sqlite3
import subprocess
import time
from datetime import datetime, timedelta
from pathlib import Path

from . import store

TABLES = ("results", "runs")


def root() -> Path:
    return Path(os.environ.get("SDLAB_BACKUPS") or Path.home() / ".sdlab" / "backups")


def _counts(path: Path) -> dict:
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        have = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        return {t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in TABLES if t in have}
    finally:
        con.close()


def _zstd() -> str | None:
    return shutil.which("zstd")


def snapshot(dest: Path | None = None) -> dict:
    dest = Path(dest or root())
    dest.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    raw = dest / f".results-{stamp}.sqlite.part"
    t0 = time.perf_counter()
    src = sqlite3.connect(store.path(), timeout=60)
    out = sqlite3.connect(raw)
    try:
        src.backup(out)                                  # one step: a read transaction, so the copy is one moment's store
        out.execute("PRAGMA journal_mode=DELETE")         # one self-contained file (the store is WAL)
    finally:
        out.close()
        src.close()
    t1 = time.perf_counter()
    rows = _counts(raw)
    for extra in ("-wal", "-shm"):
        Path(str(raw) + extra).unlink(missing_ok=True)
    raw_bytes = raw.stat().st_size
    z = _zstd()
    final = dest / f"results-{stamp}.sqlite.{'zst' if z else 'gz'}"
    if z:
        subprocess.run([z, "-q", "-T0", f"-{os.environ.get('SDLAB_BACKUP_LEVEL', '10')}", "--rm", "-o", str(final), str(raw)], check=True)
    else:
        with open(raw, "rb") as f, gzip.open(final, "wb", compresslevel=9) as g:
            shutil.copyfileobj(f, g, 1 << 20)
        raw.unlink()
    t2 = time.perf_counter()
    code = store.path().parent / "code"
    if code.is_dir():
        (dest / "code").mkdir(exist_ok=True)
        for p in code.glob("*.patch"):
            if not (dest / "code" / p.name).exists():
                shutil.copy2(p, dest / "code" / p.name)
    info = {"file": final.name, "at": stamp, "rows": rows, "bytes": final.stat().st_size, "raw_bytes": raw_bytes,
            "snapshot_seconds": round(t1 - t0, 1), "compress_seconds": round(t2 - t1, 1), "seconds": round(t2 - t0, 1)}
    final.with_name(final.name + ".json").write_text(json.dumps(info, indent=1))
    return {**info, "file": str(final)}


def snapshots(dest: Path | None = None) -> list[Path]:
    dest = Path(dest or root())
    return sorted(p for p in dest.glob("results-*.sqlite.*") if not p.name.endswith(".json"))


def _when(p: Path) -> datetime:
    return datetime.strptime(p.name.split(".")[0][len("results-"):], "%Y%m%d-%H%M%S")


def rotate(dest: Path | None = None, now: datetime | None = None) -> list[str]:
    now = now or datetime.now()
    keep: set[Path] = set()
    days: dict = {}
    weeks: dict = {}
    for p in snapshots(dest):
        w = _when(p)
        age = now - w
        if age <= timedelta(hours=24):
            keep.add(p)
        elif age <= timedelta(days=14):
            d = w.date()
            if d not in days or _when(days[d]) < w:
                days[d] = p
        elif age <= timedelta(weeks=8):
            k = w.isocalendar()[:2]
            if k not in weeks or _when(weeks[k]) < w:
                weeks[k] = p
    keep |= set(days.values()) | set(weeks.values())
    gone = []
    for p in snapshots(dest):
        if p not in keep:
            p.unlink()
            p.with_name(p.name + ".json").unlink(missing_ok=True)
            gone.append(p.name)
    return gone


def restore(file: str | Path, to: str | Path, replace: bool = False) -> dict:
    file, to = Path(file), Path(to)
    if to.resolve() == store.path().resolve() and not replace:
        raise SystemExit(f"{to} is the live store: stop the watcher and the server, then pass --replace")
    if to.exists() and not replace:
        raise SystemExit(f"{to} exists (pass --replace to overwrite it)")
    tmp = to.with_name(to.name + ".part")
    if file.suffix == ".zst":
        subprocess.run([_zstd() or "zstd", "-q", "-d", "-f", "-o", str(tmp), str(file)], check=True)
    else:
        with gzip.open(file, "rb") as g, open(tmp, "wb") as f:
            shutil.copyfileobj(g, f, 1 << 20)
    rows = _counts(tmp)
    side = file.with_name(file.name + ".json")
    want = json.loads(side.read_text())["rows"] if side.exists() else None
    if want is not None and rows != want:
        tmp.unlink()
        raise SystemExit(f"{file}: restored row counts {rows} differ from the backup's {want}")
    for extra in ("-wal", "-shm"):
        Path(str(to) + extra).unlink(missing_ok=True)
    tmp.replace(to)
    return {"path": str(to), "rows": rows, "checked": want is not None}


def main(a) -> int:
    if a.command == "backup":
        got = snapshot(a.dir)
        gone = rotate(a.dir)
        print(f"backup: {got['file']}: {got['rows']} rows, {got['raw_bytes'] / 1e6:.0f} MB -> {got['bytes'] / 1e6:.0f} MB in {got['seconds']} s"
              f" (snapshot {got['snapshot_seconds']} s, compress {got['compress_seconds']} s); rotated out {len(gone)}")
        return 0
    if a.file in (None, "latest"):
        have = snapshots(a.dir)
        if not have:
            raise SystemExit("no backups")
        a.file = str(have[-1])
    got = restore(a.file, a.to or Path(a.file).with_suffix("").with_suffix(".restored.sqlite"), a.replace)
    print(f"restore: {a.file} -> {got['path']}: {got['rows']} rows" + (" (the same as when it was taken)" if got["checked"] else ""))
    return 0
