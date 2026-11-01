"""Balances restated once every level has one, with what the other balances show.

A balance is found for each level alone, on an objective that charges per counter, so it takes
the one counter that is cheapest where several say the same: Orchestra's count of an event where
machine counters count the same events apart, another machine's copy of this machine's events,
one of two machines' counts of one flow. Alone those are fine; together they split flows through
outside (a stock drains by the event counter, the next fills by a machine's) or lose the flow that
joins two stocks (each took its own machine's copy). Three passes, in this order, put that right:

- ``split_event_counters``: Orchestra's event counter gives way to the machine counters that sum
  to it (``sd.collinear.decompose``) when there is evidence that the parts are flows of their own:
  one is claimed by another stock's balance, or is the level's own machine's count;
- ``split_foreign_counters``: another machine's counter that no other stock claims gives way to the
  level's own machine's counters that sum to it (the machine's record of its transitions, which
  the other only mirrors). A counter two stocks claim is the flow between them and stays;
- ``unify_same_flows``: two counters of the same events, each in a balance (two machines' counts
  of one event; a move recorded in two hops, a moment apart, through a state the grid never sees
  held), become one in every balance, so the one flow runs between the stocks and, where the
  event moves two machines' stocks, is a co-flow (``sd.ends``); never two a measured level lies
  between (``measured_between``).

A restated balance must still fit as a stock's (the caller's ``fits``), or the level keeps what it
had. Each pass returns the balances and, per counter replaced, why (for the record, when no
balance keeps it).

Right after the join (so identification judges each stock on its own counters) and again once
every balance is final, ``own_counters_back`` gives each stock back its own writer's
counter of events ``unify_same_flows`` joined to another writer's: one event, two writers' records
(the worker's review request moves a ticket and starts the reviewer's turn), each stock balanced by
its own, the pair still one flow and a co-flow with one rate (``sd.ends``)."""

from __future__ import annotations

from itertools import combinations

from .balance import MIN_EVENTS, fit_of
from .between import fills_and_drains
from .collinear import decompose
from .drivers import behind
from .live import balance_steps
from .series import EVENT_COUNTER, Series, writer_of, written_by


def _replace(s: Series, terms: list, c: Series, parts: list, steps: list[int], fits) -> tuple[list, float, float] | None:
    """The balance with ``c`` replaced by ``parts`` (each with its sign), if it still fits."""
    sign = next(sg for k, sg in terms if k is c)
    terms2 = [(k, sg) for k, sg in terms if k is not c] + [(p, sign) for p in parts]
    r2, exact = fit_of(s, terms2, steps)
    return (terms2, r2, exact) if fits(s, r2, exact) else None


def _claimed_by_others(found: list, s: Series) -> set[str]:
    return {k.key for o, oterms, _, _ in found if o is not s for k, _ in oterms}


def split_event_counters(found: list, counters: list[Series], masks: dict[str, list[int]], writer_of, fits, floor: float
                         ) -> tuple[list, dict[str, str]]:
    """Orchestra's event counters in the balances, each replaced by the machine counters that sum
    to it (``floor``: the events a sum of parts needs). ``order.queued`` is ``placed + returns +
    failed + leases``: four flows into the waiting orders, two of them from other stocks. Where
    two sets sum to it alike, the level's own machine's parts win over another machine's copy."""
    out, notes = [], {}
    machine = [c for c in counters if written_by(c)]
    for s, terms, r2, exact in found:
        for c, _ in list(terms):
            if c.name != EVENT_COUNTER:
                continue
            used = {k.key for k, _ in terms}
            own = {k.key for k in machine if writer_of(k) == writer_of(s)}
            parts = decompose(c, [k for k in machine if k.key not in used], masks[s.key], sizes=(1, 2, 3, 4),
                              required=_claimed_by_others(found, s) | own, floor=floor, own=own)
            got = _replace(s, terms, c, parts, masks[s.key], fits) if parts else None
            if got:
                terms, r2, exact = got
                notes[c.key] = f"the same as {' + '.join(p.key for p in parts)} (counts the same events, which those count apart)"
        out.append((s, terms, r2, exact))
    return out, notes


def split_foreign_counters(found: list, counters: list[Series], masks: dict[str, list[int]], writer_of, fits, floor: float
                           ) -> tuple[list, dict[str, str]]:
    """Another machine's counters in a balance that no other stock claims, each replaced by the
    level's own machine's counters that sum to it: yelp's reviews are the customers served plus
    those who gave up, and the customers' waiting is the customers' to account for."""
    out, notes = [], {}
    machine = [c for c in counters if written_by(c)]
    for s, terms, r2, exact in found:
        own = [c for c in machine if writer_of(c) == writer_of(s)]
        if not own:
            out.append((s, terms, r2, exact))
            continue
        others = _claimed_by_others(found, s)
        for c, _ in list(terms):
            if c.name == EVENT_COUNTER or any(c is o for o in own) or c.key in others:
                continue
            used = {k.key for k, _ in terms}
            parts = decompose(c, [k for k in own if k.key not in used], masks[s.key], sizes=(1, 2, 3), floor=floor)
            got = _replace(s, terms, c, parts, masks[s.key], fits) if parts else None
            if got:
                terms, r2, exact = got
                notes[c.key] = f"the same as {' + '.join(p.key for p in parts)} (counts the same events, which those count apart)"
        out.append((s, terms, r2, exact))
    return out, notes


