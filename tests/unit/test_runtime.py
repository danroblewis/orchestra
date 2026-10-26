"""orchestra.runtime.alive: a recorded pid is alive only if its process exists."""

import os
import subprocess
import sys

from orchestra.runtime import alive


def test_alive():
    assert alive(os.getpid()) and alive(str(os.getpid()))
    gone = subprocess.Popen([sys.executable, "-c", "pass"])
    gone.wait()                                   # reaped, so the pid no longer exists
    assert not alive(gone.pid)
    assert not alive(0) and not alive(None) and not alive("not a pid")
