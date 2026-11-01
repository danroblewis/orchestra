"""The ops on stocks, effects, flows, marks, targets and event types (§6.3), each applied to a
layer in place. A machine's and an attachment's are ``machine_ops``. Each op returns the part and
id it changed; the store gives it its change id and provenance.

What the owner asks for (``author: owner``) is declared at once; what another author proposes
enters ``proposed`` (§3). Nothing here reads a discovered model: a declaration binds no series and
is matched to one only by ``link`` (rule 7 as amended)."""

from __future__ import annotations

from . import machine_ops
from .checks import IntentError, make_slug, no_derived, only, slug, strings, target, text
from .revise import at_once, revise, settle_pending

GROUP = {"stock": "stocks", "effect": "effects", "flow": "flows", "machine": "machines", "attachment": "attachments",
         "event": "events"}
OPTION = ("key", "title", "how", "kind", "instrument", "simulated", "cost", "caveat", "clearance", "provenance", "commit",
          "first_points")


def empty() -> dict:
    return {"stocks": {}, "effects": {}, "flows": {}, "machines": {}, "events": {}, "attachments": {}, "targets": {},
            "marks": {"expected": {}, "ignored": {}}}


def _state(ctx) -> str:
    return "declared" if ctx["provenance"].get("author") == "owner" else "proposed"


def _new(ctx, **fields) -> dict:
    return {**fields, "state": _state(ctx), "provenance": ctx["provenance"], "change": ctx["change"],
            "guessed": strings(ctx["op"].get("guessed"), "guessed"), "pending": []}


def element(layer: dict, part: str, eid) -> dict:
    group = layer.get(GROUP.get(part, ""), None)
    if group is None:
        raise IntentError(f"part must be one of {', '.join(GROUP)}, not {part!r}")
    if eid not in group:
        raise IntentError(f"there is no {part} {eid!r} in the declared layer")
    return group[eid]


def declare_level(layer: dict, op: dict, ctx: dict, part: str) -> tuple[str, str]:
    only(op, ("id", "name", "unit", "near", "note"), f"declare_{part}")
    name = text(op.get("name"), "name", required=True, limit=200)
    eid = slug(op.get("id") or make_slug(name))
    fields = {"name": name, "unit": text(op.get("unit"), "unit", limit=64), "near": text(op.get("near"), "near", limit=1000),
              "note": text(op.get("note"), "note")}
    group = layer[GROUP[part]]
    other = "effects" if part == "stock" else "stocks"
    if eid in layer[other]:
        raise IntentError(f"{eid} is already declared as {'an effect' if part == 'stock' else 'a stock'}")
    if eid in group:
        changed = {k: v for k, v in fields.items() if op.get(k) is not None}
        revise(group[eid], changed, {}, {}, strings(op.get("guessed"), "guessed"), ctx)
        return part, eid
    group[eid] = _new(ctx, id=eid, part=part, **fields, found_as=None, measure=None, target=None)
    return part, eid


def declare_flow(layer: dict, op: dict, ctx: dict) -> tuple[str, str]:
    only(op, ("id", "from", "to", "name", "note"), "declare_flow")
    a, b = text(op.get("from"), "from", limit=1000), text(op.get("to"), "to", limit=1000)
    if a is None and b is None:
        raise IntentError("a flow has at least one end in a stock (null is outside)")
    eid = slug(op.get("id") or make_slug(f"{a or 'outside'}_to_{b or 'outside'}"))
    if eid in layer["flows"]:
        raise IntentError(f"flow {eid} is already declared")
    name = text(op.get("name"), "name", limit=200) or f"{a or 'outside'} → {b or 'outside'}"
    layer["flows"][eid] = _new(ctx, id=eid, part="flow", name=name, note=text(op.get("note"), "note"), **{"from": a, "to": b},
                               target=None)
    return "flow", eid


def set_target(layer: dict, op: dict, ctx: dict) -> tuple[str, str]:
    only(op, ("part", "id", "key", "target", "value", "hi", "over_s"), "set_target")
    part = op.get("part")
    if part not in ("stock", "effect", "flow"):
        raise IntentError(f"a target is on a stock, an effect or a flow, not {part!r}")
    t = target({"op": op.get("target"), **{k: op[k] for k in ("value", "hi", "over_s") if k in op}})
    if op.get("id") is not None:
        element(layer, part, op["id"])["target"] = t
        return part, op["id"]
    key = text(op.get("key"), "key", required=True, limit=1000)
    layer["targets"][key] = {"part": part, "key": key, "target": t, "provenance": ctx["provenance"], "change": ctx["change"]}
    return part, key


def mark(layer: dict, op: dict, ctx: dict, which: str, on: bool) -> tuple[str, str]:
    only(op, ("part", "key"), op["op"])
    part = op.get("part")
    if part not in ("stock", "flow"):
        raise IntentError(f"a mark is on a discovered stock or flow, by key, not {part!r}")
    key = text(op.get("key"), "key", required=True, limit=1000)
    marks = layer["marks"][which]
    if on:
        marks[key] = {"part": part, "key": key, "provenance": ctx["provenance"], "change": ctx["change"]}
    elif marks.pop(key, None) is None:
        raise IntentError(f"{key} is not {which}")
    return part, key


