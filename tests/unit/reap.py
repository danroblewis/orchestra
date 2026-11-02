"""Stops a process a test started, with everything it started, however the test ends.

Run as a script beside the process (the ``spawn`` fixture in ``conftest.py`` does), it watches the
process's descendants until its stdin closes: when the fixture closes it at teardown, or when
pytest dies (killed, it never runs its finalisers, but its end of the pipe closes all the same).
Then it stops them: SIGTERM to the process's group, a short wait, SIGTERM to every descendant it
saw (a launcher starts each in a session of its own), and SIGKILL to what is left."""

import os
import signal
import sys
import threading
import time

import psutil


def _running(p: psutil.Process) -> bool:
    try:
        return p.is_running() and p.status() != psutil.STATUS_ZOMBIE
    except psutil.Error:
        return False


def _wait(procs, timeout: float) -> list[psutil.Process]:
    end = time.monotonic() + timeout
    while (left := [p for p in procs if _running(p)]) and time.monotonic() < end:
        time.sleep(0.05)
    return left


def descendants(pid: int) -> list[psutil.Process]:
    try:
        p = psutil.Process(pid)
        return [p, *p.children(recursive=True)]
    except psutil.Error:
        return []


def stop(pid: int, seen: dict | None = None, grace: float = 10.0) -> None:
    """Stop ``pid`` (the leader of its own process group) and every descendant in ``seen`` or
    alive now: SIGTERM to the group, ``grace`` seconds for the leader, then SIGTERM to the rest
    and SIGKILL to whatever is still running two seconds later."""
    seen = dict(seen or {})
    for p in descendants(pid):
        seen.setdefault((p.pid, _created(p)), p)
    try:
        os.killpg(pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        pass
    leader = [p for p in seen.values() if p.pid == pid]
    _wait(leader, grace)
    for p in descendants(pid):
        seen.setdefault((p.pid, _created(p)), p)
    left = [p for p in seen.values() if _running(p)]
    for p in left:
        try:
            p.terminate()                              # psutil checks it is still the same process
        except psutil.Error:
            pass
    for p in _wait(left, 2.0):
        try:
            p.kill()
        except psutil.Error:
            pass
    try:
        os.killpg(pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass


def _created(p: psutil.Process) -> float:
    try:
        return p.create_time()
    except psutil.Error:
        return 0.0


def watch(pid: int, grace: float) -> None:
    closed = threading.Event()
    threading.Thread(target=lambda: (sys.stdin.read(), closed.set()), daemon=True).start()
    seen: dict = {}
    while not closed.wait(0.2):
        for p in descendants(pid):
            seen.setdefault((p.pid, _created(p)), p)
    stop(pid, seen, grace)


if __name__ == "__main__":
    watch(int(sys.argv[1]), float(sys.argv[2]))
