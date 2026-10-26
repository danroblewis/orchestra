"""Which stocks may drive a flow's rate (the linear form in ``sd.discover.fit_flow``): not one
whose balance counts the flow's own events.

A stock one of whose balance counters counts the flow's events (the same events, a part of them,
or the flow a part of its) is one lower, or one higher, just before every such event by
construction: an order is placed at the instant the taker who took it is free again, so the free
takers just before each placing are one fewer, and that reverse causation beats any real driver
on likelihood (the bakery's placed read −2.6 × the free takers where the demand gauge was the
driver). Such a stock stays a stock; it just may not explain the flow, and the flow's evidence
records which stocks were kept from it and why. The flow's own ends are not kept from it: its
source is what the proportional form reads, and the level at either end is not moved by an event
before the event."""

from __future__ import annotations

from .collinear import CANCEL_STEPS
from .series import Series

PART_SHARE = 0.5      # a counter is a part of another's events only when it counts at least this share of them


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


def co_counting(counter: Series, src: str | None, dst: str | None, found: list, sid_of: dict[str, str],
                steps: list[int], same_flow) -> dict[str, str]:
    """The stocks, by id, whose balance counts this flow's events, each with why; the flow's own
    ends excepted. ``found``: (level, terms, r2, exact) per stock; ``steps``: the grid steps the
    counters are compared on (those every series involved was live in)."""
    out: dict[str, str] = {}
    for s, terms, _, _ in found:
        sid = sid_of[s.key]
        if sid in (src, dst):
            continue
        for k, _ in terms:
            if k is counter:
                why = "its balance has this flow's counter"
            elif same_flow(counter, k):
                why = f"its balance has {k.key}, which counts the same events as this flow"
            elif part_of(k, counter, steps):
                why = f"its balance has {k.key}, which counts a part of this flow's events"
            elif part_of(counter, k, steps):
                why = f"its balance has {k.key}, of whose events this flow counts a part"
            else:
                continue
            out[sid] = why
            break
    return out
