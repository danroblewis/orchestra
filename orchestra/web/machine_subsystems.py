"""The Machines page's subsystems (docs/proposals/subsystems.md B9, B10, B15): ``/api/machines``'s
``subsystems``, the partitions of the one map's machines, event types and hand-offs, display only
and stored nowhere. Computed from what the page already has; nothing per domain, no label's name
known (AGENTS.md rule 1).

- **The model's partitions carried to machines** (``sd.subsystems``, and the declared subsystems
  beside them, ``sd.intended.subsystems``): a machine is in the group its flow hypotheses lie in
  (``sd.attribute``'s evidence, read through the model; never a ``machine`` label on a series),
  spans several, or is unassigned. A declared machine's ``tags`` naming a declared subsystem (its id
  or its name) place it in that subsystem's box.
- **One partition per announced field that groups machines** (``group``, ``package``: SPEC §2),
  named by the field: a machine is in the group its instances announced; one whose instances
  announced two is in two groups, and so outside every box.
- **An event type** is inside a box when every machine that publishes or listens for it is in that
  box; between boxes (``between``, with the groups it touches) when they are all in boxes but not
  one; outside every box (``unassigned.events``) when a machine on it is in none.
- **A hand-off** from a machine in one box to a machine in another crosses: each pair of groups
  lists its hand-offs, ``count`` the pairs of machines that handed work across, ``subjects`` how
  many subjects they handed. Inside one box it is ``joined``; one touching a machine in no box is
  neither. A machine handing to itself is no hand-off between anything.
- A machine in two groups (``spanning``) is drawn outside every box (the owner, 2026-11-02)."""

from __future__ import annotations

FIELDS = ("group", "package")


def _hears(pattern: str, type_: str) -> bool:
    return pattern == type_ or pattern == "*" or (pattern.endswith(".*") and type_.startswith(pattern[:-1]))


def on_types(out: dict) -> dict[str, set[str]]:
    """event type -> the machines that publish it or listen for it (observed, announced or declared)."""
    on: dict[str, set[str]] = {t: set() for t in out.get("types") or []}
    pubs = {m["id"]: {p["type"] for p in m.get("publishes") or []} for m in out.get("machines") or []}
    subs = {m["id"]: set(m.get("subscribes") or []) for m in out.get("machines") or []}
    for e in out.get("intended_edges") or []:
        if e.get("gone"):
            continue
        if e.get("kind") == "publishes":
            pubs.setdefault(e["from"], set()).add(e["to"])
            on.setdefault(e["to"], set())
        else:
            subs.setdefault(e["to"], set()).add(e["from"])
    for t in list(on):
        on[t] = {m for m, ts in pubs.items() if t in ts} | {m for m, ps in subs.items() if any(_hears(p, t) for p in ps)}
    return on


def carry(meta: dict, values: list[str], where: dict[str, str], span: dict[str, list[str]], out: dict,
          on: dict[str, set[str]], extra: dict[str, dict] | None = None) -> dict:
    """A partition of the map: ``where`` machine -> its group, ``span`` machine -> its groups;
    ``extra``: what each group carries besides (a declared name, ghosts)."""
    ids = [m["id"] for m in out.get("machines") or []]
    groups = {v: {"value": v, "machines": [], "events": [], **((extra or {}).get(v) or {})} for v in values}
    unassigned = {"machines": [], "events": []}
    for mid in ids:
        if mid in where:
            groups[where[mid]]["machines"].append(mid)
        elif mid not in span:
            unassigned["machines"].append(mid)
    present = set(ids)
    for g in groups.values():               # gathered by name and not on the map: a ghost in its box
        missing = [mid for mid in (g.get("members") or {}).get("machines") or [] if mid not in present]
        if missing:
            g["ghosts"] = {**(g.get("ghosts") or {}), "machines": missing}
    between = []
    for t in sorted(on):
        vs = {where.get(mid) for mid in on[t]}
        if not on[t] or None in vs:
            unassigned["events"].append(t)
        elif len(vs) == 1:
            groups[vs.pop()]["events"].append(t)
        else:
            between.append({"type": t, "groups": sorted(vs)})
    crossing: dict[tuple, dict] = {}
    inside: set[tuple] = set()
    for h in out.get("handoffs") or []:
        a, b = where.get(h["from"]), where.get(h["to"])
        if h["from"] == h["to"] or a is None or b is None:
            continue
        if a == b:
            inside.add((h["from"], h["to"]))
            continue
        pair = tuple(sorted((a, b)))
        c = crossing.setdefault(pair, {"between": list(pair), "handoffs": [], "count": 0, "subjects": 0, "_pairs": set()})
        c["handoffs"].append({k: h.get(k) for k in ("from", "via", "to", "count")})
        c["_pairs"].add((h["from"], h["to"]))
        c["subjects"] += h.get("count") or 0
    cross = []
    for c in crossing.values():
        c["count"] = len(c.pop("_pairs"))
        cross.append(c)
    cross.sort(key=lambda c: (-c["count"], c["between"]))
    return {**meta, "groups": list(groups.values()), "unassigned": unassigned, "between": between, "crossing": cross,
            "spanning": [{"machine": m, "groups": gs} for m, gs in sorted(span.items())],
            "joined": len(inside), "crossed": sum(c["count"] for c in cross), "crossed_simulated": 0}


