"""The people relayed from one system, drawn as one group (SPEC §10, "Many people"; the owner,
2026-11-04: "way too many people names sometimes, and it's breaking various things").

A bridge relays each act on a system it reads as the person who did it,
``person.<system>.<account>`` (``orchestra.people``), and announces each one: at work, hundreds
of machines from one system. ``/api/machines?people=grouped`` gives, in place of the person rows
of each system that has at least ``GROUP_MIN`` of them, one **group** row, ``Jira people (600)``:
its id ``people/<system>`` (a ``/`` no machine's id has, since a source's ``/`` starts its
instance), or ``people/<system>/<group>`` for the people whose announcement names a group (or a
team), each such group apart. Every hand-off, relay, edge, hub, counted edge, declared edge and
listener that names one of its people names the group instead, summed (``within``: the hand-offs
between two of its people, which no line draws). The full answer (the default) is unchanged.

Display only. Each person is still a machine, observed (AGENTS.md rule 2): the bus, discovery, the
flows' hypotheses and the declared layer never read a group. ``expand`` keeps a group's people one
by one (the map's expanded group), each marked ``in_people``; every group, expanded or not, is in
``people_groups``. ``members`` lists a group's people for the card's list.

Kept one by one: an owner-mapped ``person.<key>`` (``relayed_from`` is None), a person the owner
declared (``intent``) or hid (``hidden``: in "hidden by you"), and a machine known by counted
traffic. A group whose people all only announced themselves is ``announced_only``, and folds as one
machine does."""

from __future__ import annotations

from collections import Counter

from ..people import GROUP_MIN, relayed_from

PREFIX = "people/"
SAMPLE = 3            # the names a group's summary shows


def _title(system: str, group: str | None) -> str:
    return f"{system[:1].upper()}{system[1:]} people" + (f" · {group}" if group else "")


def key_of(m: dict) -> str | None:
    """The group a machine row is drawn in, or None for one kept one by one."""
    system = relayed_from(m.get("id"))
    if system is None or m.get("bootstrap") or m.get("intent") or m.get("hidden") or m.get("counted"):
        return None
    return PREFIX + system + (f"/{m['group']}" if m.get("group") else "")


def groups_of(machines: list[dict]) -> dict[str, list[dict]]:
    """Each group's people, the groups with at least ``GROUP_MIN`` of them."""
    by: dict[str, list[dict]] = {}
    for m in machines:
        if (k := key_of(m)) is not None:
            by.setdefault(k, []).append(m)
    return {k: ms for k, ms in sorted(by.items()) if len(ms) >= GROUP_MIN}


def _row(key: str, ms: list[dict]) -> dict:
    """One group's row, in the shape of a machine's (what a page reads of one), summed."""
    system, _, group = key[len(PREFIX):].partition("/")
    pubs: dict[str, dict] = {}
    for m in ms:
        for p in m.get("publishes") or []:
            q = pubs.setdefault(p["type"], {"type": p["type"], "count": 0, "day": 0, "n_10m": 0, "window_s": 0, "per_min_10m": 0.0})
            q["count"] += p.get("count") or 0
            q["day"] += p.get("day") or 0
            q["n_10m"] += p.get("n_10m") or 0
            q["window_s"] = max(q["window_s"], p.get("window_s") or 0)
            q["per_min_10m"] = round(q["per_min_10m"] + (p.get("per_min_10m") or 0), 2)
    flows: dict[str, dict] = {}
    for m in ms:
        for f in m.get("flows") or []:
            have = flows.get(f["flow"])
            if have is None or (f.get("confidence") or 0) > (have.get("confidence") or 0):
                flows[f["flow"]] = {**f, "people": (have or {}).get("people", 0)}
            flows[f["flow"]]["people"] += 1
    by_activity = sorted(ms, key=lambda m: (-(m.get("last_seen") or 0), m["id"]))
    def common(f):                      # the one value its people said, or None
        vs = {m.get(f) for m in ms}
        return vs.pop() if len(vs) == 1 else None
    title = _title(system, group or None)
    seen = [m["first_seen"] for m in ms if m.get("first_seen") is not None]
    last = [m["last_seen"] for m in ms if m.get("last_seen") is not None]
    at = [m["announced_at"] for m in ms if m.get("announced_at") is not None]
    return {"id": key, "name": f"{title} ({len(ms)})", "bootstrap": False, "mode": common("mode"), "kind": "person",
            "kinds": dict(Counter(m.get("kind") for m in ms if m.get("kind"))), "package": common("package"), "group": group or None,
            "about": {}, "publishes": sorted(pubs.values(), key=lambda p: (-p["count"], p["type"])),
            "subscribes": sorted({t for m in ms for t in m.get("subscribes") or []}),
            "flows": sorted(flows.values(), key=lambda f: (-(f.get("confidence") or 0), f["flow"])),
            "logs": [], "processes": [], "instances": [],
            "first_seen": min(seen, default=None), "last_seen": max(last, default=None), "active": any(m.get("active") for m in ms),
            "cadence_s": None, "announced": sum(m.get("announced") or 0 for m in ms),
            "announced_only": all(m.get("announced_only") for m in ms), "announced_at": max(at, default=None),
            "intent": None, "comparison": None, "hidden": None, "measured": None,
            "people_group": {"key": key, "system": system, "group": group or None, "title": title, "size": len(ms),
                             "active": sum(1 for m in ms if m.get("active")), "announced_only": sum(1 for m in ms if m.get("announced_only")),
                             "names": [m.get("name") or m["id"] for m in by_activity[:SAMPLE]], "ids": [m["id"] for m in ms],
                             "within": 0, "expanded": False}}


