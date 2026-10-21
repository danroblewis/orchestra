"""The pool's tables, in the result store's SQLite file (store.path()), beside `results`. Creating them
never touches an existing table or row (CREATE ... IF NOT EXISTS only).

    pool_jobs     one row per job: kind (agent | mainline), by, note, priority, ref, commit, spec (JSON),
                  state, created/started/finished, error, total
    pool_items    one row per (job, case, variant, strategy): the promised hashes, mode (run | rescore,
                  prev_id: the stored result re-scored), state, rank (slow first), the lease (id, worker,
                  expiry), attempts (crashes, rejections, lost leases), the memory a retry needs
                  (min_free_mb), result_id (pool_results), or reused_id / reused_pool_id: a stored result with
                  exactly its hashes (in results / pool_results), not run again; confirm_id: for a none-long
                  item held until its none-short passes (jobs.confirm_of), that none-short item
    pool_results  one row per accepted item: job, item, commit, machine, worker, slot, status, peak RSS,
                  the full row (JSON), and promoted_id: its row in `results` when it became the main
                  line's latest (None otherwise; promote: pending | done | not-main-line | current)
    pool_workers  every worker seen: its last heartbeat and what it said (slots, load, memory)

One server process writes them; LOCK serialises its writers (claims and posts are read-modify-write).
"""

from __future__ import annotations

import threading
from contextlib import contextmanager

from .. import store

LOCK = threading.RLock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS pool_jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL DEFAULT 'agent', by TEXT, note TEXT, priority INTEGER NOT NULL DEFAULT 100,
    ref TEXT, commit_sha TEXT, spec TEXT, state TEXT NOT NULL, created TEXT NOT NULL, started TEXT, finished TEXT,
    error TEXT, total INTEGER NOT NULL DEFAULT 0, planned_at TEXT
);
CREATE TABLE IF NOT EXISTS pool_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER NOT NULL, case_id TEXT NOT NULL, variant TEXT NOT NULL, strategy TEXT NOT NULL,
    case_hash TEXT NOT NULL, strategy_hash TEXT NOT NULL, score_hash TEXT NOT NULL,
    mode TEXT NOT NULL DEFAULT 'run', prev_id INTEGER, state TEXT NOT NULL DEFAULT 'queued', rank REAL NOT NULL DEFAULT 0,
    heavy INTEGER NOT NULL DEFAULT 0, timeout REAL, tags TEXT,
    lease_id TEXT, worker TEXT, leased_at TEXT, lease_expires REAL,
    crashes INTEGER NOT NULL DEFAULT 0, rejections INTEGER NOT NULL DEFAULT 0, lost INTEGER NOT NULL DEFAULT 0,
    min_free_mb REAL, error TEXT, result_id INTEGER, reused_id INTEGER, reused_pool_id INTEGER, finished TEXT,
    UNIQUE (job_id, case_id, variant, strategy)
);
CREATE INDEX IF NOT EXISTS pool_items_queue ON pool_items (state, job_id, rank);
CREATE INDEX IF NOT EXISTS pool_items_lease ON pool_items (lease_id);
CREATE TABLE IF NOT EXISTS pool_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id INTEGER NOT NULL UNIQUE, job_id INTEGER NOT NULL,
    case_id TEXT NOT NULL, variant TEXT NOT NULL, strategy TEXT NOT NULL,
    case_hash TEXT NOT NULL, strategy_hash TEXT NOT NULL, score_hash TEXT NOT NULL,
    commit_sha TEXT, machine TEXT, worker TEXT, slot TEXT, status TEXT NOT NULL,
    seconds REAL, wall_seconds REAL, peak_rss_mb REAL, at TEXT NOT NULL, row TEXT NOT NULL,
    promote TEXT NOT NULL DEFAULT 'pending', promoted_id INTEGER
);
CREATE INDEX IF NOT EXISTS pool_results_job ON pool_results (job_id);
CREATE INDEX IF NOT EXISTS pool_results_cell ON pool_results (case_id, strategy);
CREATE INDEX IF NOT EXISTS pool_results_promote ON pool_results (promote);
CREATE TABLE IF NOT EXISTS pool_workers (
    name TEXT PRIMARY KEY, machine TEXT, first_seen TEXT NOT NULL, last_seen TEXT NOT NULL, seen REAL NOT NULL, info TEXT
);
"""

_made: set = set()


@contextmanager
def connect(readonly: bool = False):
    with store.connect(readonly=readonly) as con:
        key = str(store.path())
        if key not in _made:
            con.executescript(SCHEMA)
            _migrate(con)
            if store.path().exists():                 # a read of a store not made yet reads an empty one in memory
                _made.add(key)
        yield con


ITEM_COLUMNS = (("confirm_id", "INTEGER"),)    # added after the table was first made (ALTER ... ADD COLUMN: no row changes)


def _migrate(con) -> None:
    have = {r[1] for r in con.execute("PRAGMA table_info(pool_items)")}
    for name, kind in ITEM_COLUMNS:
        if name not in have:
            con.execute(f"ALTER TABLE pool_items ADD COLUMN {name} {kind}")


def reset_cache() -> None:
    """Forget which stores have the tables (tests make a new store per test)."""
    _made.clear()
