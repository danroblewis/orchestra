"""States an item leaves within a step: a chain the grid splits through outside, joined again.

An order picked up from the shelf is accepted or rejected by the customer at once; a ticket
rejected by its reviewer is back in progress a second later. On a grid of steps the state in
between is empty at almost every step, so it is no stock (it changed in too few steps), and its
inflow ends at outside while its outflows begin there: the shelf drains to nowhere and the
rejected orders come back from nowhere. The rework loop is open.

A **passage** joins them. Its counters are ins and outs: at least one in drains a stock to
outside, at least one out fills another stock from outside, each claimed by that one stock
alone (an event that moves two machines' stocks says nothing of which material passes), and any
other counter in it (one no balance used, or another such drain or fill) is free to join if
the drain's or the fill's machine wrote it; a counter no machine is known to write (another
store's series without a machine label) never joins, since nothing then ties it to the passage
but its total, and among dozens of busy counters some always add up. No in and out but the drain and the fill count the
same events (a pair that cancels would let any two flows pass), and Orchestra's event counters,
stand-ins for the machines' own, take no part. They count the same items:
their totals agree, and the outs' running total is never ahead of the ins' nor more than a step
behind them (each item left within a step), in all but ``CANCEL_STEPS`` of the steps any of
them moved (and in none, when a counter that counted fewer than ``MIN_EVENTS`` completes it).
The fewest counters win, then the most of the first in's machine, then the fewest
steps out of step.

The drain must have counted ``MIN_EVENTS``; the fill is judged with the rest of the passage. A
rare fill (the few orders a customer sends back) is taken when the passage closes exactly and
something more than the fill vouches for it: a free counter of the fill's machine that counted
``MIN_EVENTS`` is among the outs (the orders accepted, the other way out of the same state), or
a measured level's raw points rise at the ins' events and fall at the outs'. Otherwise a
passage would come and go with the one event that takes the fill over the floor at the edge of
a window.

The state between is the measured level whose raw points rise at the ins' events and fall at
the outs' (``sd.between``): the grid misses it, its raw points do not. With no such level (none
is written, or it never reads above zero), the state is a stock measured by no series, with the
level the counters imply, drawn as hidden: an item spends almost no time in it. Each passage is
taken in turn, so a fill a passage makes (a counter no balance used, now the state's inflow) can
close the next one."""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import accumulate, combinations

from .balance import MIN_EVENTS
from .between import SAME_TOTAL, state_level
from .collinear import CANCEL_STEPS
from .parsimony import same_events
from .series import EVENT_COUNTER, Series

MAX_COUNTERS = 4      # a passage is at most this many counters


@dataclass
class Passage:
    level: Series                 # the measured level, or one the counters imply
    ins: list[Series]
    outs: list[Series]
    measured: bool
    out_of_step: int              # steps in which the outs ran ahead of the ins, or more than a step behind
    moved: int                    # steps in which any of them moved
    rises: list[int] = field(default_factory=list)   # a measured level's rises: [at an in's event, all]
    falls: list[int] = field(default_factory=list)   # ... and its falls: [at an out's event, all]

    @property
    def terms(self) -> list[tuple[Series, int]]:
        return [(c, 1) for c in self.ins] + [(c, -1) for c in self.outs]

    def evidence(self) -> dict:
        """What the stock records of how it was found."""
        how = ("its level, measured, rose at the ins' events and fell at the outs'" if self.measured else
               "no level measures it: the level is what the counters imply, and an item spends almost no time in it")
        return {"passing": {"ins": [c.key for c in self.ins], "outs": [c.key for c in self.outs],
                            "out_of_step_steps": self.out_of_step, "moved_steps": self.moved,
                            **({"rises_at_ins": self.rises, "falls_at_outs": self.falls} if self.measured else {}),
                            "note": f"a state each item leaves within a step, so the grid sees it empty: {how}"},
                **({} if self.measured else {"hidden": True})}


def _claims(found: list) -> dict[str, set[tuple[str, int]]]:
    """Per counter key, the stocks whose balances hold it, each with its sign."""
    out: dict[str, set[tuple[str, int]]] = {}
    for s, terms, _, _ in found:
        for c, sign in terms:
            out.setdefault(c.key, set()).add((s.key, sign))
    return out


def _summed(cs: list[Series]) -> list[float]:
    return [sum(xs) for xs in zip(*(c.deltas for c in cs))]


def out_of_step(ins: list[float], outs: list[float]) -> tuple[int, int]:
    """Steps in which the outs' running total was ahead of the ins' or more than a step behind,
    and steps in which either moved (``drivers.behind``, counted rather than all or nothing)."""
    cin = cout = before = 0.0
    bad = moved = 0
    for x, y in zip(ins, outs):
        cin, cout = cin + x, cout + y
        moved += 1 if (x or y) else 0
        bad += 0 if before - 1e-9 <= cout <= cin + 1e-9 else 1
        before = cin
    return bad, moved


def _vouched(p: Series, outs: list[Series], total: dict[str, float], claims: dict, floor: float, writer_of) -> bool:
    """Whether a free counter of the fill ``p``'s machine with ``floor`` events is among the outs."""
    return any(c is not p and c.key not in claims and total[c.key] >= floor and writer_of(c) == writer_of(p) for c in outs)