def _tags(out: dict) -> dict[str, list[str]]:
    """A declared machine's tags (its envelope's), by id."""
    return {m["id"]: list((m.get("intent") or {}).get("tags") or []) for m in out.get("machines") or [] if m.get("intent")}


def from_model(p: dict, out: dict, on: dict, tags: dict[str, list[str]]) -> dict:
    """A model partition carried to the map's machines by their hypotheses (B9), a declared
    machine's tags placing it in a declared subsystem's box."""
    values = [g["value"] for g in p["groups"]]
    where = {mid: g["value"] for g in p["groups"] for mid in g.get("machines") or []}
    span = {s["machine"]: list(s["groups"]) for s in p.get("spanning") or []}
    names = {}
    for g in p["groups"]:
        for n in (g.get("declared"), g.get("name")):
            if n:
                names[n] = g["value"]
    for mid, ts in tags.items():
        vs = sorted({names[t] for t in ts if t in names} | ({where[mid]} if mid in where else set()) | set(span.get(mid) or []))
        if len(vs) == 1:
            where[mid] = vs[0]
        elif len(vs) > 1:
            where.pop(mid, None)
            span[mid] = vs
    keep = ("value", "name", "declared", "note", "provenance", "confirmed", "ghosts", "members")
    extra = {g["value"]: {k: g[k] for k in keep[1:] if k in g} for g in p["groups"]}
    for e in extra.values():
        if "ghosts" in e:
            e["ghosts"] = {k: v for k, v in e["ghosts"].items() if v}
    return carry({"label": p["label"], "source": p.get("source") or "labels", "by": "hypotheses"}, values, where, span, out, on, extra)


def from_announcements(field: str, label: str, out: dict, on: dict, announced: dict[str, dict[str, list[str]]]) -> dict | None:
    """The partition by what the machines announced in ``field``; None with fewer than two values."""
    said = {}
    for m in out.get("machines") or []:
        vs = (announced.get(m["id"]) or {}).get(field) or ([m[field]] if isinstance(m.get(field), str) and m[field] else [])
        if vs:
            said[m["id"]] = sorted(set(vs))
    values = sorted({v for vs in said.values() for v in vs})
    if len(values) < 2:
        return None
    where = {mid: vs[0] for mid, vs in said.items() if len(vs) == 1}
    span = {mid: vs for mid, vs in said.items() if len(vs) > 1}
    return carry({"label": label, "source": "announced", "by": field}, values, where, span, out, on)


def default_of(parts: list[dict], model_default: str | None) -> str | None:
    """Where the map starts: the declared partition when there is one, else the model's own default
    (the one the Dynamics page opens on), whatever it boxes: the page starts with boxes off when it
    boxes no machine, and says why. With no model partition, the announced partition the hand-offs
    separate best (the most pairs handed on inside a box, the fewest crossing, then by label)."""
    if any(p.get("source") == "declared" for p in parts):
        return next(p["label"] for p in parts if p.get("source") == "declared")
    if model_default is not None:
        return model_default
    said = [p for p in parts if p.get("source") == "announced"]
    return min(said, key=lambda p: (-p["joined"], p["crossed"], p["label"]))["label"] if said else None


def subsystems(out: dict, model_subs: dict | None, announced: dict[str, dict[str, list[str]]]) -> dict:
    """``/api/machines``'s ``subsystems``: the model's partitions (declared first) carried to the
    machines, then one per announced field; the default as ``default_of`` says."""
    on, tags = on_types(out), _tags(out)
    parts = [from_model(p, out, on, tags) for p in (model_subs or {}).get("partitions") or []]
    taken = {p["label"] for p in parts}
    said = []
    for f in FIELDS:
        label = f if f not in taken else f"{f} (announced)"
        if (p := from_announcements(f, label, out, on, announced)) is not None:
            said.append(p)
    return {"default": default_of(parts + said, (model_subs or {}).get("default")), "partitions": parts + said,
            **({"declared": model_subs["declared"]} if (model_subs or {}).get("declared") else {})}
