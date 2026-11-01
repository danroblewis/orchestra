"""A quiet window holds the model: a stock whose series did not move is not gone.

A stock that stops moving still holds its quantity. When a discovery's window is quiet for a
stock of the current version (its level did not change, or changed in too few steps to judge; for
a stock no series measures, every counter of its flows did not move or counted too few events),
the window has no evidence about it, for or against. Dropping it would save a poorer model as
"the structure changed" (the core demo, 2026-11-01: a quiet hour saved v4 with one stock of v3's
seven, and the next discovery drew DONE=34 as gone). So ``hold`` carries each such stock from the
current version into the discovery, with the current version's flows that reach it (whose other
end is outside or in the discovery), marked ``evidence["quiet"]``: the version they stand on and
since when they have been quiet. A stock whose series is no longer written, or moved and no
longer balances, is not quiet: discovery's answer stands, and the stock goes.

Nothing is fitted or deleted: the held parts are the current version's, numbers and all, and a
discovery whose structure is then the current version's saves no version (``rediscover``); the
record says ``quiet since <time>: the model of v<N> stands``."""

from __future__ import annotations

import copy
from datetime import UTC, datetime

from .model import Machine, Model
from .series import series_key

QUIET = ("a level that did not change in the window", "a level that changed in only ", "a counter that did not move in the window",
         "a counter of only ")      # the reasons discovery leaves a series out for too little motion (sd.discover)


def quiet(why: str | None) -> bool:
    """Whether a series was left out for too little motion, not for what it did."""
    return bool(why) and why.startswith(QUIET)


def _quiet_stock(s, flows: list, left_out: dict) -> bool:
    if s.series is not None:
        return quiet(left_out.get(series_key(s.series.name, s.series.labels)))
    counters = [f.counter for f in flows if s.id in (f.src, f.dst) and f.counter is not None]
    return bool(counters) and all(quiet(left_out.get(series_key(c.name, c.labels))) for c in counters)


def hold(model: Model, current: Model | None, version: int | None, previous: Model | None = None) -> Model:
    """The discovered ``model`` with the quiet stocks of ``current`` (saved as ``version``) it
    lacks carried in, each with the flows that reach it; recorded in ``model.discovery["quiet"]``.
    ``previous``: the last discovery, whose record says since when a stock already held was quiet."""
    if current is None or current.era != model.era:
        return model                   # another era's parts are the prior's to carry (sd.prior)
    left_out = model.discovery.get("left_out") or {}
    start = model.discovery.get("start")
    before = ((previous.discovery if previous else {}) or {}).get("quiet") or {}
    since_of = before.get("since_by_stock") or {}
    have = {s.id for s in model.stocks}
    held = [s for s in current.stocks if s.id not in have and not (s.evidence or {}).get("simulated")
            and _quiet_stock(s, current.flows, left_out)]
    if not held:
        return model
    since = {s.id: since_of.get(s.id, start) for s in held}
    for s in held:
        c = copy.deepcopy(s)
        c.evidence = {**c.evidence, "quiet": {"version": version, "since": since[s.id],
                                              "why": "its series did not move in the window: no evidence for or against it, so it stands"}}
        model.stocks.append(c)
        have.add(s.id)
    ids, flows = {s.id for s in held}, {f.id for f in model.flows}
    carried = []
    for f in current.flows:
        if f.id in flows or not ({f.src, f.dst} & ids) or not all(x is None or x in have for x in (f.src, f.dst)):
            continue
        c = copy.deepcopy(f)
        c.evidence = {**c.evidence, "quiet": {"version": version, "why": "a flow of a stock held through a quiet window"}}
        model.flows.append(c)
        carried.append(f.id)
    mine = {m.id: m for m in model.machines}
    for m in current.machines:
        theirs = [fid for fid in m.attributed if fid in carried]
        if not theirs:
            continue
        if m.id in mine:
            mine[m.id].attributed = list(dict.fromkeys([*mine[m.id].attributed, *theirs]))
        else:
            model.machines.append(Machine(m.id, m.name, m.kind, m.description, theirs, list(m.observed_by), m.bootstrap))
    first = min((t for t in since.values() if t is not None), default=None)
    model.discovery["quiet"] = {"version": version, "since": first, "since_by_stock": since,
                                "stocks": [s.id for s in held], "flows": carried}
    return model


def stands(model: Model) -> str | None:
    """What the discovery record says when the held model is the current version's."""
    q = model.discovery.get("quiet")
    if not q:
        return None
    if q.get("since") is None:
        return f"quiet: the model of v{q['version']} stands"
    at = datetime.fromtimestamp(q["since"], UTC).strftime("%Y-%m-%d %H:%M UTC")
    return f"quiet since {at}: the model of v{q['version']} stands"
