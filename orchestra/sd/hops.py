"""Two hops of one move, counted apart, through a state the grid never sees held.

A machine that moves an item through a state it leaves at once counts both hops: approved, then
done; rejected, then back in progress. Within a step the two counters count the same events, so
discovery keeps one of them (counters of one machine that move together are one) and the flow
runs past the state. When a measured level rises at the first hop's events and falls at the
second's (``sd.between``), that level is the state: the counter kept stays the hop it counts,
the copy comes back as the other, and the flow runs through the state (``sd.passing.Passage``)."""

from __future__ import annotations

from .balance import fit_of
from .between import state_level
from .live import balance_steps
from .passing import Passage, out_of_step
from .series import EVENT_COUNTER, Series


def split_hops(found: list, counters: list[Series], copies: dict[str, list[Series]], levels: list[Series], *,
               start: float, end: float, step: float, first_stamped, writer_of) -> tuple[list, list[Passage], list[Series]]:
    """The balances with each two-hop move that a measured state lies on split in two, the
    passages through those states, and the copies that came back as counters of their own.
    ``copies``: per counter key, the same machine's counters of the same events it stands for."""
    found, levels = list(found), list(levels)
    made: list[Passage] = []
    revived: list[Series] = []
    for k in counters:
        held = [(i, sign) for i, (_, terms, _, _) in enumerate(found) for c, sign in terms if c is k]
        if sorted(sign for _, sign in held) != [-1, 1]:
            continue                    # a hop is a move between two stocks, one draining and one filling
        for d in copies.get(k.key, []):
            if d.name == EVENT_COUNTER or k.name == EVENT_COUNTER or writer_of(d) != writer_of(k):
                continue
            first, second = (k, d) if first_stamped(k, d) else (d, k)
            state = state_level(levels, [first], [second], start=start, end=end, step=step, writer_of=writer_of)
            if not state:
                continue
            level, up, down = state
            levels.remove(level)
            for i, sign in held:        # the stock drained now drains by the first hop, the one filled fills by the second
                s, terms, _, _ = found[i]
                hop = first if sign < 0 else second
                terms = [(hop if c is k else c, sg) for c, sg in terms]
                found[i] = (s, terms, *fit_of(s, terms, balance_steps(s, [c for c, _ in terms])))
            made.append(Passage(level, [first], [second], True, *out_of_step(first.deltas, second.deltas), up, down))
            revived.append(d)
            break
    return found, made, revived
