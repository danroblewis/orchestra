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
- ``unify_same_flows``: two machines' counters of the same events (``same_flow``) become one in
  every balance, the one that fits the balances best.

A restated balance must still fit as a stock's (the caller's ``fits``), or the level keeps what it
had. Each pass returns the balances and, per counter replaced, why (for the record, when no
balance keeps it)."""

from __future__ import annotations

from itertools import combinations

from .balance import fit_of
from .collinear import decompose
from .series import EVENT_COUNTER, Series


def _replace(s: Series, terms: list, c: Series, parts: list, steps: list[int], fits) -> tuple[list, float, float] | None:
    """The balance with ``c`` replaced by ``parts`` (each with its sign), if it still fits."""
    sign = next(sg for k, sg in terms if k is c)
    terms2 = [(k, sg) for k, sg in terms if k is not c] + [(p, sign) for p in parts]
    r2, exact = fit_of(s, terms2, steps)
    return (terms2, r2, exact) if fits(s, r2, exact) else None


def _claimed_by_others(found: list, s: Series) -> set[str]:
    return {k.key for o, oterms, _, _ in found if o is not s for k, _ in oterms}


def split_event_counters(found: list, counters: list[Series], masks: dict[str, list[int]], machine_of, fits, floor: float
                         ) -> tuple[list, dict[str, str]]:
    """Orchestra's event counters in the balances, each replaced by the machine counters that sum
    to it (``floor``: the events a sum of parts needs). ``order.queued`` is ``placed + returns +
    failed + leases``: four flows into the waiting orders, two of them from other stocks."""
    out, notes = [], {}
    machine = [c for c in counters if c.labels.get("machine")]
    for s, terms, r2, exact in found:
        for c, _ in list(terms):
            if c.name != EVENT_COUNTER:
                continue
            used = {k.key for k, _ in terms}
            evidence = _claimed_by_others(found, s) | {k.key for k in machine if machine_of(k) == machine_of(s)}
            parts = decompose(c, [k for k in machine if k.key not in used], masks[s.key], sizes=(1, 2, 3, 4), required=evidence, floor=floor)
            got = _replace(s, terms, c, parts, masks[s.key], fits) if parts else None
            if got:
                terms, r2, exact = got
                notes[c.key] = f"the same as {' + '.join(p.key for p in parts)} (counts the same events, which those count apart)"
        out.append((s, terms, r2, exact))
    return out, notes


def split_foreign_counters(found: list, counters: list[Series], masks: dict[str, list[int]], machine_of, fits, floor: float
                           ) -> tuple[list, dict[str, str]]:
    """Another machine's counters in a balance that no other stock claims, each replaced by the
    level's own machine's counters that sum to it: yelp's reviews are the customers served plus
    those who gave up, and the customers' waiting is the customers' to account for."""
    out, notes = [], {}
    machine = [c for c in counters if c.labels.get("machine")]
    for s, terms, r2, exact in found:
        own = [c for c in machine if machine_of(c) == machine_of(s)]
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


def unify_same_flows(found: list, masks: dict[str, list[int]], same_flow, machine_of, fits) -> tuple[list, dict[str, str]]:
    """Two machines' counters of the same events, one leaving a stock and the other entering
    another, become one counter in every balance: whichever leaves the balances fitting best, when
    every one still fits (``fits``). The flow then joins the stocks instead of leaving one and
    entering the other from outside. Two such counters with the same sign are left alone: one event
    moving each machine's own material (an order accepted leaves the board's accepting and the
    customers' waiting at once), which ``sd.ends`` draws as a co-flow."""
    found = list(found)
    notes: dict[str, str] = {}
    used = {c.key: c for _, terms, _, _ in found for c, _ in terms}
    signs = {c.key: {sg for _, terms, _, _ in found for k, sg in terms if k is c} for c in used.values()}
    for a, b in combinations(sorted(used), 2):
        ca, cb = used[a], used[b]
        if machine_of(ca) == machine_of(cb) or signs[a] & signs[b] or not same_flow(ca, cb):
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
            if ok and (best is None or total > best[0]):
                best = (total, trial, keep, drop)
        if best is not None:
            found = best[1]
            notes[best[3].key] = f"the same as {best[2].key} (counts the same events)"
    return found, notes
