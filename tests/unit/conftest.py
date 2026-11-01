"""Without ``orchestra[sd]`` (``sd.extra``), the modules that import numpy when collected are not
collected, so the unit suite passes with and without the extra. Each also skips its tests by
``sd_installed()`` once collected."""

from orchestra.sd.extra import installed

NEEDS_SD = [
    "test_experiments_api.py",
    "test_experiments_edits.py",
    "test_experiments_forward.py",
    "test_experiments_inverse.py",
    "test_experiments_language.py",
    "test_experiments_replay.py",
]

collect_ignore = [] if installed() else NEEDS_SD
