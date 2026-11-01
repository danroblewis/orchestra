"""Without ``orchestra[sd]`` (``sd.extra``), the modules that import numpy when collected are not
collected, so the unit suite passes with and without the extra. Each also skips its tests by
``sd_installed()`` once collected."""

from orchestra.sd.extra import installed

NEEDS_SD = [
    "test_equation_language.py",
    "test_forward.py",
    "test_model_reads.py",
]

collect_ignore = [] if installed() else NEEDS_SD
