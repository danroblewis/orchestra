"""A machine instance's cadence on the bus, and whether it is still active by it: one rule, shared by
the Machines page (``web/machines.py``) and the host's quiet watch (``quiet.py``).

A **beat** is an event that comes more than ``BURST_S`` after the instance's previous event (the
events of one burst, a restart's ``started`` and ``subscribed`` or one run's few events, are one
beat). Its **cadence** is the median gap between its last ``BEATS`` beats, observed, never taken
from what the machine says of itself (AGENTS.md rule 2). An instance is **active** while its last
event is within ``ACTIVE_MARGIN`` times its cadence (a cadence over a day counts as a day), and
never less than ``ACTIVE_FLOOR_S``."""

from __future__ import annotations

from itertools import pairwise
from statistics import median

DAY = 86400.0
ACTIVE_FLOOR_S = 120.0     # active within at least this, however fast its cadence
ACTIVE_MARGIN = 2.5        # ... and within this many beats of its cadence: a round may be late, or one missed
BEATS = 9                  # the last times kept to observe a cadence
BURST_S = ACTIVE_FLOOR_S / ACTIVE_MARGIN   # an event this soon after the instance's previous one is in the same burst, not a new beat


def active_within(cadence: float | None) -> float:
    """How long after it was last seen an instance with this cadence is still active (a cadence
    longer than a day counts as a day)."""
    return max(ACTIVE_FLOOR_S, ACTIVE_MARGIN * min(cadence, DAY)) if cadence else ACTIVE_FLOOR_S


def gaps(times) -> float | None:
    """The median gap between the last ``BEATS`` distinct times, or ``None`` with fewer than two."""
    ts = sorted(set(times))[-BEATS:]
    return median(b - a for a, b in pairwise(ts)) if len(ts) > 1 else None