def _held_together(found: list, a: Series, b: Series) -> bool:
    """Whether one balance holds both counters: with opposite signs, that stock is the buffer
    between them (put on a shelf and taken a moment later), and they are its inflow and outflow,
    not one flow."""
    return any(any(c is a for c, _ in terms) and any(c is b for c, _ in terms) for _, terms, _, _ in found)


def measured_between(levels: list[Series], a: Series, b: Series) -> bool:
    """Whether a measured level is the buffer between two counters: one fills it and the other
    drains it (either way round), within half a unit in every step where the level and both
    counters are live, and in at least one of those steps the counters differ and the level moved
    by a whole unit with them. However seldom it moved (the shelf an order leaves within seconds,
    read as held in two steps of an hour, too few to be a stock), the grid tells the two apart in
    its steps: its inflow and its outflow, never one flow. A gauge whose moves are all fractions
    (a rating, a mean age) explains no difference of counts, and is never a buffer; nor is a level
    that never falls (or never rises) by a whole unit in those steps: a buffer fills and drains
    (``sd.between.fills_and_drains``, the test ``sd.between`` puts to a state's raw points)."""
    for lv in levels:
        if lv.counter:
            continue
        steps = balance_steps(lv, [a, b])
        if not fills_and_drains(lv.deltas[i] for i in steps):
            continue
        if not any(abs(lv.deltas[i]) >= 1 and a.deltas[i] != b.deltas[i] for i in steps):
            continue
        if any(fit_of(lv, [(a, sg), (b, -sg)], steps)[1] >= 1.0 - 1e-9 for sg in (1, -1)):
            return True
    return False


def buffers(levels: list[Series], unit: dict[str, str]):
    """``measured_between`` over the levels in the counters' own unit, for ``unify_same_flows``."""
    return lambda a, b: measured_between([lv for lv in levels if unit[lv.key] == unit[a.key]], a, b)


def unify_same_flows(found: list, masks: dict[str, list[int]], same, first_stamped, writer_of, fits,
                     between=lambda a, b: False) -> tuple[list, dict[str, str], list[tuple[Series, Series]]]:
    """Two counters of the same events (``same``: in the same steps, or one stamped up to a step
    after the other), each in a balance, become one counter in every balance, unless a balance
    holds both (``_held_together``) or a measured level lies between them (``between``:
    ``measured_between``). Within a machine the flow then runs between its stocks
    instead of leaving one and entering the other from outside; where the two counters are two
    machines' records of one event moving each one's own material (an order accepted leaves the
    board's waiting and takes one of the kitchen's cooks), the one counter is claimed by both
    machines' stocks and ``sd.ends`` makes it a flow and a co-flow. The counter kept is the one every balance still
    fits with (``fits``); between two, the one that moves material between its own machine's
    stocks (its flow is the move, the other's the co-flow), then one its own machine's stock
    holds at all (the board's count of the orders rejected back into its waiting, over the
    customers' count of the same returns: a stock's own machine's counters come first), then the
    one stamped first (the flow's events are judged against the levels just before them, which
    the later stamp has already moved), then the one that leaves the balances fitting best. Returns the balances,
    why each counter dropped was (by key), and the pairs joined (kept, dropped). Where the dropped
    one was another writer's stock's own, that stock takes it back once every balance is final
    (``own_counters_back``)."""
    found = list(found)
    notes: dict[str, str] = {}
    joined: list[tuple[Series, Series]] = []
    used = {c.key: c for _, terms, _, _ in found for c, _ in terms}
    gone: set[str] = set()
    for a, b in combinations(sorted(used), 2):
        ca, cb = used[a], used[b]
        if a in gone or b in gone or _held_together(found, ca, cb) or not same(ca, cb) or between(ca, cb):
            continue
        best = None
        for keep, drop in ((ca, cb), (cb, ca)):
            trial, total, ok = [], 0.0, True
            for s, terms, r2, exact in found:
                if any(c is drop for c, _ in terms):
                    terms = [(keep if c is drop else c, sg) for c, sg in terms]
                    r2, exact = fit_of(s, terms, masks[s.key])
                    ok = ok and fits(s, r2, exact)
                trial.append((s, terms, r2, exact))
                total += r2
            if not ok:
                continue
            own = {sg for s, terms, _, _ in trial for c, sg in terms if c is keep and writer_of(s) == writer_of(keep)}
            rank = (len(own) == 2, len(own) >= 1, first_stamped(keep, drop), total)
            if best is None or rank > best[0]:
                best = (rank, trial, keep, drop)
        if best is not None:
            _, found, keep, drop = best
            notes[drop.key] = f"the same as {keep.key} (counts the same events)"
            joined.append((keep, drop))
            gone.add(drop.key)
    return found, notes, joined


