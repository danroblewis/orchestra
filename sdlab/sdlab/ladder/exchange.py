"""Results moving between machines: `sdlab-ladder export` on the machine that ran them, `sdlab-ladder
import FILE` on the one that keeps the source-of-truth store (node2 -> mac; machines.py).

    export(since_id=None, out=None) -> {path, count, since_id, upto_id, patches}
        The results this machine made (machine = here(), or none: made before 2026-10-19; never rows it
        imported itself) with id > since_id, by default since the last export (recorded in this store's
        `exports` table), to a gzipped JSONL file: a header line {kind: header, format, machine,
        exported_at, since_id, upto_id, head (git HEAD here), runs (the newest runs, as the runs panel
        shows them: the watcher's batch, its backlog and counts)}, one line per result {kind: result,
        every column of the results table but latest, with id: its id here}, one line per code patch the
        results refer to {kind: patch, hash, text} ($SDLAB_LADDER_CACHE/code/<hash>.patch), and an end
        line {kind: end, count} (an import refuses a file without it: a copy cut short).
    load(path) -> {header, results, patches}
    import_file(path) -> {machine, added, skipped, latest, patches}
        Adds the results with new ids here, machine and remote_id (their id there) set. A row whose
        (machine, remote_id) is already here, or that this machine made itself, is skipped, so importing
        a file twice adds nothing. A row becomes its cell's latest only when its `at` is newer than the
        latest here (ties keep the row already here); otherwise it is stored with latest = 0. Nothing is
        deleted or changed but the latest flag of a superseded row. The header is kept in the `machines`
        table (the runs panel shows the other machine's watcher from it). Patches are written if missing.
    high_water(machine) -> the newest remote id imported from that machine (0: none), what
        scripts/sdlab-sync.sh passes to `export --since-id` there, so a file lost on the way is sent again.
    remotes() -> [{name, imported_at, exported_at, upto_id, header, results}]

Results made by older code need nothing special: their hashes differ from the current ones, so
store.staleness marks them stale as it marks any local row.
"""

from __future__ import annotations

import gzip
import json
import sqlite3
import subprocess
from pathlib import Path

from . import store
from .data import cache_root
from .machines import here

FORMAT = 1
COLUMNS = ("id", "case_id", "case_hash", "variant", "strategy", "strategy_hash", "score_hash", "at", "status", "seconds", "error",
           "scores", "found", "code_commit", "code_dirty", "score_seconds", "wall_seconds", "wait_seconds", "run_id", "machine")
TABLES = """
CREATE TABLE IF NOT EXISTS exports (id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL, since_id INTEGER, upto_id INTEGER,
                                    count INTEGER, file TEXT);
CREATE TABLE IF NOT EXISTS machines (name TEXT PRIMARY KEY, imported_at TEXT, exported_at TEXT, upto_id INTEGER, header TEXT);
"""


def _head() -> str | None:
    try:
        r = subprocess.run(["git", "rev-parse", "HEAD"], cwd=Path(__file__).parent, capture_output=True, text=True, timeout=10)
        return r.stdout.strip() if r.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None


def _runs_brief() -> list[dict]:
    from . import runs
    import time
    now = time.time()
    return [runs._brief(r, now) for r in store.runs(10)]


def export(since_id: int | None = None, out: str | Path | None = None) -> dict:
    me = here()
    with store.connect() as con:
        con.executescript(TABLES)
        if since_id is None:
            r = con.execute("SELECT upto_id FROM exports ORDER BY id DESC LIMIT 1").fetchone()
            since_id = int(r[0]) if r and r[0] is not None else 0
        top = con.execute("SELECT MAX(id) FROM results").fetchone()[0] or 0
        path = Path(out) if out else cache_root() / "exports" / f"{me}-{since_id}-{top}.jsonl.gz"
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".part")
        header = {"kind": "header", "format": FORMAT, "machine": me, "exported_at": store.now(), "since_id": since_id,
                  "upto_id": top, "head": _head(), "runs": _runs_brief()}
        n, patches = 0, set()
        with gzip.open(tmp, "wt", compresslevel=6) as f:
            f.write(json.dumps(header) + "\n")
            cur = con.execute(f"SELECT {', '.join(COLUMNS)} FROM results WHERE id > ? AND id <= ? AND remote_id IS NULL"
                              " AND (machine IS NULL OR machine = ?) ORDER BY id", (since_id, top, me))
            for r in cur:
                row = dict(zip(COLUMNS, r))
                row["machine"] = row["machine"] or me
                row["kind"] = "result"
                if row["code_dirty"]:
                    patches.add(row["code_dirty"])
                f.write(json.dumps(row) + "\n")
                n += 1
            for h in sorted(patches):
                p = cache_root() / "code" / f"{h}.patch"
                if p.exists():
                    f.write(json.dumps({"kind": "patch", "hash": h, "text": p.read_text()}) + "\n")
            f.write(json.dumps({"kind": "end", "count": n}) + "\n")
        tmp.replace(path)
        con.execute("INSERT INTO exports (at, since_id, upto_id, count, file) VALUES (?, ?, ?, ?, ?)",
                    (header["exported_at"], since_id, top, n, str(path)))
    return {"path": str(path), "count": n, "since_id": since_id, "upto_id": top, "patches": len(patches)}


