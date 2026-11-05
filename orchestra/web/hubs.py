"""The hubs of the Machines page's event map, found once, here, so the page and the Supervisor read
one answer (``/api/machines``: ``hubs``, and ``relays`` only through a hub).

A machine that exchanges event types both ways with at least two others (it publishes a type each
of them listens for, and listens for a type each of them publishes) is a **hub**, and those are its
members; the widest first, and a member of a hub is no hub of its own. The types between a hub and
a member, and those the hub both publishes and listens for, are its protocol. A relay (a subject
handed to the hub by one machine and on by it to another) counts as work handed from the one to
the other only when the hub's hand-off is its protocol. The rule is machine-graph.js's
(``protocol``), which reads these hubs when the API serves them; no event type's name is known
here (AGENTS.md rule 1)."""

from __future__ import annotations


def _hears(pattern: str, type_: str) -> bool:
    return pattern == type_ or pattern == "*" or (pattern.endswith(".*") and type_.startswith(pattern[:-1]))


class Hubs:
    """``pub``: by machine, the types it publishes; ``sub``: the patterns it listens for."""

    def __init__(self, pub: dict[str, set[str]], sub: dict[str, set[str]]):
        self.pub, self.sub = pub, sub
        # only a machine that both publishes and listens can exchange both ways: a person a relay
        # announced, who listens for nothing, is never a hub's member (hundreds of them cost nothing)
        ids = sorted(m for m in set(pub) | set(sub) if pub.get(m) and sub.get(m))
        cands = [(h, {m for m in ids if m != h and self.sends(h, m) and self.sends(m, h)}) for h in ids]
        cands = sorted(((h, ms) for h, ms in cands if len(ms) >= 2), key=lambda c: (-len(c[1]), c[0]))
        self.hubs: dict[str, set[str]] = {}
        for h, members in cands:
            if not any(h in ms for ms in self.hubs.values()):
                self.hubs[h] = members

    def listens(self, m: str, type_: str) -> bool:
        return any(_hears(p, type_) for p in self.sub.get(m, ()))

    def sends(self, a: str, b: str) -> list[str]:
        """The types ``a`` publishes that ``b`` listens for."""
        return sorted(t for t in self.pub.get(a, ()) if self.listens(b, t))

    def protocol(self, a: str, type_: str, b: str) -> bool:
        """Whether ``type_`` from ``a`` to ``b`` is a hub's protocol: between a hub and its member,
        or a hub's own bookkeeping."""
        if a == b:
            return a in self.hubs and self.listens(a, type_)
        return (a in self.hubs and b in self.hubs[a]) or (b in self.hubs and a in self.hubs[b])

    def through(self, relays: list[dict]) -> list[dict]:
        """The relays that hand work from one machine to another through a hub."""
        return [r for r in relays if r["from"] != r["to"] and r["through"] in self.hubs
                and self.protocol(r["through"], r.get("through_via") or "", r["to"])]

    def record(self) -> list[dict]:
        return [{"hub": h, "members": sorted(ms)} for h, ms in self.hubs.items()]
