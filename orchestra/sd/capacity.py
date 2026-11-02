"""A level that counts a stock's servers busy: its capacity, not a second stock. The head chef's
busy flag, balanced exactly by inspections started less inspections done, holds one of the orders
inspecting while the chef works on it; two chefs' count of inspections under way, 0 to 2, holds two.
Kept as a stock it counts those orders twice, and its inflow comes from outside the model, which it
never did. In system dynamics a server is the capacity of one stock, not a second stock: the items
are one stock (the orders under inspection) and the servers are a parameter of its outflow.

Such a level (``busy``) of whole items, 0 to its most ``k``, is the capacity of ``stock`` when, on
the series' own writes (never the grid, whose step would decide it):

- its balance holds on its writes: at ``MATCHED`` of them it reads what its counters imply (ins
  less outs since the window began, apart from the items there before) at some instant within
  the tolerance (``between.follows``, as a passage's level must);
- it holds no more than the stock: at all but ``SAME_TOTAL`` of its writes, at most the stock's
  most within the tolerance;
- its items leave as the stock's do: ``MATCHED`` of its outflows' events are, one to one, events
  of some of the stock's outflows within the tolerance, and their totals agree within ``SAME_TOTAL``;
- the stock's own writer counts what fills it (the board counts the inspections started): another
  machine's count of its own work (a worker's busy level beside the items it
  works on) is that machine's stock, however its events coincide with the stock's;
- what fills it is no stock's flow (then its items arrive from a stock of the model: a shelf of 0
  and 1 the inspections passed fill, the state after a stock that its outflow fills): no counter
  another stock's balance takes, nor one counting the same events as such a flow, unless it
  counts this stock's own inflow's (the chef starts an order the moment it is baked).

The tolerance is ``ORDER`` (a second) plus the longer of the two levels' write intervals: two
writers sampling on their own schedules may stamp one instant up to an interval apart, and events
further apart than that are different instants. A writer whose events run later than its own write
interval (a chef who reports 8 s after the board on 5 s writes) is not resolved, and its level stays
a stock. The level is left out, with why, and shown in the stock's evidence (``capacity_of``:
capacity k, the share of time busy, the mean occupancy, its counters): a merged thing is shown,
never dropped (AGENTS.md rule 7). A stock the operator declared or a place its instrument built is
never judged."""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from itertools import combinations, pairwise
from statistics import median

from .between import MATCHED, ORDER, follows
from .resolution import value_at
from .series import Series, writer_of

SAME_TOTAL = 0.03    # how far apart two counts of the same events' totals may be; the share of its writes a server count may exceed the stock in
VIEW = "the same items as"   # the reason's opening: never an input (sd.inputs), never a level a passage runs through


def _window(s: Series, start: float, end: float) -> list[tuple[float, float]]:
    return [(t, v) for t, v in s.points if start < t <= end]


def capacity(s: Series, start: float, end: float) -> int | None:
    """The most a level of whole items held in the window, when it never went below 0 and held
    something: how many servers it counts. None for anything else."""
    vals = [v for _, v in _window(s, start, end)]
    if not vals or any(v < 0 or abs(v - round(v)) > 1e-9 for v in vals) or max(vals) < 1:
        return None
    return round(max(vals))


def interval(s: Series, start: float, end: float) -> float:
    """The level's usual gap between writes in the window."""
    ts = [t for t, _ in _window(s, start, end)]
    return median([b - a for a, b in pairwise(ts)]) if len(ts) > 1 else 0.0


def stamps(cs: list[Series], start: float, end: float) -> list[float]:
    """The instants the counters counted, once per item, inside the window (a drop is a reset)."""
    out: list[float] = []
    for c in cs:
        for (_, a), (t, b) in pairwise(c.points):
            n = (b - a) if b >= a else b
            if start < t <= end and n > 0:
                out += [t] * round(n)
    return sorted(out)


def matched(a: list[float], b: list[float], tol: float) -> int:
    """How many of ``a``'s instants have one of ``b``'s within ``tol``, each of ``b``'s used once."""
    used, hit = [False] * len(b), 0
    for t in a:
        i = bisect_left(b, t - tol)
        while i < len(b) and b[i] <= t + tol and used[i]:
            i += 1
        if i < len(b) and b[i] <= t + tol:
            used[i], hit = True, hit + 1
    return hit


def same_events(a: list[float], b: list[float], tol: float) -> bool:
    """Two counts of the same events, by their instants: totals within ``SAME_TOTAL`` of each
    other, and ``MATCHED`` of ``a``'s matched to ``b``'s within ``tol`` (as a passage's moves)."""
    if not a or abs(len(a) - len(b)) > max(1.0, SAME_TOTAL * len(b)):
        return False
    return matched(a, b, tol) >= MATCHED * len(a) - 1e-9


def held_within(busy: Series, stock: Series, start: float, end: float, tol: float) -> bool:
    """Whether at all but ``SAME_TOTAL`` of ``busy``'s writes it held no more than the stock's most
    within ``tol`` (a writer that once reports a moment late)."""
    ts = [t for t, _ in stock.points]
    writes = _window(busy, start, end)
    over = 0
    for t, v in writes:
        lo, hi = bisect_left(ts, t - tol), bisect_right(ts, t + tol)
        over += v > max([value_at(stock, t - tol), *(stock.points[i][1] for i in range(lo, hi))]) + 1e-9
    return bool(writes) and over <= SAME_TOTAL * len(writes)


