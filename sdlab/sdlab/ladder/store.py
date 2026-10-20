"""The ladder's results: SQLite at $SDLAB_LADDER_CACHE/results.sqlite (default
~/.cache/sdlab/ladder/results.sqlite).

results: one row per run of a strategy on a case's variant, never deleted. A row records the case's
hash, the strategy's hash and the scorer's hash it ran with, the git commit and uncommitted patch
hash of the strategy's code (provenance.py), when, its status (pass, equivalent,
fail, error, timeout), the scores (JSON), the found flows (JSON), how long discovery took and any
error; and since 2026-10-19 its times (seconds: discovery; score_seconds: loading the fresh data and
scoring; wall_seconds: the whole item in its worker, errors and timeouts included; wait_seconds: from
the run's start until a worker took the item) and the run that made it (run_id). Old rows have only
seconds. The newest row for each (case, variant, strategy) has latest = 1. A pair is stale when it has
no row, or its latest row ran with another case hash, strategy hash or scorer hash (score_only: only
the scorer changed, so the stored flows are scored again without running discovery).

runs and progress: what the current (or last) run is doing, for a live view: one row per run
(command, started, finished, total; since 2026-10-19 also its worker count, process id, the stale
items there were when it was planned (backlog: a watch batch takes at most --batch of them), and
running counts of the items done, errors, timeouts and their wall seconds, kept for every run, never
deleted) and one per item of it (queued, running, done, with when it started and finished); items of
earlier runs are dropped when a new run starts.
"""

from __future__ import annotations

import json
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from .data import cache_root

