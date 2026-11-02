"""Without ``orchestra[sd]`` (``sd.extra``), the modules that import numpy when collected are not
collected, so the unit suite passes with and without the extra. Each also skips its tests by
``sd_installed()`` once collected."""

import pytest

from orchestra.sd.extra import installed

NEEDS_SD = [
    "test_equation_language.py",
    "test_forward.py",
    "test_model_reads.py",
]

collect_ignore = [] if installed() else NEEDS_SD


@pytest.fixture(autouse=True)
def _discovery_not_stopping(monkeypatch):
    """``sd.bounded.kill_running`` (a host's stop, a web app's shutdown) refuses every strategy
    after it, for the rest of the process: each test starts as a fresh process would."""
    from orchestra.sd import bounded
    monkeypatch.setattr(bounded, "_stopping", False)


@pytest.fixture
def spawn():
    """``spawn(argv, grace=10.0, **popen_kwargs)`` starts a process in a session of its own, and
    stops it with everything it started however the test ends: at teardown, and, through a
    watcher (``reap.py``), when pytest itself is killed and never runs its finalisers."""
    import subprocess
    import sys
    from pathlib import Path

    import reap

    started = []

    def start(argv, *, grace: float = 10.0, **kw) -> subprocess.Popen:
        p = subprocess.Popen(argv, start_new_session=True, **kw)
        w = subprocess.Popen([sys.executable, str(Path(reap.__file__)), str(p.pid), str(grace)],
                             stdin=subprocess.PIPE, start_new_session=True)
        started.append((p, w, grace))
        return p

    yield start
    for p, w, grace in reversed(started):
        w.stdin.close()                                # the watcher stops it and what it started
        try:
            w.wait(timeout=grace + 10)
        except subprocess.TimeoutExpired:
            w.kill()
            w.wait()
            reap.stop(p.pid, grace=grace)
        if p.poll() is None:
            p.kill()
        p.wait()