def occupancy(s: Series, start: float, end: float) -> float | None:
    """The level's mean over the window, each value weighted by how long it was held."""
    pts = [(start, value_at(s, start)), *_window(s, start, end), (end, None)]
    span = end - start
    return sum(v * (b - a) for (a, v), (b, _) in pairwise(pts)) / span if span > 0 else None


def view_of(entry: tuple, found: list, start: float, end: float, implied: frozenset | set = frozenset(), apart=None) -> dict | None:
    """The stock ``entry``'s level is the capacity of, with the evidence, or None. ``implied``: the
    keys of stocks whose level a passage's counters imply (``sd.passing``), never a host: a measured
    level is never folded into a state no series measures. ``apart(a, b)``: two levels that name
    different things (pods in us-east and in us-west, two consumer groups' lag), never one's capacity."""
    s, terms = entry[0], entry[1]
    k = capacity(s, start, end)
    ins, outs = [c for c, sg in terms if sg > 0], [c for c, sg in terms if sg < 0]
    if k is None or not ins or not outs:
        return None
    best = None
    for a, aterms, *_ in found:
        if a is s or not a.points or a.key in implied or (apart and apart(s, a)):
            continue
        # the start of service is the stock's own record (the board counts the inspections it
        # starts): another machine's count of its own work that coincides with the stock's items
        # (a worker's busy level, beside the items it works on) is that machine's stock, and which
        # machine serves which flow is only ever a hypothesis (AGENTS.md rule 6)
        if writer_of(a) is None or not any(writer_of(c) == writer_of(a) for c in ins):
            continue
        tol = ORDER + max(interval(s, start, end), interval(a, start, end))
        agree, said = follows(_window(s, start - tol, end), ins, outs, start, end, tol, tol)
        if not said or agree < MATCHED * said:
            continue                             # it does not read what its counters imply on its own writes
        if not held_within(s, a, start, end, tol):
            continue
        # what fills it is no stock's flow: never a counter another stock's balance (or this
        # stock's outflow) takes, and never one counting the same events as such a flow unless
        # it is this stock's own inflow (the chef starts an order the moment it is baked)
        mine_in = [c for c, sg in aterms if sg > 0]
        flows = [cb for x in found if x[0] is not s and x[0] is not a for cb, _ in x[1]] + [c for c, sg in aterms if sg < 0]
        at = lambda cs: stamps(cs, start, end)
        if any(cb is c for c in ins for cb in flows) or any(
                same_events(at([c]), at([cb]), tol) and not any(m is c or same_events(at([c]), at([m]), tol) for m in mine_in)
                for c in ins for cb in flows):
            continue
        mine = at(outs)
        aouts = [c for c, sg in aterms if sg < 0]
        ends = next((sub for n in range(len(aouts), 0, -1) for sub in combinations(aouts, n) if same_events(mine, at(list(sub)), tol)), None)
        if ends is not None:
            best = (a, ends, tol)
            break
    if best is None:
        return None
    a, ends, tol = best
    mean = occupancy(s, start, end)
    return {"stock": a, "record": {
        "series": s.key, "capacity": k, "utilisation": None if mean is None else round(mean / k, 4),
        "mean_occupancy": None if mean is None else round(mean, 4), "tolerance_s": round(tol, 3),
        "starts": [c.key for c in ins], "ends": [c.key for c in outs], "ends_as": [c.key for c in ends]}}


def why(s: Series, a: Series, rec: dict) -> str:
    k, u, m = rec["capacity"], rec["utilisation"], rec["mean_occupancy"]
    busy = "" if u is None else f", busy {u:.0%} of the time" + ("" if k == 1 else f" (mean occupancy {m:.2f})")
    return (f"{VIEW} {a.key}: its capacity of {k} ({'a flag' if k == 1 else f'{k} servers'}), not a second stock. On its own "
            f"writes it reads what its counters imply, holds no more than that stock, and its items leave as that stock's "
            f"do ({', '.join(rec['ends_as'])}), within {rec['tolerance_s']:g} s; what fills it is no stock's flow. The items are "
            f"counted once, in that stock, shown in its drawer: capacity {k}{busy}")


def capacity_views(found: list, left_out: dict[str, str], start: float, end: float, protected: frozenset | set = frozenset(),
                   implied: frozenset | set = frozenset(), apart=None) -> tuple[list, dict[str, list[dict]], dict[str, str]]:
    """``found`` without the levels that are another stock's capacity; per kept stock's key, its
    capacities (``capacity_of``); and per counter of one no stock now uses, why (for ``left_out``).
    ``protected``: keys never judged (declared, constructed, a passage's); ``implied``: never hosts; ``apart``: as ``view_of``."""
    kept = list(found)
    views: dict[str, list[dict]] = {}
    notes: dict[str, str] = {}
    for x in found:
        s = x[0]
        if s.key in protected or s.key in views:
            continue
        v = view_of(x, kept, start, end, implied, apart)
        if v is None:
            continue
        a, rec = v["stock"], v["record"]
        kept = [y for y in kept if y[0] is not s]
        views.setdefault(a.key, []).append(rec)
        left_out[s.key] = why(s, a, rec)
        for key in rec["starts"]:
            notes[key] = f"the start of {s.key}, the capacity of {a.key}: it moves items within that stock, not between stocks"
        for key in rec["ends"]:
            notes[key] = f"the end of {s.key}, the capacity of {a.key}: the same items leaving it as {', '.join(rec['ends_as'])}"
    return kept, views, notes