def link(layer: dict, op: dict, ctx: dict) -> tuple[str, str]:
    only(op, ("id", "part", "found_as"), "link")
    part = op.get("part") or ("stock" if op.get("id") in layer["stocks"] else "effect")
    if part not in ("stock", "effect"):
        raise IntentError(f"link joins a declared stock or effect to what discovery found, not a {part}")
    el = element(layer, part, op.get("id"))
    el["found_as"] = text(op.get("found_as"), "found_as", limit=1000)
    el["linked"] = {"by": ctx["provenance"].get("author"), "change": ctx["change"]} if el["found_as"] else None
    return part, el["id"]


def declare_event(layer: dict, op: dict, ctx: dict) -> tuple[str, str]:
    only(op, ("type", "description"), "declare_event")
    t = text(op.get("type"), "type", required=True, limit=200)
    layer["events"][t] = {"type": t, "description": text(op.get("description"), "description"), "implicit": False,
                          "provenance": ctx["provenance"], "change": ctx["change"]}
    return "event", t


def record_measurement(layer: dict, op: dict, ctx: dict) -> tuple[str, str]:
    only(op, ("part", "id", "options", "chosen"), "record_measurement")
    el = element(layer, op.get("part") or "stock", op.get("id"))
    opts = op.get("options")
    if not isinstance(opts, list) or not opts:
        raise IntentError("options is a non-empty list")
    out = []
    for o in opts:
        if not isinstance(o, dict):
            raise IntentError(f"an option is an object, not {o!r}")
        no_derived(o)
        if extra := sorted(set(o) - set(OPTION)):
            raise IntentError(f"an option's unknown field{'s' if len(extra) > 1 else ''}: {', '.join(extra)}")
        text(o.get("key"), "an option's key", required=True, limit=40)
        out.append(dict(o))
    keys = [o["key"] for o in out]
    if len(set(keys)) != len(keys):
        raise IntentError("each option's key is used once")
    chosen = op.get("chosen")
    if chosen is not None and chosen not in keys:
        raise IntentError(f"chosen must be one of the options' keys ({', '.join(keys)}), not {chosen!r}")
    el["measure"] = {"options": out, "chosen": chosen, "change": ctx["change"]}
    return el["part"], el["id"]


def confirm(layer: dict, op: dict, ctx: dict, accept: bool) -> tuple[str, str]:
    only(op, ("part", "id", "change"), op["op"])
    part, eid = op.get("part"), op.get("id")
    el = element(layer, part, eid)
    if op.get("change"):
        settle_pending(el, op["change"], accept, ctx)
        return part, eid
    if el.get("state") != "proposed":
        raise IntentError(f"{part} {eid} is {el.get('state')}, not proposed" + ("" if accept else ": retract it"))
    if accept:
        el.update(state="declared", guessed=[], confirmed={"by": ctx["provenance"].get("author"), "change": ctx["change"]})
    else:
        del layer[GROUP[part]][eid]
        _orphans(layer, part, eid)
    return part, eid


def _orphans(layer: dict, part: str, eid: str) -> None:
    """A machine discarded or retracted takes its attachments with it."""
    if part == "machine":
        layer["attachments"] = {k: a for k, a in layer["attachments"].items() if a["machine"] != eid}


def retract(layer: dict, op: dict, ctx: dict) -> tuple[str, str]:
    only(op, ("part", "id"), "retract")
    part, eid = op.get("part"), op.get("id")
    element(layer, part, eid)
    del layer[GROUP[part]][eid]
    _orphans(layer, part, eid)
    return part, eid


def apply_op(layer: dict, op: dict, ctx: dict) -> tuple[str, str]:
    """Apply one op in place; returns (part, id)."""
    if not isinstance(op, dict):
        raise IntentError(f"an op is an object, not {op!r}")
    name = op.get("op")
    ctx = {**ctx, "op": op}
    simple = {"declare_stock": lambda: declare_level(layer, op, ctx, "stock"),
              "declare_effect": lambda: declare_level(layer, op, ctx, "effect"),
              "declare_flow": lambda: declare_flow(layer, op, ctx),
              "set_target": lambda: set_target(layer, op, ctx),
              "expect": lambda: mark(layer, op, ctx, "expected", True), "unexpect": lambda: mark(layer, op, ctx, "expected", False),
              "ignore": lambda: mark(layer, op, ctx, "ignored", True), "unignore": lambda: mark(layer, op, ctx, "ignored", False),
              "link": lambda: link(layer, op, ctx), "declare_event": lambda: declare_event(layer, op, ctx),
              "record_measurement": lambda: record_measurement(layer, op, ctx),
              "confirm": lambda: confirm(layer, op, ctx, True), "discard": lambda: confirm(layer, op, ctx, False),
              "retract": lambda: retract(layer, op, ctx)}
    if name in simple:
        return simple[name]()
    if name in machine_ops.OPS:
        return machine_ops.OPS[name](layer, op, ctx)
    raise IntentError(f"unknown op {name!r}")


__all__ = ["apply_op", "at_once", "element", "empty"]
