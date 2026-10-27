"""Where each counter's flow goes: the stocks whose balances claim it.

A counter subtracted in one stock's balance and added in another's is a move between them; one
end only, and it comes from or goes to outside. When two stocks claim the same end, the one whose
balance the counter explains most keeps it (an ordinary stock before an accumulator), and the
other's claim is recorded in the flow's evidence rather than silently lost. When the stocks that
claim a counter belong to different machines, it is a **co-flow**: one event that moves two
materials (an order baked leaves the board's baking stock and frees one of the expo's bakers;
where each machine counted the event itself, ``sd.restate`` has made the two counters one).
That is recorded as one flow per machine with the same counter: the counter's own machine (or the
machine whose stocks it explains most) has the plain flow, the others ``<flow>@<machine>``, each
naming the other in its evidence. The Dynamics page draws flows as edges between stocks, so every
claim stays visible; one flow with four ends could not be drawn.

A counter that drains no stock and that several stocks each take as an inflow, explaining at least
``COPY_SHARE`` of each one's changes, is a **copy**: every event fills each of them (a topic's
published count fills every subscription's backlog; a fanout exchange fills each bound queue). It
is not a split, and not a contest between them: the stock it explains most has the plain flow,
the others ``<flow>><stock>``, each from outside, the copies naming the flow they copy
(``copy_of``) and the flow its copies (``copies``). A counter that also drains a stock is a move
with co-flows, as before: a copy out of a stock would drain it once per destination."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from .balance import explained_share
from .live import balance_steps

COPY_SHARE = 0.25       # a counter fills a stock as a copy when it explains at least this share of the stock's changes


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
        steps = balance_steps(s, [c for c, _ in terms])      # the steps the balance was found on
        for c, sign in terms:
            out[c.key].append(Claim(sid_of[s.key], sign, explained_share(s, terms, c, steps), machine_of(s), acc))
    return out


def _end(cs: list[Claim]) -> tuple[str | None, list[dict]]:
    """The stock that keeps this end, and the claims it beat."""
    if not cs:
        return None, []
    cs = sorted(cs, key=lambda c: (c.accumulator, -c.share))
    return cs[0].stock, [{"stock": c.stock, "share": round(c.share, 4)} for c in cs[1:]]


def copies(c, cs: list[Claim], fid: str) -> list[Move] | None:
    """The flows of a counter that fills several stocks at once and drains none (one per stock it
    fills, the stock it explains most first), or None when it is not a copy."""
    fills = sorted((cl for cl in cs if cl.sign > 0 and not cl.accumulator and cl.share >= COPY_SHARE), key=lambda cl: -cl.share)
    if len(fills) < 2 or any(cl.sign < 0 for cl in cs):
        return None
    made = [Move(fid if i == 0 else f"{fid}>{cl.stock}", c, None, cl.stock,
                 {"copy_of": fid, "share": round(cl.share, 4),
                  "note": f"every event also fills {cl.stock}: the same events as {fid}, a copy, not a split"} if i else {})
            for i, cl in enumerate(fills)]
    made[0].evidence["copies"] = [m.id for m in made[1:]]
    made[0].evidence["share"] = round(fills[0].share, 4)
    if others := [cl for cl in cs if cl not in fills]:
        made[0].evidence["conflicts"] = [{"end": "dst", "kept": fills[0].stock,
                                          "others": [{"stock": cl.stock, "share": round(cl.share, 4)} for cl in others]}]
    return made


def moves(counters: list, by_counter: dict[str, list[Claim]], fid_of: dict[str, str], machine_of) -> list[Move]:
    """The flows the claims make, in the counters' order: one per counter and claiming machine,
    or one per stock a copy fills."""
    out: list[Move] = []
    for c in counters:
        cs = by_counter.get(c.key)
        if not cs:
            continue
        if (made := copies(c, cs, fid_of[c.key])) is not None:
            out += made
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
