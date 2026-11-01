"""Which measured level is the state an item passes through within a step.

The grid samples a level at whole steps, so a state each item leaves within a second reads empty
at every step; its raw points do not. The level that rises at an instant one of the passage's
ins counted (at it, or no later than the level's own write interval after it), and falls at an
instant one of its outs counted, is that state: most of its rises and of its falls (``MATCHED``)
must, and it must have risen no more often than the ins counted. At each of its own writes it
must read what the counters imply (``follows``): the items the ins moved in less those the outs
moved out, up to then, give or take ``ORDER`` seconds for the order of two writers' writes,
apart from a constant (the items there before). A state sampled coarsely misses the items that come and
go between two of its writes, and so do the counters' totals at those writes; a level that is
another state reads zero where the counters say an item is in, and moves where they say nothing
moved (delivery_sail's triage.waiting rose at 2 of sail.waiting's 25 moves and was bound as it):
at most ``1 - MATCHED`` of the writes where either says something may disagree. It must fill and drain in the
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

from bisect import bisect_left, bisect_right
from itertools import pairwise
from statistics import median

from .series import Series

MATCHED = 0.8         # the share of a level's rises (and falls) that must come at the passage's events
CHANCE = 0.5          # the share of the window the events' tolerance may cover, at most, for a match to mean anything
SAME_TOTAL = 0.03
ORDER = 1.0           # seconds: how far apart two writers' writes of one instant may be stamped


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


def _counts(c: Series, start: float, end: float) -> list[tuple[float, float]]:
    return [(t, (b - a) if b >= a else b) for (_, a), (t, b) in pairwise(c.points) if start < t <= end and ((b - a) if b >= a else b) > 0]


def follows(pts: list[tuple[float, float]], cin: list[Series], cout: list[Series], start: float, end: float, step: float,
            tol: float) -> tuple[int, int]:
    """Of the level's writes in the window where it says something is there, or the counters say
    so throughout ``tol`` of it, how many read what the counters imply: [agreeing, all such writes]. The implied level at a write
    is the ins' moves less the outs' since the window began, at any instant within ``tol`` of
    it (``tol``: the lesser of ``ORDER`` and the level's write interval); the level is compared
    with it apart from the offset most writes share (the items there before)."""
    moved = sorted([*((t, n) for c in cin for t, n in _counts(c, start - step, end)),
                    *((t, -n) for c in cout for t, n in _counts(c, start - step, end))])
    at = [t for t, _ in moved]
    run = [0.0]
    for _, n in moved:
        run.append(run[-1] + n)                     # run[i]: the implied level after the first i moves
    writes = [(t, v) for t, v in pts if t > start]
    if not writes:
        return 0, 0
    offsets: dict[float, int] = {}
    for t, v in writes:
        k = round(v - run[bisect_right(at, t)], 6)
        offsets[k] = offsets.get(k, 0) + 1
    base = max(offsets, key=lambda k: (offsets[k], -abs(k)))
    agree = said = 0
    for t, v in writes:
        lo, hi = bisect_right(at, t - tol), bisect_right(at, t + tol)
        implied = run[lo:hi + 1]
        if abs(v - base) < 0.5 and any(abs(x) < 0.5 for x in implied):
            continue                                 # nothing there, by the level, and maybe by the counters
        said += 1
        agree += 1 if any(abs(v - base - x) < 0.5 for x in implied) else 0
    return agree, said


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
    all, the items the matched ones moved, the items the counters moved]; None when it is not the
    state between them. ``counted``: the ins and outs whose moves the level must follow, when
    ``ins`` and ``outs`` add copies of the same events (whose instants it may match, but whose
    moves are not more items)."""
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
    agree, said = follows(pts, cin, cout, start, end, step, min(tol, ORDER))
    if agree < MATCHED * said:
        return None                                  # another state: it does not read what the counters imply
    rose = {t: b - a for (_, a), (t, b) in pairwise(pts) if b > a and t > start}
    fell = {t: a - b for (_, a), (t, b) in pairwise(pts) if b < a and t > start}
    hit_in = sum(n for t, n in rose.items() if _hits([t], into, tol))
    hit_out = sum(n for t, n in fell.items() if _hits([t], out, tol))
    return ([up, len(rises), round(hit_in, 6), round(moves(cin, start, end), 6)],
            [down, len(falls), round(hit_out, 6), round(moves(cout, start, end), 6)])


def state_level(levels: list[Series], ins: list[Series], outs: list[Series], *, start: float, end: float, step: float,
                writer_of, counted: tuple[list[Series], list[Series]] | None = None) -> tuple[Series, list, list] | None:
    """The level that is the state between ``ins`` and ``outs``: of those that qualify, the one
    with the most rises at the ins' events, then the ins' machine's (``counted``: ``at_events``)."""
    scored = [(m, lv) for lv in levels if (m := at_events(lv, ins, outs, start, end, step, counted))]
    if not scored:
        return None
    (up, down), level = max(scored, key=lambda x: (x[0][0][0], writer_of(x[1]) == writer_of(ins[0]), x[1].key))
    return level, up, down