def _sum(rows: list[dict], key, fields=("count", "day")) -> list[dict]:
    """Rows that now name the same ends merged: their counts summed, the first's other fields kept."""
    out: dict = {}
    for r in rows:
        k = key(r)
        if k in out:
            for f in fields:
                if f in r:
                    out[k][f] = (out[k].get(f) or 0) + (r[f] or 0)
        else:
            out[k] = dict(r)
    return sorted(out.values(), key=lambda r: -(r.get("count") or 0)) if "count" in fields else list(out.values())


def grouped(out: dict, expand: set[str] | frozenset = frozenset()) -> dict[str, str]:
    """``out`` (an ``/api/machines`` answer) in its grouped form, in place; returns each grouped
    person's id -> its group's id (an expanded group's people are not in it)."""
    groups = groups_of(out.get("machines") or [])
    rows = {k: _row(k, ms) for k, ms in groups.items()}
    to = {m["id"]: k for k, ms in groups.items() if k not in expand for m in ms}
    for k in expand:
        if k in rows:
            rows[k]["people_group"]["expanded"] = True
    member_of = {m["id"]: k for k, ms in groups.items() for m in ms}
    machines = []
    placed = set()
    for m in out.get("machines") or []:
        k = to.get(m["id"])
        if k is None:
            machines.append({**m, "in_people": member_of[m["id"]]} if m["id"] in member_of else m)
        elif k not in placed:
            placed.add(k)
            machines.append(rows[k])
    out["machines"] = machines
    out["people_groups"] = [rows[k] for k in sorted(rows)]
    if not to:
        return to
    g = lambda x: to.get(x, x)
    for h in out.get("handoffs") or []:
        if h["from"] in to and to.get(h["from"]) == to.get(h["to"]):
            rows[to[h["from"]]]["people_group"]["within"] += h.get("count") or 0
    out["handoffs"] = _sum([{**h, "from": g(h["from"]), "to": g(h["to"])} for h in out.get("handoffs") or []
                            if not (h["from"] in to and to.get(h["from"]) == to.get(h["to"]))],
                           lambda h: (h["from"], h.get("via"), h["to"]))
    out["relays"] = _sum([{**r, "from": g(r["from"]), "through": g(r["through"]), "to": g(r["to"])} for r in out.get("relays") or []
                          if g(r["from"]) != g(r["to"])],
                         lambda r: (r["from"], r.get("via"), r["through"], r.get("through_via"), r["to"]))
    out["edges"] = _sum([{**e, "from": g(e["from"]), "to": g(e["to"])} for e in out.get("edges") or []],
                        lambda e: (e["from"], e["to"], e.get("kind")))
    if isinstance(out.get("hubs"), list):
        out["hubs"] = [{**h, "hub": g(h["hub"]), "members": sorted({g(x) for x in h.get("members") or []})} for h in out["hubs"]]
    for name in ("counted", "intended_edges"):
        if isinstance(out.get(name), list):
            out[name] = [{**e, **{f: g(e[f]) for f in ("from", "to", "machine") if isinstance(e.get(f), str)}} for e in out[name]]
    for u in out.get("unanswered_types") or []:
        u["listeners"] = sorted({g(x) for x in u.get("listeners") or []})
    return to


def announced_fields(fields: dict[str, dict[str, list[str]]], to: dict[str, str]) -> dict[str, dict[str, list[str]]]:
    """The announced ``group`` and ``package`` of each machine (``MachineIndex.announced_fields``),
    with each group's the union of its people's: the boxes on the map take the group as a machine."""
    out = {m: f for m, f in fields.items() if m not in to}
    for m, k in to.items():
        mine = out.setdefault(k, {})
        for f, vs in (fields.get(m) or {}).items():
            mine[f] = sorted(set(mine.get(f) or []) | set(vs))
    return out


def members(machines: list[dict], key: str) -> dict | None:
    """A group's people, for the card's list: each one's id, name, whether it is active, when it was
    last seen and how many events it published; the busiest first. None when there is no such group."""
    ms = groups_of(machines).get(key)
    if ms is None:
        return None
    rows = [{"id": m["id"], "name": m.get("name"), "active": bool(m.get("active")), "last_seen": m.get("last_seen"),
             "first_seen": m.get("first_seen"), "events": sum(p.get("count") or 0 for p in m.get("publishes") or []),
             "day": sum(p.get("day") or 0 for p in m.get("publishes") or []), "announced_only": bool(m.get("announced_only")),
             "flows": len(m.get("flows") or [])} for m in ms]
    rows.sort(key=lambda r: (-r["events"], (r["name"] or r["id"]).lower()))
    return {"key": key, "title": _row(key, ms)["people_group"]["title"], "size": len(rows), "members": rows}
