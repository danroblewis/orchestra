"""The host's discovery cadence: no overlap, a pause after a run that outlasted the interval, and
a log line that says how long it took and whether the strategy was cut at its deadline."""

from __future__ import annotations

from types import SimpleNamespace

from orchestra.host import LEAST_PAUSE, discovery_line, pace
from orchestra.sd.model import Model


def test_runs_start_every_interval_and_pause_after_a_long_one():
    assert pace(300, 40) == 260                       # the next starts 300 s after this one started
    assert pace(300, 290) == LEAST_PAUSE * 300        # never right after: at least a fifth of the interval
    assert pace(300, 900) == LEAST_PAUSE * 300


def test_the_log_line_says_how_long_and_what_was_cut():
    m = Model("system", "The system")
    m.discovery = {"sdlab": "stopped at its deadline of 240 s: conservation's fits are kept"}
    r = SimpleNamespace(model=m, version=None, strategy="kalman_lna")
    line = discovery_line(r, 312.4, 300)
    assert "took 312 s" in line and "stopped at its deadline of 240 s" in line and "longer than [discovery] every (300 s)" in line
    m.discovery = {}
    assert discovery_line(r, 30, 300).endswith("structure unchanged; took 30 s")
