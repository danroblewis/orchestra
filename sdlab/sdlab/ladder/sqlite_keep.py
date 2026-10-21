"""Opening SQLite files without SQLite 3.51.0/3.51.1's unix-VFS deadlock (the server hung on it on 2026-10-20).

In those versions unixLock() holds a file's inode mutex (pLockMutex) and then takes the VFS's global mutex
(unixBigLock) in unixIsSharingShmNode(), while opening a file (findReusableFd()) takes them the other way
round. A WAL connection closing as the process's only reader of the file tries an EXCLUSIVE lock (to
checkpoint and remove the WAL) and so goes down that path; if another thread is opening the same file at that
moment, both wait for ever, and every later open waits behind them. SQLite 3.51.2 fixed it ("an obscure
deadlock in the new broken-posix-lock detection logic"); the server's Python links 3.51.0. A macOS sample of
the hung server showed exactly this: one thread in sqlite3WalClose > unixLock waiting for unixBigLock, one in
findReusableFd holding it and waiting for the inode mutex, 20 more opens behind them, and the pool's endpoints
queued on db.LOCK behind those (tests/test_sqlite_keep.py reproduces it).

The workaround: the first time a process opens a file through connect(), it also opens a keeper connection
to it, reads once (taking the SHARED lock, which a WAL connection keeps while it is open) and never closes it.
With two holders of SHARED in the process, a closing connection sees nShared > 1 and gives up its EXCLUSIVE
lock before reaching unixIsSharingShmNode(), so the bad lock order never happens. The keeper holds no read
transaction, so checkpoints are not held back; the WAL file is checkpointed by commits (wal_autocheckpoint) and
no longer removed when the last other connection closes. At most KEEP files are kept (tests make many stores).
"""

from __future__ import annotations

import sqlite3
import threading
import time
from collections import OrderedDict
from pathlib import Path

KEEP = 16
_lock = threading.Lock()
_kept: OrderedDict[str, sqlite3.Connection] = OrderedDict()
_not_wal: dict[str, float] = {}           # files found not in WAL mode, and when: looked at again after RETRY seconds
RETRY = 10.0


def keep(p, now_wal: bool = False) -> None:
    """Hold a keeper connection to the WAL file at p (an existing file; a no-op once it is kept, or when the
    file is not in WAL mode yet: a later call keeps it, at once with now_wal after switching it to WAL)."""
    key = str(p)
    if key in _kept or key == ":memory:" or (not now_wal and time.monotonic() - _not_wal.get(key, -RETRY) < RETRY):
        return
    with _lock:
        if key in _kept or not Path(key).exists():
            return
        try:
            k = sqlite3.connect(key, timeout=30, check_same_thread=False)
            if k.execute("PRAGMA journal_mode").fetchone()[0] != "wal":
                k.close()                                     # only WAL files keep SHARED (and only they hit the bug)
                _not_wal[key] = time.monotonic()
                return
            k.execute("SELECT COUNT(*) FROM sqlite_master").fetchone()   # takes SHARED on the file; WAL keeps it
        except sqlite3.Error:
            return
        _kept[key] = k
        while len(_kept) > KEEP:
            _kept.popitem(last=False)[1].close()


def connect(p, **kw) -> sqlite3.Connection:
    """sqlite3.connect(p, **kw), with the file kept (see the module doc)."""
    keep(p)
    con = sqlite3.connect(p, **kw)
    keep(p)                                                   # a file this connection has just made
    return con


def kept() -> list[str]:
    return list(_kept)
