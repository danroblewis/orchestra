"""Which measured level is the state an item passes through within a step.

The grid samples a level at whole steps, so a state each item leaves within a second reads empty
at every step; its raw points do not. The level that rises at an instant one of the passage's
ins counted (at it, or no later than the level's own write interval after it), and falls at an
instant one of its outs counted, is that state: most of its rises and of its falls (``MATCHED``)
must, and it must have risen at least once and no more often than the ins counted. A level that
never reads above zero says nothing about which state it is, and is never chosen."""

from __future__ import annotations

from bisect import bisect_left
from itertools import pairwise
from statistics import median

from .series import Series

MATCHED = 0.8         # the share of a level's rises (and falls) that must come at the passage's events
SAME_TOTAL = 0.03


def events(c: Series, start: float, end: float) -> list[float]:
    """The instants a counter counted, inside the window (a drop is a reset)."""
    return sorted(t for (_, a), (t, b) in pairwise(c.points) if start < t <= end and ((b - a) if b >= a else b) > 0)


def _hits(moves: list[float], at: list[float], tol: float) -> int:
    hit = 0
    for t in moves:
        i = bisect_left(at, t - tol)
        hit += 1 if i < len(at) and at[i] <= t + 1e-6 else 0
    return hit


def at_events(level: Series, ins: list[Series], outs: list[Series], start: float, end: float, step: float
              ) -> tuple[list[int], list[int]] | None:
    """The level's rises at the ins' events and its falls at the outs' events, each as [matched,
    all]; None when it is not the state between them."""
    pts = [(t, v) for t, v in level.points if start - step < t <= end]
    rises = [t for (_, a), (t, b) in pairwise(pts) if b > a and t > start]
    falls = [t for (_, a), (t, b) in pairwise(pts) if b < a and t > start]
    if not rises:
        return None
    tol = min(step, median([b - a for (a, _), (b, _) in pairwise(pts)] or [step])) + 1e-6
    into = sorted(t for c in ins for t in events(c, start - step, end))
    out = sorted(t for c in outs for t in events(c, start - step, end))
    up, down = _hits(rises, into, tol), _hits(falls, out, tol)
    if up < MATCHED * len(rises) or down < MATCHED * len(falls) or len(rises) > len(into) * (1 + SAME_TOTAL) + 1:
        return None
    return [up, len(rises)], [down, len(falls)]


def state_level(levels: list[Series], ins: list[Series], outs: list[Series], *, start: float, end: float, step: float,
                machine_of) -> tuple[Series, list[int], list[int]] | None:
    """The level that is the state between ``ins`` and ``outs``: of those that qualify, the one
    with the most rises at the ins' events, then the ins' machine's."""
    scored = [(m, lv) for lv in levels if (m := at_events(lv, ins, outs, start, end, step))]
    if not scored:
        return None
    (up, down), level = max(scored, key=lambda x: (x[0][0][0], machine_of(x[1]) == machine_of(ins[0]), x[1].key))
    return level, up, down
