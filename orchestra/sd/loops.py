"""The model's feedback loops, as ids, for saying when they appear or disappear (``sd.compare``,
``sd.announce``).

A loop is a cycle of stocks, each influencing the next: stock X influences stock Y when a flow
into or out of Y has a rate that reads X (X among its equation's inputs, X not Y). A rate that
reads only its own source is no link (a drain proportional to what is there), and a measured
input is no stock. Cycles through the same stocks are one loop (the Dynamics page groups them
the same way, ``static/loops.js``); its id is ``loop:`` and the stocks' ids sorted, joined with
``+``. At most ``CAP`` cycles are followed, up to ``DEPTH`` stocks long."""

from __future__ import annotations

from .model import Model

CAP = 500
DEPTH = 12


def links(model: Model) -> dict[str, set[str]]:
    stocks = {s.id for s in model.stocks}
    out: dict[str, set[str]] = {s: set() for s in stocks}
    for f in model.flows:
        e = f.current()
        reads = [x for x in (e.inputs if e else []) if x in stocks]
        if e and not e.inputs and e.form in ("proportional", "linear") and f.src:
            reads = [f.src]
        for x in reads:
            for y in (f.src, f.dst):
                if y and y in stocks and y != x:
                    out[x].add(y)
    return out


def loops(model: Model) -> list[dict]:
    """Each loop: its id and its stocks (one cycle through them, from the first by id)."""
    adj = links(model)
    order = sorted(adj)
    found: dict[str, list[str]] = {}
    count = 0
    for i, start in enumerate(order):
        allowed = set(order[i:])                 # each cycle once: from its lowest stock
        stack = [(start, [start])]
        while stack and count < CAP:
            node, path = stack.pop()
            for nxt in sorted(adj[node]):
                if nxt == start and len(path) > 1:
                    count += 1
                    key = "loop:" + "+".join(sorted(path))
                    found.setdefault(key, list(path))
                elif nxt in allowed and nxt not in path and len(path) < DEPTH:
                    stack.append((nxt, [*path, nxt]))
    return [{"id": k, "stocks": v} for k, v in sorted(found.items())]
