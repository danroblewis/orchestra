"""Running SD Lab strategies with a hard deadline.

A strategy is given a time budget in its options, but SD Lab's strategies are research code made
of stages with budgets of their own, and some outlast what they were given (the live demo's
``kalman_lna`` took seven minutes on a four-minute deadline). With a deadline, the jobs run in a
Python process of their own (``python -m orchestra.sd.bounded``, the jobs as JSON on its standard
input), which is killed when the deadline passes, with every process it started (it runs in a
session of its own, and the whole group is killed: a strategy that works in a pool of worker
processes, such as the vendored z3robust, would otherwise leave them running). The discovery then
keeps conservation's own fits, and says so. Without one (tests, a direct call), they run here.

The running child's group is registered while it runs, so a host or web server that stops
mid-discovery ends it too (``kill_running``, also at exit): its session of its own keeps any
terminal signal from reaching it. A child killed so raises ``Stopped``, not ``Late``: the
discovery waiting on it is abandoned, never saved as if the strategy had failed, and nothing is
started after the stop. Ctrl-C while waiting kills the child before it propagates."""

from __future__ import annotations

import atexit
import json
import os
import signal
import subprocess
import sys
import threading

_running: set[int] = set()             # the process groups of the strategies running now
_killed: set[int] = set()              # those kill_running ended
_stopping = False                      # set by kill_running: nothing is started after it
_lock = threading.Lock()


class Late(Exception):
    """The strategy did not answer within its deadline, or its process failed."""


class Stopped(Exception):
    """The process stopped mid-discovery (``kill_running``): the discovery is abandoned, never
    saved. Not a ``Late``: a stop is not a strategy's failure."""


def run_jobs(jobs: list[tuple], deadline: float | None) -> list[dict]:
    """Each job's answer (``jobs``: ``run_strategy``'s arguments), or ``Late``."""
    from . import strategies

    if not deadline:
        return [strategies.run_strategy(*job) for job in jobs]
    return json.loads(_bounded([sys.executable, "-m", "orchestra.sd.bounded"], json.dumps(jobs), deadline))


def _bounded(cmd: list[str], given: str, deadline: float) -> str:
    """What ``cmd`` printed, given ``given`` on its standard input, or ``Late`` when it failed or
    outlasted ``deadline``. Either way, every process it started is killed after it."""
    with _lock:                            # checked and registered under the lock kill_running takes
        if _stopping:
            raise Stopped("stopping: no strategy is started")
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                start_new_session=True)
        _running.add(proc.pid)
    try:
        try:
            out, err = proc.communicate(given, timeout=deadline)
        except subprocess.TimeoutExpired:
            _kill_group(proc.pid)
            proc.communicate()
            raise Late(f"stopped at its deadline of {deadline:g} s") from None
        except BaseException:              # Ctrl-C, or anything else while waiting: no child is left
            _kill_group(proc.pid)
            raise
    finally:
        with _lock:
            _running.discard(proc.pid)
            killed = proc.pid in _killed
            _killed.discard(proc.pid)
    _kill_group(proc.pid)                  # its workers may outlive it even when it answered
    if killed:
        raise Stopped("stopped mid-discovery: the strategy was killed")
    if proc.returncode != 0:
        raise Late(f"its process failed: {(err.strip().splitlines() or ['no message'])[-1]}")
    return out


def kill_running() -> None:
    """Kill every strategy process running now, with what it started, and start none after: for
    a host or web server that stops while a discovery runs. The discovery waiting on it then
    stops (``Stopped``) at once."""
    global _stopping
    with _lock:
        _stopping = True
        groups = list(_running)
        _killed.update(groups)
    for pgid in groups:
        _kill_group(pgid)


atexit.register(kill_running)


def _kill_group(pgid: int) -> None:
    """Kill the process group the child leads (its session): it and every process it started."""
    try:
        os.killpg(pgid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass


def main() -> None:
    from .strategies import run_strategy

    jobs = json.load(sys.stdin)
    json.dump([run_strategy(*job) for job in jobs], sys.stdout)


if __name__ == "__main__":
    main()