SCHEMA = """
CREATE TABLE IF NOT EXISTS results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id TEXT NOT NULL, case_hash TEXT NOT NULL, variant TEXT NOT NULL,
    strategy TEXT NOT NULL, strategy_hash TEXT NOT NULL, score_hash TEXT NOT NULL,
    at TEXT NOT NULL, latest INTEGER NOT NULL DEFAULT 1,
    status TEXT NOT NULL, seconds REAL, error TEXT,
    scores TEXT, found TEXT,
    code_commit TEXT, code_dirty TEXT,
    score_seconds REAL, wall_seconds REAL, wait_seconds REAL, run_id INTEGER, machine TEXT, remote_id INTEGER
);
CREATE INDEX IF NOT EXISTS results_key ON results (case_id, variant, strategy, latest);
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    command TEXT, started TEXT NOT NULL, finished TEXT, total INTEGER NOT NULL DEFAULT 0,
    jobs INTEGER, pid INTEGER, backlog INTEGER, done INTEGER, errors INTEGER, timeouts INTEGER, busy REAL
);
CREATE TABLE IF NOT EXISTS progress (
    run_id INTEGER NOT NULL, case_id TEXT NOT NULL, variant TEXT NOT NULL, strategy TEXT NOT NULL,
    state TEXT NOT NULL, reason TEXT, started TEXT, finished TEXT, status TEXT,
    PRIMARY KEY (run_id, case_id, variant, strategy)
);
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def path() -> Path:
    return cache_root() / "results.sqlite"


@contextmanager
def connect(readonly: bool = False):
    p = path()
    if readonly and not p.exists():
        con = sqlite3.connect(":memory:")
    else:
        p.parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(p, timeout=30)
        con.execute("PRAGMA journal_mode=WAL")
    con.row_factory = sqlite3.Row
    try:
        con.executescript(SCHEMA)
        _migrate(con)
        yield con
        con.commit()
    finally:
        con.close()


RESULT_COLUMNS = (("code_commit", "TEXT"), ("code_dirty", "TEXT"), ("score_seconds", "REAL"), ("wall_seconds", "REAL"),
                  ("wait_seconds", "REAL"), ("run_id", "INTEGER"), ("machine", "TEXT"), ("remote_id", "INTEGER"))
RUN_COLUMNS = (("jobs", "INTEGER"), ("pid", "INTEGER"), ("backlog", "INTEGER"), ("done", "INTEGER"), ("errors", "INTEGER"),
               ("timeouts", "INTEGER"), ("busy", "REAL"))
_migrated: set = set()
REMOTE_INDEX = "CREATE UNIQUE INDEX IF NOT EXISTS results_remote ON results (machine, remote_id) WHERE remote_id IS NOT NULL"


def _migrate(con: sqlite3.Connection) -> None:
    """Columns added since a store was made: code_commit and code_dirty (where a result's code is); the
    result's times and run (2026-10-19); a run's workers, backlog and counts (2026-10-19); the machine that
    made a result and its id there (remote_id: set only on imported rows, exchange.py; 2026-10-19), with
    the index that keeps an import from storing one remote row twice."""
    if str(path()) in _migrated:
        con.execute(REMOTE_INDEX)                             # a store made again at the same path (tests)
        return
    for table, cols in (("results", RESULT_COLUMNS), ("runs", RUN_COLUMNS)):
        have = {r[1] for r in con.execute(f"PRAGMA table_info({table})")}
        for col, kind in cols:
            if col not in have:
                try:
                    con.execute(f"ALTER TABLE {table} ADD COLUMN {col} {kind}")
                except sqlite3.OperationalError:               # another process added it first
                    pass
    con.execute(REMOTE_INDEX)
    _migrated.add(str(path()))


def _row(r: sqlite3.Row, found: bool = False) -> dict:
    out = {"id": r["id"], "case": r["case_id"], "case_hash": r["case_hash"], "variant": r["variant"], "strategy": r["strategy"],
           "strategy_hash": r["strategy_hash"], "score_hash": r["score_hash"], "at": r["at"], "latest": bool(r["latest"]),
           "status": r["status"], "seconds": r["seconds"], "error": r["error"], "scores": json.loads(r["scores"]) if r["scores"] else None,
           "code_commit": r["code_commit"], "code_dirty": r["code_dirty"]}
    keys = r.keys()
    if "machine" in keys:
        out["machine"] = r["machine"] or _here()             # rows stored before 2026-10-19 have none: made here
    for k in ("score_seconds", "wall_seconds", "wait_seconds", "run_id"):
        if k in keys and r[k] is not None:                  # older rows have none: left out, so they read as before
            out[k] = r[k]
    if found:
        out["found"] = json.loads(r["found"]) if r["found"] else None
    return out


def _here() -> str:
    from .machines import here
    return here()


def record(row: dict) -> int:
    """Store a result (case, variant, strategy, case_hash, strategy_hash, score_hash, status,
    seconds?, error?, scores?, found?, code_commit?, code_dirty?, score_seconds?, wall_seconds?, wait_seconds?,
    run_id?) as the latest for its key, made on this machine (machines.here())."""
    with connect() as con:
        con.execute("UPDATE results SET latest = 0 WHERE case_id = ? AND variant = ? AND strategy = ? AND latest = 1",
                    (row["case"], row["variant"], row["strategy"]))
        cur = con.execute(
            "INSERT INTO results (case_id, case_hash, variant, strategy, strategy_hash, score_hash, at, latest, status, seconds, error, scores, found,"
            " code_commit, code_dirty, score_seconds, wall_seconds, wait_seconds, run_id, machine) VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (row["case"], row["case_hash"], row["variant"], row["strategy"], row["strategy_hash"], row["score_hash"], row.get("at") or now(),
             row["status"], row.get("seconds"), row.get("error"),
             json.dumps(row["scores"]) if row.get("scores") is not None else None,
             json.dumps(row["found"]) if row.get("found") is not None else None, row.get("code_commit"), row.get("code_dirty"),
             row.get("score_seconds"), row.get("wall_seconds"), row.get("wait_seconds"), row.get("run_id"), _here()))
        return int(cur.lastrowid)


def latest(case: str | None = None, variant: str | None = None, strategy: str | None = None, found: bool = False) -> list[dict]:
    q, args = "SELECT * FROM results WHERE latest = 1", []
    for col, v in (("case_id", case), ("variant", variant), ("strategy", strategy)):
        if v is not None:
            q += f" AND {col} = ?"
            args.append(v)
    with connect(readonly=True) as con:
        return [_row(r, found) for r in con.execute(q + " ORDER BY case_id, strategy, variant", args)]


def history(case: str, variant: str, strategy: str, found: bool = False) -> list[dict]:
    with connect(readonly=True) as con:
        rows = con.execute("SELECT * FROM results WHERE case_id = ? AND variant = ? AND strategy = ? ORDER BY id DESC", (case, variant, strategy))
        return [_row(r, found) for r in rows]


def found_flows(ids: list[int]) -> dict[int, str | None]:
    """{result id: its found flows as stored (JSON text, not parsed)} for the given ids."""
    out: dict[int, str | None] = {}
    with connect(readonly=True) as con:
        for i in range(0, len(ids), 500):
            chunk = [int(x) for x in ids[i:i + 500]]
            q = f"SELECT id, found FROM results WHERE id IN ({','.join('?' * len(chunk))})"
            out.update({r["id"]: r["found"] for r in con.execute(q, chunk)})
    return out


def version() -> tuple:
    """Changes whenever a result is stored: (newest id, how many)."""
    with connect(readonly=True) as con:
        r = con.execute("SELECT MAX(id), COUNT(*) FROM results").fetchone()
        return (r[0] or 0, r[1])


def after(last_id: int) -> list[dict]:
    """Every result stored after id last_id, oldest first, without found flows (api.summary reads only
    what is new since it last looked)."""
    with connect(readonly=True) as con:
        return [_row(r) for r in con.execute("SELECT * FROM results WHERE id > ? ORDER BY id", (int(last_id),))]


def key_of(result_id: int) -> tuple | None:
    """(case, variant, strategy) of one result, or None if there is none (to tell that a store was replaced)."""
    with connect(readonly=True) as con:
        r = con.execute("SELECT case_id, variant, strategy FROM results WHERE id = ?", (int(result_id),)).fetchone()
        return (r[0], r[1], r[2]) if r else None


def get(result_id: int, found: bool = True) -> dict | None:
    """One result by its id (None if there is none)."""
    with connect(readonly=True) as con:
        r = con.execute("SELECT * FROM results WHERE id = ?", (int(result_id),)).fetchone()
        return _row(r, found) if r else None


def statuses(strategy: str) -> list[dict]:
    """Every result of a strategy, oldest first, without scores or found flows: {id, case, variant,
    strategy_hash, score_hash, at, status}."""
    with connect(readonly=True) as con:
        rows = con.execute("SELECT id, case_id, variant, strategy_hash, score_hash, at, status FROM results WHERE strategy = ? ORDER BY id", (strategy,))
        return [{"id": r["id"], "case": r["case_id"], "variant": r["variant"], "strategy_hash": r["strategy_hash"],
                 "score_hash": r["score_hash"], "at": r["at"], "status": r["status"]} for r in rows]


TIMES = "id, case_id, variant, strategy, strategy_hash, at, status, seconds, score_seconds, wall_seconds"


def times_after(last_id: int) -> list[tuple]:
    """(id, case, variant, strategy, strategy hash, at, status, seconds, score_seconds, wall_seconds) of every
    result stored after id last_id, oldest first: what timing.py keeps (no scores or flows: light)."""
    with connect(readonly=True) as con:
        return [tuple(r) for r in con.execute(f"SELECT {TIMES} FROM results WHERE id > ? ORDER BY id", (int(last_id),))]


def staleness(row: dict | None, case_hash: str, strategy_hash: str, score_hash: str) -> str | None:
    """Why a pair must run again (None: its latest result is current)."""
    if row is None:
        return "new"
    if row["case_hash"] != case_hash:
        return "case changed"
    if row["strategy_hash"] != strategy_hash:
        return "strategy changed"
    if row["score_hash"] != score_hash:
        return "score_only" if row["status"] not in ("error", "timeout") else "scoring changed"
    if row["status"] == "error" and _crashed(row.get("error")):
        return "worker crashed"                       # the machine, not the strategy: run it again
    return None


def _crashed(error: str | None) -> bool:
    """An error from the worker process dying (out of memory, killed), not from the strategy."""
    e = error or ""
    return "BrokenProcessPool" in e or "terminated abruptly" in e


# ---- progress ----

def start_run(command: str, items: list[dict], jobs: int | None = None, backlog: int | None = None) -> int:
    """A new run of items on jobs workers (backlog: the stale items there were when it was planned)."""
    import os
    with connect() as con:
        con.execute("DELETE FROM progress")
        cur = con.execute("INSERT INTO runs (command, started, total, jobs, pid, backlog, done, errors, timeouts, busy)"
                          " VALUES (?, ?, ?, ?, ?, ?, 0, 0, 0, 0)", (command, now(), len(items), jobs, os.getpid(), backlog))
        run_id = int(cur.lastrowid)
        con.executemany("INSERT OR REPLACE INTO progress (run_id, case_id, variant, strategy, state, reason) VALUES (?, ?, ?, ?, 'queued', ?)",
                        [(run_id, i["case"], i["variant"], i["strategy"], i.get("reason")) for i in items])
        return run_id


def mark(run_id: int, item: dict, state: str, status: str | None = None, wall: float | None = None) -> None:
    """An item's state; a done item also counts in its run (done, errors, timeouts, busy: its wall seconds)."""
    col = "started" if state == "running" else "finished"
    for attempt in range(5):
        try:
            with connect() as con:
                con.execute(f"UPDATE progress SET state = ?, {col} = ?, status = COALESCE(?, status) WHERE run_id = ? AND case_id = ? AND variant = ? AND strategy = ?",
                            (state, now(), status, run_id, item["case"], item["variant"], item["strategy"]))
                if state == "done":
                    con.execute("UPDATE runs SET done = COALESCE(done, 0) + 1, errors = COALESCE(errors, 0) + ?, timeouts = COALESCE(timeouts, 0) + ?,"
                                " busy = COALESCE(busy, 0) + ? WHERE id = ?", (status == "error", status == "timeout", wall or 0.0, run_id))
            return
        except sqlite3.OperationalError:
            time.sleep(0.05 * (attempt + 1))


def finish_run(run_id: int) -> None:
    with connect() as con:
        con.execute("UPDATE runs SET finished = ? WHERE id = ?", (now(), run_id))


def runs(limit: int = 50, command: str | None = None) -> list[dict]:
    """The newest runs first (every column; done, errors, timeouts and busy are None for runs made before
    2026-10-19), optionally only those of one command (e.g. "watch")."""
    q, args = "SELECT * FROM runs", []
    if command:
        q += " WHERE command = ?"
        args.append(command)
    with connect(readonly=True) as con:
        return [dict(r) for r in con.execute(q + " ORDER BY id DESC LIMIT ?", (*args, int(limit)))]


STALL = 180          # seconds without any item starting or finishing: the run's process is gone (items time out at 120 s)


def progress() -> dict:
    """{"run": {id, command, started, finished, total, done, running, aborted?} | None, "items": [...]}; a run
    that never finished is reported finished (aborted when not everything was done) once all its
    items are done or it has stalled for STALL seconds."""
    with connect(readonly=True) as con:
        r = con.execute("SELECT * FROM runs ORDER BY id DESC LIMIT 1").fetchone()
        if r is None:
            return {"run": None, "items": []}
        items = [{"case": x["case_id"], "variant": x["variant"], "strategy": x["strategy"], "state": x["state"], "reason": x["reason"],
                  "started": x["started"], "finished": x["finished"], "status": x["status"]}
                 for x in con.execute("SELECT * FROM progress WHERE run_id = ? ORDER BY case_id, strategy, variant", (r["id"],))]
    run = {"id": r["id"], "command": r["command"], "started": r["started"], "finished": r["finished"], "total": r["total"],
           "done": sum(i["state"] == "done" for i in items), "running": sum(i["state"] == "running" for i in items)}
    if not run["finished"]:
        # a run whose process died (killed, interrupted) is never marked finished: report it as over
        # once everything is done, or once nothing has started or finished for STALL seconds
        last = max([run["started"]] + [x for i in items for x in (i["started"], i["finished"]) if x])
        idle = (datetime.now(timezone.utc) - datetime.fromisoformat(last.replace("Z", "+00:00"))).total_seconds()
        if run["done"] >= run["total"] or idle > STALL:
            run.update(finished=last, aborted=run["done"] < run["total"], running=0)
            items = [{**i, "state": "aborted"} if i["state"] == "running" else i for i in items]
    return {"run": run, "items": items}


# ---- archive ----

def latest_keys() -> list[tuple]:
    """(id, case, variant, strategy) of every latest result (light: no scores or flows)."""
    with connect(readonly=True) as con:
        return [tuple(r) for r in con.execute("SELECT id, case_id, variant, strategy FROM results WHERE latest = 1 ORDER BY case_id, variant, strategy")]


def archive(ids: list[int], why: dict[int, str]) -> int:
    """Take results out of the latest (latest = 0) and list them in `archived` with why and when; the
    rows themselves are kept (prune.py: a result whose case or variant no longer exists). Returns how
    many were archived."""
    with connect() as con:
        con.execute("CREATE TABLE IF NOT EXISTS archived (result_id INTEGER PRIMARY KEY, at TEXT NOT NULL, why TEXT)")
        at, n = now(), 0
        for i in ids:
            cur = con.execute("UPDATE results SET latest = 0 WHERE id = ? AND latest = 1", (int(i),))
            if cur.rowcount:
                con.execute("INSERT OR REPLACE INTO archived (result_id, at, why) VALUES (?, ?, ?)", (int(i), at, why.get(i)))
                n += 1
        return n
