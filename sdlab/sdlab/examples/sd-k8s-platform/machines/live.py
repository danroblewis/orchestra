"""Sensor: the sd-k8s-platform example, live; see sdlab/livefeed.py.

    live.py [seed]

A lighter feed than the other examples' (a week of this model takes most of a minute to simulate,
and a sensor has a minute per tick): its first recording is one day, of the measured levels only
(no flow counters), and once a run is past half of a recording, the next one (twice as long) is made
in the background, so the run does not wait for it. SDLAB_LIVE_STEPS works as for the other examples.
"""

import io
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

import sim

from sdlab.livefeed import play, recording

LIVE_STEPS = 1440
FEED = SimpleNamespace(SEED=sim.SEED, STEPS=sim.STEPS, LONG_STEPS=LIVE_STEPS, UNBOUNDED=True,
                       measured=lambda seed, steps: {k: v for k, v in sim.measured(seed, steps).items() if k != "counters"})
HERE = Path(__file__).resolve().parent

if __name__ == "__main__":
    if sys.argv[1:2] == ["--prepare"]:                      # in the background: live.py --prepare <steps> <seed>
        recording(FEED, HERE, int(sys.argv[3]), int(sys.argv[2]))
        sys.exit(0)
    stdin = "" if sys.stdin.isatty() else sys.stdin.read()
    sys.stdin = io.StringIO(stdin)
    play(FEED, __file__)
    if not os.environ.get("SDLAB_LIVE_STEPS"):
        seed = int(sys.argv[1]) if len(sys.argv) > 1 else sim.SEED
        t, steps = int((json.loads(stdin) if stdin.strip() else {}).get("t") or 1), LIVE_STEPS
        while t > steps:
            steps *= 2
        if t > steps // 2:
            lock = Path(tempfile.gettempdir()) / f"sdlab-live-prepare-{HERE.parent.name}-{seed}-{2 * steps}"
            try:
                os.close(os.open(lock, os.O_CREAT | os.O_EXCL))
            except FileExistsError:
                pass
            else:
                subprocess.Popen([sys.executable, __file__, "--prepare", str(2 * steps), str(seed)], start_new_session=True,
                                 stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, cwd=HERE)
