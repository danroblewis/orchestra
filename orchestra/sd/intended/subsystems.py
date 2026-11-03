"""Declared subsystems beside the derived partitions (docs/proposals/subsystems.md §5, B14, B15): what
``/api/dynamics/model`` and ``/api/machines`` serve as ``subsystems``, declared first when present.

- A subsystem that **names a label's value** (``{label, value}``) titles that group's box in the
  partition by that label: the group gains ``name``, ``declared`` (its id), ``note`` and
  ``provenance`` (the pages say "named by <who>"; the raw value stays the group's ``value``), and
  that partition becomes the default.
- The subsystems that **gather** (``{members}``) make one partition of their own, ``declared``
  (``source: "declared"``), listed and drawn first: a group per subsystem, its value the
  subsystem's id. Its stocks and flows are matched by key (``keys.py``); a flow it does not name is
  placed by its ends and a machine by its hypotheses, as in any partition (``sd.subsystems.place``);
  a member the model does not have (any more) is a **ghost** in its box (``ghosts``: stock and flow
  keys), as an expected part is.

Only a declared subsystem (the owner's, or confirmed) is drawn; a proposal waits for the owner. It
binds no series and changes no equation, hypothesis or key; discovery never reads it (rule 7)."""

from __future__ import annotations

from ..subsystems import place
from .keys import Keys

DECLARED = "declared"


def declared(layer: dict) -> list[dict]:
    """The declared (not proposed) subsystems, in declaration order."""
    return [x for x in (layer.get("subsystems") or {}).values() if x.get("state") == "declared"]


def naming(el: dict) -> dict:
    """What a group carries of the subsystem that names or gathers it."""
    return {"name": el["name"], "declared": el["id"], "note": el.get("note"), "provenance": el.get("provenance") or {},
            **({"confirmed": el["confirmed"]} if el.get("confirmed") else {})}


def gathered(model, subs: list[dict]) -> dict | None:
    """The partition the gathering subsystems make of ``model``, with their ghosts; None without one."""
    gs = [x for x in subs if x.get("members")]
    if not gs or model is None:
        return None
    keys = Keys(model)
    stock_group, flow_group, machine_group, ghosts = {}, {}, {}, {}
    for x in gs:
        m, g = x["members"], ghosts.setdefault(x["id"], {"stocks": [], "flows": []})
        for k in m.get("stocks") or []:
            sid = keys.stocks.get(k)
            if sid is None:
                g["stocks"].append(k)
            else:
                stock_group[sid] = x["id"]
        for k in m.get("flows") or []:
            fid = keys.flows.get(k)
            if fid is None:
                g["flows"].append(k)
            else:
                flow_group[fid] = x["id"]
        for mid in m.get("machines") or []:
            machine_group[mid] = x["id"]
    p = place(model, DECLARED, stock_group, [x["id"] for x in gs], flows=flow_group, machines=machine_group)
    by = {x["id"]: x for x in gs}
    for g in p["groups"]:
        g.update(naming(by[g["value"]]), ghosts=ghosts[g["value"]], members=by[g["value"]]["members"])
    p["source"] = DECLARED
    return p


def with_declared(subs: dict, layer: dict | None, model) -> dict:
    """The derived partitions (``sd.subsystems.subsystems``) with the declared subsystems: the
    gathering partition first, the groups a subsystem names titled by it; the default the declared
    partition, else the first partition a declared subsystem names, else the derived default."""
    out = {"default": subs.get("default"), "partitions": [dict(p, groups=[dict(g) for g in p["groups"]]) for p in subs.get("partitions") or []]}
    for p in out["partitions"]:
        p.setdefault("source", "labels")
    ds = declared(layer or {})
    if not ds:
        return out
    named = {(x["label"], x["value"]): x for x in ds if x.get("label") is not None}
    first = None
    for p in out["partitions"]:
        for g in p["groups"]:
            if (x := named.get((p["label"], g["value"]))) is not None:
                g.update(naming(x))
                first = first or p["label"]
    g = gathered(model, ds)
    if g is not None:
        out["partitions"].insert(0, g)
        first = DECLARED
    out["default"] = first or out["default"]
    out["declared"] = [{k: x.get(k) for k in ("id", "name", "note", "label", "value", "members", "provenance")} for x in ds]
    return out
