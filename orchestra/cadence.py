"""A machine instance's cadence on the bus, and whether it is still active by it: one rule, shared by
the Machines page (``web/machines.py``) and the host's quiet watch (``quiet.py``).

A **beat** is an event that comes more than ``BURST_S`` after the instance's previous event (the
events of one burst, a restart's ``started`` and ``subscribed`` or one run's few events, are one
beat). Its **cadence** is the median gap between its last ``BEATS`` beats (at least ``MIN_BEATS``; a gap
longer than the cadence before it allows, a hang, left out), observed, never taken
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
MIN_BEATS = 3              # beats before a cadence counts: two gaps, a rhythm of its own, not one interval
BURST_S = ACTIVE_FLOOR_S / ACTIVE_MARGIN   # an event this soon after the instance's previous one is in the same burst, not a new beat


def active_within(cadence: float | None) -> float:
    """How long after it was last seen an instance with this cadence is still active (a cadence
    longer than a day counts as a day)."""
    return max(ACTIVE_FLOOR_S, ACTIVE_MARGIN * min(cadence, DAY)) if cadence else ACTIVE_FLOOR_S


def gaps(times, least: int = MIN_BEATS) -> float | None:
    """The median gap between the last ``BEATS`` distinct times, or ``None`` with fewer than
    ``least`` (``MIN_BEATS`` for a machine: two gaps, a rhythm of its own, not one interval; a series'
    writes, ``sd.intended.measured``, take two). Only gaps between beats count,
    never the open one since the last; and a gap longer than ``active_within`` the cadence of the
    gaps before it (a hang, a stop) is left out, so a hang is never learnt as the usual gap."""
    ts = sorted(set(times))[-BEATS:]
    if len(ts) < max(2, least):
        return None
    kept: list[float] = []
    for g in (b - a for a, b in pairwise(ts)):
        if kept and g > active_within(median(kept)):
            continue
        kept.append(g)
    return median(kept)