def own_counters_back(found: list, joined: list[tuple[Series, Series]], masks: dict[str, list[int]], writer_of, fits
                      ) -> tuple[list, dict[str, tuple[Series, Series]]]:
    """Each stock whose writer wrote a counter that ``unify_same_flows`` joined to another writer's
    (``joined``: (kept, dropped)) takes its own back, where its balance still holds the kept one and
    still fits with its own: no stock is balanced by another instrument's count of its events while
    its own exists. Orchestra's event counter is no one's own. Returns the balances and, per counter
    given back (by its key), the pair (kept, given back): the two stay one flow and a co-flow
    (``sd.ends.claims``)."""
    out, back = [], {}
    for s, terms, r2, exact in found:
        for keep, drop in joined:
            w = writer_of(drop)
            if (EVENT_COUNTER in (keep.name, drop.name) or w is None or w == writer_of(keep) or writer_of(s) != w
                    or not any(c is keep for c, _ in terms) or any(c is drop for c, _ in terms)):
                continue
            mine = [(drop if c is keep else c, sg) for c, sg in terms]
            r2b, exact2 = fit_of(s, mine, masks[s.key])
            if fits(s, r2b, exact2):
                terms, r2, exact = mine, r2b, exact2
                back[drop.key] = (keep, drop)
        out.append((s, terms, r2, exact))
    return out, back


SAME_STEPS = 0.03     # a bus count and a counter that differ in no more than this share of the steps they moved in count alike


def bus_copy(ev: Series, other: Series) -> bool:
    """Whether Orchestra's count of an event type (``ev``) and another counter count the same
    moments: both name the event's machine (its ``source``; the other, or a counter it stands for,
    carries that machine as a label value, ``by="merge_gate"``), and they count alike: at least
    ``MIN_EVENTS``, totals that agree, in the same steps or up to a step apart either way (the bus
    and an instrument stamp one moment apart). Timing alone is no evidence: two machines on one
    period (a job each minute) count in the same steps every time."""
    if ev.name != EVENT_COUNTER or other.name == EVENT_COUNTER:
        return False
    total, da, db = sum(ev.deltas), ev.deltas, other.deltas
    if total < MIN_EVENTS or abs(total - sum(db)) > max(1.0, SAME_STEPS * total):
        return False
    moved = sum(1 for x, y in zip(da, db) if x or y)
    return sum(1 for x, y in zip(da, db) if x != y) <= SAME_STEPS * moved or behind(da, db) or behind(db, da)


def _names(c: Series, machine: str) -> bool:
    return any(v.partition("/")[0] == machine for v in c.labels.values())


def bus_copies(found: list, back: dict[str, tuple[Series, Series]], stands_for: dict[str, list[Series]], apart
               ) -> dict[str, tuple[Series, Series]]:
    """Orchestra's event counters in the final balances, each filed under a counter of the same
    moments that a balance holds (``bus_copy``; the counter, or one of the counters it stands for,
    ``stands_for``, names the event's machine; never two counters ``apart`` or one balance holds
    together, which are its inflow and outflow): the bus count is secondary (AGENTS.md rule 7), so
    where its machine's counter of the same moments is a flow, it is never a flow of its own. The
    balance keeps it (its stamps may fit a level read just after, where the other's, a step later,
    do not: a repository read when the bus heard the landing); ``sd.ends.claims`` files its claims
    under the other, one flow and a co-flow, as for ``own_counters_back``. A bus count with no such
    counter stays a flow. Returns ``back`` (per counter filed, by key: (the flow's counter, the
    counter filed)) with the bus counts added, each under the counter that one is itself filed
    under, if any, and anything filed under a bus count moved with it."""
    held = {c.key: c for _, terms, _, _ in found for c, _ in terms}
    out = dict(back)
    for key, c in sorted(held.items()):
        machine = writer_of(c)
        if c.name != EVENT_COUNTER or machine is None:
            continue
        flows = [k for k in held.values() if bus_copy(c, k) and not apart(c, k) and not _held_together(found, c, k)
                 and any(_names(x, machine) for x in [k, *stands_for.get(k.key, ())])]
        if not flows:
            continue
        k = min(flows, key=lambda k: (sum(1 for x, y in zip(c.deltas, k.deltas) if x != y), k.key))
        k = out[k.key][0] if k.key in out else k
        out[key] = (k, c)
        for x, (keep, drop) in list(out.items()):
            if keep is c:
                out[x] = (k, drop)
    return out
