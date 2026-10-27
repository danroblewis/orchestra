"""Running SD Lab strategies with a hard deadline.

A strategy is given a time budget in its options, but SD Lab's strategies are research code made
of stages with budgets of their own, and some outlast what they were given (the live demo's
``kalman_lna`` took seven minutes on a four-minute deadline). With a deadline, the jobs run in a
Python process of their own (``python -m orchestra.sd.bounded``, the jobs as JSON on its standard
input), which is killed when the deadline passes, with every process it started (it runs in a
session of its own, and the whole group is killed: a strategy that works in a pool of worker
processes, such as the vendored z3robust, would otherwise leave them running). The discovery then
keeps conservation's own fits, and says so. Without one (tests, a direct call), they run here."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys


class Late(Exception):
    """The strategy did not answer within its deadline, or its process failed."""


def run_jobs(jobs: list[tuple], deadline: float | None) -> list[dict]:
    """Each job's answer (``jobs``: ``run_strategy``'s arguments), or ``Late``."""
    from . import strategies

    if not deadline:
        return [strategies.run_strategy(*job) for job in jobs]
    return json.loads(_bounded([sys.executable, "-m", "orchestra.sd.bounded"], json.dumps(jobs), deadline))


def _bounded(cmd: list[str], given: str, deadline: float) -> str:
    """What ``cmd`` printed, given ``given`` on its standard input, or ``Late`` when it failed or
    outlasted ``deadline``. Either way, every process it started is killed after it."""
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                            start_new_session=True)
    try:
        out, err = proc.communicate(given, timeout=deadline)
    except subprocess.TimeoutExpired:
        _kill_group(proc.pid)
        proc.communicate()
        raise Late(f"stopped at its deadline of {deadline:g} s") from None
    _kill_group(proc.pid)                  # its workers may outlive it even when it answered
    if proc.returncode != 0:
        raise Late(f"its process failed: {(err.strip().splitlines() or ['no message'])[-1]}")
    return out


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
