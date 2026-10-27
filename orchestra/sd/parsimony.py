"""A balance's counters that one unused counter counts at once, replaced by it.

A level's balance is found by a search that charges per counter, and it can still settle on two
or three counters whose signed sum another counter, one no balance uses, counts by itself: the
free takers balanced by the customers' orders less the app's orders, where the takers' own count
of the orders they took is exactly that difference. The difference is algebra and the one
counter is the flow: with it, the app's orders no longer drain the takers. The set is replaced
when the one counter counts the same events as its signed sum, each stamped a moment before or
after the other (their running totals never more than one event apart, in all but
``CANCEL_STEPS`` of the steps either moved: two machines record an order a step apart either
way), and the balance still fits as a stock's (``fits``); of several, the one that leaves the
balance fitting best.

The level's own machine's counters are never in the set: they are its record of its
transitions, and another machine's count of their sum only mirrors them (the customers served
and those who gave up are the customers' own, whatever yelp's reviews add up to). Orchestra's
event counters are never the one counter (``sd.restate`` splits them into the machine counters
they sum, which are the flows), nor is a counter that a restate pass replaced by its parts
(``apart``)."""

from __future__ import annotations

from itertools import accumulate, combinations

from .balance import MIN_EVENTS, fit_of
from .collinear import CANCEL_STEPS
from .series import EVENT_COUNTER, Series

MAX_SET = 3      # a set of at most this many counters is replaced by one


def same_events(a: list[float], b: list[float]) -> bool:
    """Whether two counts per step count the same events, each a moment before or after the other.
    Fewer than ``MIN_EVENTS`` say nothing: two rare counters are always within an event or two."""
    ta, tb = sum(a), sum(b)
    if ta < MIN_EVENTS or abs(ta - tb) > max(1.0, 0.03 * tb):
        return False
    moved = sum(1 for x, y in zip(a, b) if x or y)
    apart = sum(1 for d in accumulate(x - y for x, y in zip(a, b)) if abs(d) > 1 + 1e-9)
    return moved > 0 and apart <= CANCEL_STEPS * moved


def fewer_counters(found: list, counters: list[Series], masks: dict[str, list[int]], fits, apart: set[str], writer_of
                   ) -> tuple[list, dict[str, str]]:
    """The balances with each such set replaced, and per counter taken out, why."""
    used = {c.key for _, terms, _, _ in found for c, _ in terms}
    free = [c for c in counters if c.key not in used and c.key not in apart and c.name != EVENT_COUNTER and any(c.deltas)]
    out, notes = [], {}
    for s, terms, r2, exact in found:
        changed = True
        while changed and free:
            changed = False
            best = None
            for size in range(2, min(MAX_SET, len(terms)) + 1):
                for sub in combinations(terms, size):
                    if any(writer_of(c) is not None and writer_of(c) == writer_of(s) for c, _ in sub):
                        continue
                    summed = [sum(sign * c.deltas[i] for c, sign in sub) for i in range(len(s.deltas))]
                    t = 1 if sum(summed) >= 0 else -1
                    for u in free:
                        if not same_events([t * x for x in summed], u.deltas):
                            continue
                        terms2 = [x for x in terms if x not in sub] + [(u, t)]
                        r2b, exact2 = fit_of(s, terms2, masks[s.key])
                        if fits(s, r2b, exact2) and (best is None or (r2b, exact2) > best[0]):
                            best = ((r2b, exact2), sub, u, terms2)
                if best:
                    break
            if best:
                (r2, exact), sub, u, terms = best
                free.remove(u)
                for c, sign in sub:
                    notes[c.key] = (f"with {' and '.join(k.key for k, _ in sub if k is not c)} in the balance of {s.key}, "
                                    f"the same as {u.key}, which counts their {'sum' if all(sg == sign for _, sg in sub) else 'difference'} itself")
                changed = True
        out.append((s, terms, r2, exact))
    return out, notes
