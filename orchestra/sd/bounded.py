"""Running SD Lab strategies with a hard deadline.

A strategy is given a time budget in its options, but SD Lab's strategies are research code made
of stages with budgets of their own, and some outlast what they were given (the live demo's
``kalman_lna`` took seven minutes on a four-minute deadline). With a deadline, the jobs run in a
Python process of their own (``python -m orchestra.sd.bounded``, the jobs as JSON on its standard
input), which is killed when the deadline passes; the discovery then keeps conservation's own
fits, and says so. Without one (tests, a direct call), they run here."""

from __future__ import annotations

import json
import subprocess
import sys


class Late(Exception):
    """The strategy did not answer within its deadline, or its process failed."""


def run_jobs(jobs: list[tuple], deadline: float | None) -> list[dict]:
    """Each job's answer (``jobs``: ``run_strategy``'s arguments), or ``Late``."""
    from . import strategies

    if not deadline:
        return [strategies.run_strategy(*job) for job in jobs]
    try:
        done = subprocess.run([sys.executable, "-m", "orchestra.sd.bounded"], input=json.dumps(jobs), capture_output=True,
                              text=True, timeout=deadline, check=False)
    except subprocess.TimeoutExpired:
        raise Late(f"stopped at its deadline of {deadline:g} s") from None
    if done.returncode != 0:
        raise Late(f"its process failed: {(done.stderr.strip().splitlines() or ['no message'])[-1]}")
    return json.loads(done.stdout)


def main() -> None:
    from .strategies import run_strategy

    jobs = json.load(sys.stdin)
    json.dump([run_strategy(*job) for job in jobs], sys.stdout)


if __name__ == "__main__":
    main()
