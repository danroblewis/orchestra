"""Which stocks may drive a flow's rate (the linear form in ``sd.discover.fit_flow``): not one
whose balance counts the flow's own events, or counts them first.

A stock one of whose balance counters counts the flow's events is one lower, or one higher, just
before every such event by construction: an order is placed at the instant the taker who took it
is free again, so the free takers just before each placing are one fewer, and that reverse
causation beats any real driver on likelihood (the bakery's placed read −2.6 × the free takers
where the demand gauge was the driver). The same holds for a counter that counts a part of the
flow's events, or of which the flow counts a part, when its events come at or before the flow's
(``leads``): the stock moved first. One that counts them afterwards is an effect of the flow (a
record of a transition the flow's events caused, stamped a moment later), and its stock may well
be what drives the flow: what waits is taken. Such a stock stays a stock; it just may not explain
the flow, and the flow's evidence records which stocks were kept from it and why. The flow's own
ends are not kept from it: its source is what the proportional form reads, and the level at
either end is not moved by an event before the event.

``behind`` is the same lead-or-lag question asked of two counters of the same events (one stamped
a moment after the other), which ``sd.discover.same_flow`` uses."""

from __future__ import annotations

from .collinear import CANCEL_STEPS
from .series import Series

PART_SHARE = 0.5      # a counter is a part of another's events only when it counts at least this share of them
AIC_MARGIN = 2.0      # a form with another parameter, or reading another series, must beat the plain one by this much AIC
EVENTS_PER_PARAM = 10  # a form that reads another stock or an input needs this many events per parameter


def behind(lead: list[float], lag: list[float]) -> bool:
    """``lag`` counts the same events as ``lead``, stamped no more than a step later: its running
    total is always between ``lead``'s at the step before and at this step."""
    cl = cg = before = 0.0
    for x, y in zip(lead, lag):
        cl, cg = cl + x, cg + y
        if not before - 1e-9 <= cg <= cl + 1e-9:
            return False
        before = cl
    return True


def leads(a: Series, b: Series, steps: list[int]) -> bool:
    """``a``'s events come at or before ``b``'s. On a grid two counts of one moment land in the
    same step, and a lag shorter than a step puts some of the later counter's in the next: the
    counts of a step are matched with each other first, what is left over with the other
    counter's in the step after (the rest are events only one of them counts), and ``a`` leads
    when at least as many of its counts were matched forward as back. Equal, or always the same
    step, counts as leading: the stock was already one off when the event came."""
    da, db = a.deltas, b.deltas
    early = late = 0.0
    left_a = left_b = 0.0        # counts of the step before that the other counter had not matched
    prev = None
    for i in steps:
        if prev is not None and i != prev + 1:
            left_a = left_b = 0.0
        x, y = da[i], db[i]
        m = min(x, y); x -= m; y -= m               # the same step
        m = min(left_a, y); early += m; y -= m      # a counted it the step before b: a led
        m = min(left_b, x); late += m; x -= m       # b counted it the step before a: a lagged
        left_a, left_b, prev = x, y, i
    return early >= late


def part_of(a: Series, b: Series, steps: list[int]) -> bool:
    """``a`` counts a part of ``b``'s events: in all but ``CANCEL_STEPS`` of the steps ``a`` moved
    in, ``b`` moved by at least as much, and ``a`` counted at least ``PART_SHARE`` of ``b``'s
    events. On a grid a rarer counter is not told from one that merely never fires in a step the
    busy one is silent in; it also moves the level just before fewer of the events."""
    da, db = a.deltas, b.deltas
    ta, tb = sum(da[i] for i in steps), sum(db[i] for i in steps)
    if not ta or ta > tb or ta < PART_SHARE * tb:
        return False
    moved = [i for i in steps if da[i]]
    return sum(1 for i in moved if da[i] > db[i]) <= CANCEL_STEPS * len(moved)


def co_counting(counter: Series, ends: set[str], found: list, sid_of: dict[str, str],
                steps: list[int], same_flow) -> dict[str, str]:
    """The stocks, by id, whose balance counts this flow's events, each with why; the flow's own
    ``ends`` excepted (those of its co-flows too: one event, every stock it moves). ``found``:
    (level, terms, r2, exact) per stock; ``steps``: the grid steps the counters are compared on
    (those every series involved was live in)."""
    out: dict[str, str] = {}
    for s, terms, _, _ in found:
        sid = sid_of[s.key]
        if sid in ends:
            continue
        for k, _ in terms:
            if k is counter:
                why = "its balance has this flow's counter"
            elif same_flow(counter, k):
                why = f"its balance has {k.key}, which counts the same events as this flow"
            elif part_of(k, counter, steps) and leads(k, counter, steps):
                why = f"its balance has {k.key}, which counts a part of this flow's events and leads them"
            elif part_of(counter, k, steps) and leads(k, counter, steps):
                why = f"its balance has {k.key}, of whose events this flow counts a part, and which leads them"
            else:
                continue
            out[sid] = why
            break
    return out
