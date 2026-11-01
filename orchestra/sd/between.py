"""Which measured level is the state an item passes through within a step.

The grid samples a level at whole steps, so a state each item leaves within a second reads empty
at every step; its raw points do not. The level that rises at an instant one of the passage's
ins counted (at it, or no later than the level's own write interval after it), and falls at an
instant one of its outs counted, is that state: most of its rises and of its falls (``MATCHED``)
must, and its rises must account for the ins' moves and its falls for the outs' (``accounts``):
by magnitude, neither more nor fewer than the counters' moves in the window, within ``SAME_TOTAL``
and one item. A level that rose twice while the ins counted 25 moves is another state that
happened to move at two of them (delivery_sail's triage.waiting carried sail.waiting's moves,
2 of 25, and scored as matched); a state the level's writes miss (each item gone between two
writes) is not measured by it, and stays the hidden state its counters imply. It must fill and drain in the
window by at least one of its unit (``fills_and_drains``): a level that only rises (a tally of
reports read, 5 to 10 and never less) is a count of something, and one whose moves are all under
one (a duration of tenths of a second) moves no whole unit; neither is the state items pass
through, however well its moves match. The test is by magnitude: the level's unit is not known
here (a duration in whole seconds passes it). A stage that fills and does not drain inside the
window is no measured state there; the passage's state is then the hidden one its counters imply. A level that
never reads above zero says nothing about which state it is, and is never chosen. Nor does a
coincidence with counters that count at almost every instant: when the instants within the
tolerance after the ins' (or the outs') events cover more than ``CHANCE`` of the window, a level
that moves at all would match them by chance (a memory gauge against request counters), so none
is chosen."""

from __future__ import annotations

from bisect import bisect_left
from itertools import pairwise
from statistics import median

from .series import Series

MATCHED = 0.8         # the share of a level's rises (and falls) that must come at the passage's events
CHANCE = 0.5          # the share of the window the events' tolerance may cover, at most, for a match to mean anything
SAME_TOTAL = 0.03


def fills_and_drains(changes) -> bool:
    """Whether a level both rose and fell by at least one in its own unit (``changes``: its moves):
    a buffer between two counters fills and drains, so one that never falls (or never rises) is a
    counter-like tally, and one whose moves are all under one (a duration of tenths of a second, a
    rating) moves no whole unit; neither is ever a buffer. By magnitude only: the unit is the
    caller's to check (``sd.restate.buffers`` keeps to the counters' unit). The one test for a
    measured state between counters, here and in ``sd.restate.measured_between``."""
    changes = list(changes)
    return any(d >= 1 - 1e-9 for d in changes) and any(d <= -1 + 1e-9 for d in changes)


def moves(cs: list[Series], start: float, end: float) -> float:
    """How many items the counters ``cs`` counted inside the window (a drop is a reset)."""
    return sum((b - a) if b >= a else b for c in cs for (_, a), (t, b) in pairwise(c.points) if start < t <= end)


def accounts(moved: float, counted: float) -> bool:
    """Whether a level's moves one way (``moved``, by magnitude) account for the counters' moves
    (``counted``): neither more nor fewer, within ``SAME_TOTAL`` and one item."""
    return abs(moved - counted) <= SAME_TOTAL * max(moved, counted) + 1 + 1e-9


def events(c: Series, start: float, end: float) -> list[float]:
    """The instants a counter counted, inside the window (a drop is a reset)."""
    return sorted(t for (_, a), (t, b) in pairwise(c.points) if start < t <= end and ((b - a) if b >= a else b) > 0)


def _hits(moves: list[float], at: list[float], tol: float) -> int:
    hit = 0
    for t in moves:
        i = bisect_left(at, t - tol)
        hit += 1 if i < len(at) and at[i] <= t + 1e-6 else 0
    return hit


def _covered(at: list[float], tol: float) -> float:
    """How much time lies within ``tol`` after one of the instants ``at`` (sorted)."""
    total, reach = 0.0, -float("inf")
    for t in at:
        total += t + tol - max(t, reach)
        reach = t + tol
    return total


def at_events(level: Series, ins: list[Series], outs: list[Series], start: float, end: float, step: float,
              counted: tuple[list[Series], list[Series]] | None = None) -> tuple[list, list] | None:
    """The level's rises at the ins' events and its falls at the outs' events, each as [matched,
    all, the counters' moves]; None when it is not the state between them. ``counted``: the ins
    and outs whose moves the level must account for, when ``ins`` and ``outs`` add copies of the
    same events (whose instants it may match, but whose moves are not more items)."""
    pts = [(t, v) for t, v in level.points if start - step < t <= end]
    rises = [t for (_, a), (t, b) in pairwise(pts) if b > a and t > start]
    falls = [t for (_, a), (t, b) in pairwise(pts) if b < a and t > start]
    if not fills_and_drains(b - a for (_, a), (t, b) in pairwise(pts) if t > start):
        return None
    tol = min(step, median([b - a for (a, _), (b, _) in pairwise(pts)] or [step])) + 1e-6
    into = sorted(t for c in ins for t in events(c, start - step, end))
    out = sorted(t for c in outs for t in events(c, start - step, end))
    if max(_covered(into, tol), _covered(out, tol)) > CHANCE * (end - start):
        return None                                  # events at almost every instant: a match by chance
    up, down = _hits(rises, into, tol), _hits(falls, out, tol)
    if up < MATCHED * len(rises) or down < MATCHED * len(falls) or len(rises) > len(into) * (1 + SAME_TOTAL) + 1:
        return None
    cin, cout = counted or (ins, outs)
    n_in, n_out = moves(cin, start, end), moves(cout, start, end)
    risen = sum(b - a for (_, a), (t, b) in pairwise(pts) if b > a and t > start)
    fallen = sum(a - b for (_, a), (t, b) in pairwise(pts) if b < a and t > start)
    if not accounts(risen, n_in) or not accounts(fallen, n_out):
        return None                                  # another state, moving at a few of the moves
    return [up, len(rises), round(n_in)], [down, len(falls), round(n_out)]


def state_level(levels: list[Series], ins: list[Series], outs: list[Series], *, start: float, end: float, step: float,
                writer_of, counted: tuple[list[Series], list[Series]] | None = None) -> tuple[Series, list, list] | None:
    """The level that is the state between ``ins`` and ``outs``: of those that qualify, the one
    with the most rises at the ins' events, then the ins' machine's (``counted``: ``at_events``)."""
    scored = [(m, lv) for lv in levels if (m := at_events(lv, ins, outs, start, end, step, counted))]
    if not scored:
        return None
    (up, down), level = max(scored, key=lambda x: (x[0][0][0], writer_of(x[1]) == writer_of(ins[0]), x[1].key))
    return level, up, down
