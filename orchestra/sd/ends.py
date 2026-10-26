"""Where each counter's flow goes: the stocks whose balances claim it.

A counter subtracted in one stock's balance and added in another's is a move between them; one
end only, and it comes from or goes to outside. When two stocks claim the same end, the one whose
balance the counter explains most keeps it (an ordinary stock before an accumulator), and the
other's claim is recorded in the flow's evidence rather than silently lost. When the stocks that
claim a counter belong to different machines, it is a **co-flow**: one event that moves two
materials (an order baked leaves the board's baking stock and frees one of the expo's bakers).
That is recorded as one flow per machine with the same counter: the counter's own machine (or the
machine whose stocks it explains most) has the plain flow, the others ``<flow>@<machine>``, each
naming the other in its evidence. The Dynamics page draws flows as edges between stocks, so every
claim stays visible; one flow with four ends could not be drawn."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from .balance import explained_share


@dataclass
class Claim:
    stock: str          # stock id
    sign: int           # +1: the counter adds to the stock; −1: it drains it
    share: float        # how much of the stock's variance the counter explains (balance.explained_share)
    machine: str | None
    accumulator: bool


@dataclass
class Move:
    id: str
    counter: object     # the counter's Series
    src: str | None
    dst: str | None
    evidence: dict = field(default_factory=dict)


def claims(found: list, sid_of: dict, machine_of) -> dict[str, list[Claim]]:
    """Per counter key, every stock's claim on it (``found``: (level, terms, r2, exact))."""
    out: dict[str, list[Claim]] = defaultdict(list)
    for s, terms, _, _ in found:
        acc = all(sign > 0 for _, sign in terms)
        for c, sign in terms:
            out[c.key].append(Claim(sid_of[s.key], sign, explained_share(s, terms, c), machine_of(s), acc))
    return out


def _end(cs: list[Claim]) -> tuple[str | None, list[dict]]:
    """The stock that keeps this end, and the claims it beat."""
    if not cs:
        return None, []
    cs = sorted(cs, key=lambda c: (c.accumulator, -c.share))
    return cs[0].stock, [{"stock": c.stock, "share": round(c.share, 4)} for c in cs[1:]]


def moves(counters: list, by_counter: dict[str, list[Claim]], fid_of: dict[str, str], machine_of) -> list[Move]:
    """The flows the claims make, in the counters' order: one per counter and claiming machine."""
    out: list[Move] = []
    for c in counters:
        cs = by_counter.get(c.key)
        if not cs:
            continue
        groups: dict[str | None, list[Claim]] = defaultdict(list)
        for cl in cs:
            groups[cl.machine].append(cl)
        own = machine_of(c)
        main = own if own in groups else max(groups, key=lambda m: sum(cl.share for cl in groups[m]))
        fid = fid_of[c.key]
        made = []
        for machine in [main] + sorted((m for m in groups if m != main), key=str):
            src, lost_src = _end([cl for cl in groups[machine] if cl.sign < 0])
            dst, lost_dst = _end([cl for cl in groups[machine] if cl.sign > 0])
            ev: dict = {}
            conflicts = [{"end": "src", "kept": src, "others": lost_src}] if lost_src else []
            conflicts += [{"end": "dst", "kept": dst, "others": lost_dst}] if lost_dst else []
            if conflicts:
                ev["conflicts"] = conflicts
            if machine != main:
                ev["co_flow_of"] = fid
                ev["note"] = (f"the same events as {fid}, which also move {machine or 'another machine'}'s stock: "
                              "one event, two materials")
            made.append(Move(fid if machine == main else f"{fid}@{machine or 'other'}", c, src, dst, ev))
        if len(made) > 1:
            made[0].evidence["co_flows"] = [m.id for m in made[1:]]
        out += made
    return out