def _best(o: Series, fills: list[Series], pool: list[tuple[Series, int]], total: dict[str, float], claims: dict, floor: float,
          writer_of, seen, apart=lambda a, b: False) -> tuple | None:
    """The best passage that starts with the drain ``o``: one fill from ``fills``, and up to
    ``MAX_COUNTERS`` counters in all with what ``pool`` offers (each with its role, +1 in, −1 out).
    No stock is both drained by an in and filled by an out: an item that leaves a stock and is
    back within a step went nowhere the model needs (a taker busy for a moment is a free taker
    less, which its own balance already says). A fill under ``floor`` needs the passage exact and
    vouched for (``_vouched``, or ``seen(ins, outs)``: a measured level is the state between).
    Counters ``apart`` (each another measured level's turnover: pods stopped in one region and
    started in another) are never one passage's."""
    stocks = lambda cs: {k for c in cs for k, _ in claims.get(c.key, ())}
    best = None
    for size in range(MAX_COUNTERS - 1):
        for p in fills:
            if p is o or apart(o, p):
                continue
            for extra in combinations([(c, r) for c, r in pool if c is not o and c is not p], size):
                if len({c.key for c, _ in extra}) < size or any(writer_of(c) is None or writer_of(c) not in (writer_of(o), writer_of(p))
                                                                 for c, _ in extra) \
                        or any(apart(c, x) for c, _ in extra for x in (o, p)):
                    continue
                ins = [o, *(c for c, r in extra if r > 0)]
                outs = [p, *(c for c, r in extra if r < 0)]
                ti, to = sum(total[c.key] for c in ins), sum(total[c.key] for c in outs)
                if abs(ti - to) > max(1.0, SAME_TOTAL * max(ti, to)) or stocks(ins) & stocks(outs):
                    continue
                bad, moved = out_of_step(_summed(ins), _summed(outs))
                if not moved or bad > CANCEL_STEPS * moved or (bad and any(total[c.key] < floor for c in [p, *(c for c, _ in extra)])):
                    continue
                if any(same_events(a.deltas, b.deltas) for a in ins for b in outs if (a, b) != (o, p)):
                    continue
                if total[p.key] < floor and not (_vouched(p, outs, total, claims, floor, writer_of) or seen(ins, outs)):
                    continue
                every = ins + outs
                rank = (sum(1 for c in every if writer_of(c) != writer_of(o)), bad, sorted(c.key for c in every))
                if best is None or rank < best[0]:
                    best = (rank, ins, outs, bad, moved)
        if best is not None:
            return best
    return None


def passages(found: list, counters: list[Series], levels: list[Series], *, start: float, end: float, step: float,
             writer_of, copies: dict[str, list[Series]] | None = None, floor: float = MIN_EVENTS,
             apart=lambda a, b: False) -> list[Passage]:
    """Every passage, in turn (``found``: the balances, as (level, terms, r², exact); ``levels``:
    the measured levels that are no stock, any of which may be the state between). The drain it
    starts from must have counted ``floor`` events, as a balance's counters must: a few events
    coincide by chance. A rarer counter may only complete a passage, exactly, and a rarer fill
    must be vouched for besides (``_best``). ``copies``: per counter key, the counters of the same
    events it stands for, whose instants a measured state's rises and falls may match as well."""
    found, levels, made, copies = list(found), list(levels), [], copies or {}
    total = {c.key: sum(c.deltas) for c in counters}
    also = lambda cs: [*cs, *(d for c in cs for d in copies.get(c.key, ()))]     # the same events, counted again
    where = {"start": start, "end": end, "step": step, "writer_of": writer_of}
    seen = lambda ins, outs: state_level(levels, also(ins), also(outs), **where) is not None
    while True:
        claims = _claims(found)
        alone = {k: next(iter(v))[1] for k, v in claims.items() if len(v) == 1}       # claimed by one stock, with its sign
        own = [c for c in counters if c.name != EVENT_COUNTER]
        drains = [c for c in own if alone.get(c.key) == -1]
        fills = [c for c in own if alone.get(c.key) == 1 and total[c.key] > 0]
        free = [c for c in own if c.key not in claims and total[c.key] > 0]
        pool = [(c, 1) for c in drains + free] + [(c, -1) for c in fills + free]
        got = None
        for o in sorted((c for c in drains if total[c.key] >= floor), key=lambda c: (-total[c.key], c.key)):
            got = _best(o, fills, pool, total, claims, floor, writer_of, seen, apart)
            if got:
                break
        if got is None:
            return made
        _, ins, outs, bad, moved = got
        state = state_level(levels, also(ins), also(outs), **where)
        if state:
            level, up, down = state
            levels.remove(level)
            p = Passage(level, ins, outs, True, bad, moved, up, down)
        else:
            implied = [max(0.0, v) for v in accumulate([0.0, *(a - b for a, b in zip(_summed(ins), _summed(outs)))])]
            points = [(start + i * step, v) for i, v in enumerate(implied)]
            p = Passage(Series(f"after_{ins[0].name}", dict(ins[0].labels), points, implied, False), ins, outs, False, bad, moved)
        made.append(p)
        found.append((p.level, p.terms, 1.0, 1.0))
