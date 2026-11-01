"""A flag that is a stock's capacity of one: a level of 0 and 1 balanced exactly (the head chef
busy: inspections started less inspections done) whose items are already in another stock (the
orders inspecting). It is one while one of that stock's items is in it, it never holds more than
that stock does, every item leaving it leaves that stock too (its outflows count the same events as
some of the stock's), and what fills it is no other stock's flow: its inflow moves an item within
the stock (an order waiting for the chef starts its inspection), not into it. Kept as a stock it
counts those items twice, and its inflow comes from outside the model, which it never did.

In system dynamics a single server's "busy" is the capacity of one stock, not a second stock: the
items are one stock (the orders under inspection) and the server is a parameter of its outflow
(capacity 1, busy so much of the time). So the flag is left out of the stocks, with why, and
shown in that stock's evidence as its view (``views``: capacity 1, utilisation, its counters): a
merged thing is shown, never dropped (AGENTS.md rule 7).

What it does not take: a shelf of 0 and 1 (its inflow, the inspections passed, is another stock's
outflow, so its items arrive from a stock of the model); a 0/1 level beside the customers waiting
(contained, but its items leave by other events than theirs); a stock the operator declared or a
pile its instrument built (never re-judged)."""

from __future__ import annotations

from itertools import combinations

from .drivers import behind
from .series import Series

CONTAINED = 0.97     # the share of steps the flag may not exceed the stock in (two instruments' writes a moment apart)
SAME_STEPS = 0.03    # as sd.discover: counts of the same events differ in no more than this share of the steps they moved in


def is_flag(s: Series) -> bool:
    """A level that only ever takes 0 and 1, and was 1 at some point."""
    values = {v for _, v in s.points}
    return values <= {0.0, 1.0} and 1.0 in values


def _summed(terms: list, sign: int, steps: list[int], n: int) -> list[float]:
    on = set(steps)
    return [sum(c.deltas[i] for c, sg in terms if sg == sign) if i in on else 0.0 for i in range(n)]


def same_events(a: list[float], b: list[float]) -> bool:
    """Two per-step counts of the same events: their totals agree and they differ in no more than
    ``SAME_STEPS`` of the steps either moved in, or one runs no more than a step behind the other."""
    ta, tb = sum(a), sum(b)
    if ta <= 0 or abs(ta - tb) > max(1.0, SAME_STEPS * tb):
        return False
    moved = sum(1 for x, y in zip(a, b) if x or y)
    differ = sum(1 for x, y in zip(a, b) if x != y)
    return differ <= SAME_STEPS * moved or behind(a, b) or behind(b, a)


def contained(flag: Series, stock: Series, steps: list[int]) -> float:
    """The share of ``steps`` after which the flag holds no more than the stock."""
    both = [i for i in steps if i + 1 < min(len(flag.values), len(stock.values))]
    if not both:
        return 0.0
    return sum(1 for i in both if flag.values[i + 1] <= stock.values[i + 1] + 1e-9) / len(both)


def view_of(flag: tuple, found: list, masks: dict[str, list[int]], same) -> dict | None:
    """The stock the flag is a capacity-of-one view of, with the evidence, or None."""
    s, terms, _, exact = flag
    ins, outs = [c for c, sg in terms if sg > 0], [c for c, sg in terms if sg < 0]
    if not ins or not outs:
        return None
    steps = masks.get(s.key) or []
    n = len(s.deltas)
    best = None
    for a, aterms, _, _ in found:
        if a is s:
            continue
        others = [x for x in found if x[0] is not s and x[0] is not a]
        # what fills the flag is no stock's flow (then its items come from a stock of the model:
        # from this one, the flag is the state after it), unless it is this stock's own inflow too
        # (the item enters both at once, or a step apart)
        mine_in = [cb for cb, sg in aterms if sg > 0]
        flows = [cb for _, bterms, _, _ in others for cb, _ in bterms] + [cb for cb, sg in aterms if sg < 0]
        if any((cb is c or same(c, cb)) and not any(m is c or same(c, m) for m in mine_in) for c in ins for cb in flows):
            continue
        shared = sorted(set(steps) & set(masks.get(a.key) or []))
        share = contained(s, a, shared)
        if share < CONTAINED:
            continue
        mine = _summed(terms, -1, shared, n)
        aouts = [c for c, sg in aterms if sg < 0]
        ends = next((sub for k in range(len(aouts), 0, -1) for sub in combinations(aouts, k)
                     if same_events(mine, _summed([(c, -1) for c in sub], -1, shared, n))), None)
        if ends is None:
            continue
        cand = (share, a, ends)
        if best is None or share > best[0]:
            best = cand
    if best is None:
        return None
    share, a, ends = best
    held = [s.values[i + 1] for i in steps if i + 1 < len(s.values)]
    return {"stock": a, "record": {
        "series": s.key, "capacity": 1, "utilisation": round(sum(held) / len(held), 4) if held else None,
        "contained_steps": round(share, 4), "exact_steps": round(exact, 4),
        "starts": [c.key for c in ins], "ends": [c.key for c in outs], "ends_as": [c.key for c in ends]}}


def capacity_views(found: list, masks: dict[str, list[int]], left_out: dict[str, str], same,
                   protected: frozenset | set = frozenset()) -> tuple[list, dict[str, list[dict]], dict[str, str]]:
    """``found`` without the flags that are another stock's capacity of one; per kept stock's key,
    its views; and per counter of a view no stock now uses, why (for ``left_out``). ``same``: two
    counters of the same events; ``protected``: keys never judged (declared, constructed)."""
    kept = list(found)
    views: dict[str, list[dict]] = {}
    notes: dict[str, str] = {}
    for x in found:
        s = x[0]
        if s.key in protected or not is_flag(s):
            continue
        v = view_of(x, kept, masks, same)
        if v is None:
            continue
        a, rec = v["stock"], v["record"]
        kept = [y for y in kept if y[0] is not s]
        views.setdefault(a.key, []).append(rec)
        u = rec["utilisation"]
        left_out[s.key] = (f"a flag: the same items as {a.key}, a capacity-of-one view of it (it holds no more than that stock "
                           f"in {rec['contained_steps']:.0%} of steps, and every item leaving it leaves that stock too, counted "
                           f"by {', '.join(rec['ends_as'])}); its balance is exact, but the items are counted once, in that "
                           f"stock, shown in its drawer: capacity 1" + (f", busy {u:.0%} of the time" if u is not None else ""))
        for k in rec["starts"]:
            notes[k] = f"the start of {s.key}, the capacity-of-one view of {a.key}: it moves items within that stock, not between stocks"
        for k in rec["ends"]:
            notes[k] = f"the end of {s.key}, the capacity-of-one view of {a.key}: the same items leaving it as {', '.join(rec['ends_as'])}"
    return kept, views, notes
