"""SQLite 3.51.0/3.51.1's unix-VFS deadlock, which hung the server on 2026-10-20 (sqlite_keep.py): threads
opening a WAL file while another closes it as the process's only reader wait for ever. Reproduced in a child
process (so a hang can be killed): plain sqlite3.connect hangs within seconds on an affected SQLite, and the
same contention through sqlite_keep.connect (what store.connect uses) does not."""

from __future__ import annotations

import sqlite3
import subprocess
import sys

import pytest

from sdlab.ladder import sqlite_keep, store

CHILD = r'''
import os, sqlite3, sys, tempfile, threading, time
from sdlab.ladder import sqlite_keep
connect = sqlite_keep.connect if sys.argv[1] == "keep" else sqlite3.connect
p = os.path.join(tempfile.mkdtemp(), "x.sqlite")
c = sqlite3.connect(p); c.execute("PRAGMA journal_mode=WAL"); c.execute("CREATE TABLE t(a)"); c.commit(); c.close()
stop = time.time() + float(sys.argv[2])
def reader():                     # closes as the only reader: WalClose tries EXCLUSIVE (unixLock > unixIsSharingShmNode)
    while time.time() < stop:
        c = connect(p, timeout=30); c.execute("SELECT COUNT(*) FROM t").fetchone(); c.close()
def opener():                     # opens: findReusableFd takes the VFS mutex, then the inode's
    while time.time() < stop:
        connect(p, timeout=30).close()
ts = [threading.Thread(target=reader, daemon=True) for _ in range(2)] + [threading.Thread(target=opener, daemon=True) for _ in range(4)]
for t in ts: t.start()
end = time.time() + float(sys.argv[2]) + 5
for t in ts: t.join(max(0.01, end - time.time()))
print("hung" if any(t.is_alive() for t in ts) else "ok", flush=True)
os._exit(0)
'''

AFFECTED = sqlite3.sqlite_version_info[:2] == (3, 51) and sqlite3.sqlite_version_info < (3, 51, 2)


def _run(mode: str, seconds: float = 4.0) -> str:
    r = subprocess.run([sys.executable, "-c", CHILD, mode, str(seconds)], capture_output=True, text=True, timeout=seconds + 30)
    return r.stdout.strip() or r.stderr[-500:]


def test_open_and_close_contention_does_not_deadlock_through_the_keeper():
    assert _run("keep") == "ok"


@pytest.mark.skipif(not AFFECTED, reason=f"SQLite {sqlite3.sqlite_version} does not have the 3.51.0/3.51.1 deadlock")
def test_plain_sqlite3_deadlocks_on_this_sqlite():
    assert _run("plain") == "hung"                    # the bug is real here, so the keeper is what prevents it


def test_store_connect_keeps_its_file(tmp_path, monkeypatch):
    monkeypatch.setenv("SDLAB_LADDER_CACHE", str(tmp_path))
    with store.connect():
        pass
    with store.connect(readonly=True) as con:
        con.execute("SELECT COUNT(*) FROM results").fetchone()
    assert str(store.path()) in sqlite_keep.kept()


def test_a_file_not_in_wal_mode_is_not_kept(tmp_path):
    p = tmp_path / "plain.sqlite"
    sqlite3.connect(p).close()
    sqlite_keep.connect(p).close()
    assert str(p) not in sqlite_keep.kept()

