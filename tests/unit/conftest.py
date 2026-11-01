"""Without ``orchestra[sd]`` (``sd.extra``), the modules that import numpy when collected are not
collected, so the unit suite passes with and without the extra. Each also skips its tests by
``sd_installed()`` once collected."""

import pytest

from orchestra.sd.extra import installed

NEEDS_SD = [
    "test_experiment_pages.py",
    "test_experiments_api.py",
    "test_experiments_edits.py",
    "test_experiments_forward.py",
    "test_experiments_inverse.py",
    "test_experiments_language.py",
    "test_experiments_replay.py",
]

collect_ignore = [] if installed() else NEEDS_SD


@pytest.fixture(autouse=True)
def _discovery_not_stopping(monkeypatch):
    """``sd.bounded.kill_running`` (a host's stop, a web app's shutdown) refuses every strategy
    after it, for the rest of the process: each test starts as a fresh process would."""
    from orchestra.sd import bounded
    monkeypatch.setattr(bounded, "_stopping", False)