def load(path: str | Path) -> dict:
    header, results, patches, end = None, [], {}, None
    with gzip.open(path, "rt") as f:
        for line in f:
            x = json.loads(line)
            k = x.pop("kind", None)
            if k == "header":
                header = x
            elif k == "result":
                results.append(x)
            elif k == "patch":
                patches[x["hash"]] = x["text"]
            elif k == "end":
                end = x
    if header is None or end is None or end.get("count") != len(results):
        raise ValueError(f"{path}: not a whole export (no header, no end line, or the count differs): not imported")
    if header.get("format") != FORMAT:
        raise ValueError(f"{path}: export format {header.get('format')}, this code reads {FORMAT}")
    return {"header": header, "results": results, "patches": patches}


INSERT = ("INSERT INTO results (case_id, case_hash, variant, strategy, strategy_hash, score_hash, at, latest, status, seconds, error, scores,"
          " found, code_commit, code_dirty, score_seconds, wall_seconds, wait_seconds, run_id, machine, remote_id)"
          " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?)")


def import_file(path: str | Path) -> dict:
    got = load(path)
    h = got["header"]
    me = here()
    for k, text in got["patches"].items():
        p = cache_root() / "code" / f"{k}.patch"
        if not p.exists():
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text)
    added = skipped = became = 0
    with store.connect() as con:
        con.executescript(TABLES)
        con.execute("BEGIN IMMEDIATE")
        for r in got["results"]:
            machine = r.get("machine") or h["machine"]
            if machine == me or con.execute("SELECT 1 FROM results WHERE machine = ? AND remote_id = ?", (machine, r["id"])).fetchone():
                skipped += 1
                continue
            cur = con.execute("SELECT id, at FROM results WHERE case_id = ? AND variant = ? AND strategy = ? AND latest = 1",
                              (r["case_id"], r["variant"], r["strategy"])).fetchall()
            newest = max((x["at"] for x in cur), default=None)
            latest = newest is None or r["at"] > newest
            if latest:
                con.execute("UPDATE results SET latest = 0 WHERE case_id = ? AND variant = ? AND strategy = ? AND latest = 1",
                            (r["case_id"], r["variant"], r["strategy"]))
            con.execute(INSERT, (r["case_id"], r["case_hash"], r["variant"], r["strategy"], r["strategy_hash"], r["score_hash"], r["at"],
                                 int(latest), r["status"], r["seconds"], r["error"], r["scores"], r["found"], r["code_commit"],
                                 r["code_dirty"], r["score_seconds"], r["wall_seconds"], r["wait_seconds"], machine, r["id"]))
            added += 1
            became += latest
        con.execute("INSERT INTO machines (name, imported_at, exported_at, upto_id, header) VALUES (?, ?, ?, ?, ?)"
                    " ON CONFLICT(name) DO UPDATE SET imported_at = excluded.imported_at, exported_at = excluded.exported_at,"
                    " upto_id = MAX(COALESCE(machines.upto_id, 0), excluded.upto_id), header = excluded.header",
                    (h["machine"], store.now(), h["exported_at"], h["upto_id"], json.dumps(h)))
    return {"machine": h["machine"], "added": added, "skipped": skipped, "latest": became, "patches": len(got["patches"]),
            "since_id": h["since_id"], "upto_id": h["upto_id"]}


def high_water(machine: str) -> int:
    with store.connect(readonly=True) as con:
        return int(con.execute("SELECT MAX(remote_id) FROM results WHERE machine = ? AND remote_id IS NOT NULL", (machine,)).fetchone()[0] or 0)


def remotes() -> list[dict]:
    """The machines results were imported from, with their last export's header and how many results came."""
    with store.connect(readonly=True) as con:
        try:
            rows = con.execute("SELECT * FROM machines ORDER BY name").fetchall()
        except sqlite3.OperationalError:                 # no import yet
            return []
        out = []
        for r in rows:
            n = con.execute("SELECT COUNT(*) FROM results WHERE machine = ? AND remote_id IS NOT NULL", (r["name"],)).fetchone()[0]
            out.append({"name": r["name"], "imported_at": r["imported_at"], "exported_at": r["exported_at"], "upto_id": r["upto_id"],
                        "header": json.loads(r["header"]) if r["header"] else None, "results": n})
        return out
