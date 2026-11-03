"""The ops on stocks, effects, flows, marks, targets and event types (§6.3), and the subsystem's
declaration (``subsystem_ops``), each applied to a
layer in place. A machine's and an attachment's are ``machine_ops``. Each op returns the part and
id it changed; the store gives it its change id and provenance.

What the owner asks for (``author: owner``) is declared at once, a re-declaration of a proposed
stock, effect or flow included (and of a declared flow: a revision); what another author proposes
enters ``proposed`` (§3). A proposal or a pending change is confirmed or discarded by the owner,
or by the plugin answering the owner's request to do just that (``provenance.request``, §6.2,
checked in ``consent.py``), never by its author alone; a confirmation the owner gave, directly or
by request, makes the element the owner's (``confirmed.by``). What is the owner's (an element,
mark, target or described event type: ``consent.owners``) is retracted, unmarked, overwritten or
re-targeted only by the owner, or in answer to the owner's request: another author's re-mark of
the owner's mark leaves it as it is. A key is expected or ignored, never both: one mark replaces
the other. A declared stock or effect that a declared flow, a keyed target or a machine's
expected effect names (a pending change's included) is not retracted or discarded until they are
changed, so no flow is left to resolve its end some other way; an event type a machine names is
not retracted until the machine changes. Nothing here reads a discovered model: a declaration
binds no series and is matched to one only by ``link`` (rule 7 as amended)."""

from __future__ import annotations

import re

from . import machine_ops
from .checks import IntentError, make_slug, no_derived, only, slug, strings, target, text
from .consent import consents, guard_owners, may_settle, owner_asks, owners
from .revise import revise, settle_pending
from .subsystem_ops import declare_subsystem

GROUP = {"stock": "stocks", "effect": "effects", "flow": "flows", "machine": "machines", "attachment": "attachments",
         "event": "events", "subsystem": "subsystems"}
OPTION = ("key", "title", "how", "kind", "instrument", "simulated", "cost", "caveat", "clearance", "provenance", "commit",
          "first_points", "bearer_env", "system", "series", "url", "command")
# what an option names, as text: the company system it reads, the series, where and how (machine-design §2.2)
OPTION_TEXT = {"system": 200, "series": 1000, "url": 2000, "command": 2000}
ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")   # a credential is named by its variable, never given
URL_SECRET = re.compile(r"://[^/@\s]*:[^/@\s]*@")          # user:password@ in a url


def empty() -> dict:
    return {"stocks": {}, "effects": {}, "flows": {}, "machines": {}, "events": {}, "attachments": {}, "targets": {}, "subsystems": {},
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
    only(op, ("id", "name", "description", "unit", "near", "note"), f"declare_{part}")
    name = text(op.get("name"), "name", required=True, limit=200)
    eid = slug(op.get("id") or make_slug(name))
    fields = {"name": name, "description": text(op.get("description"), "description"), "unit": text(op.get("unit"), "unit", limit=64),
              "near": text(op.get("near"), "near", limit=1000), "note": text(op.get("note"), "note")}
    group = layer[GROUP[part]]
    other = "effects" if part == "stock" else "stocks"
    if eid in layer[other]:
        raise IntentError(f"{eid} is already declared as {'an effect' if part == 'stock' else 'a stock'}")
    if eid in group:
        el = group[eid]
        changed = {k: v for k, v in fields.items() if op.get(k) is not None}
        revise(el, changed, {}, {}, strings(op.get("guessed"), "guessed"), ctx)
        if el.get("state") == "proposed" and owner_asks(ctx["provenance"]):
            el.update(state="declared", confirmed={"by": "owner", "change": ctx["change"]})
        return part, eid
    group[eid] = _new(ctx, id=eid, part=part, **fields, found_as=None, measure=None, target=None)
    return part, eid


def declare_flow(layer: dict, op: dict, ctx: dict) -> tuple[str, str]:
    """An expected flow between two ends, each a declared stock's or effect's id or a discovered
    stock's key (never a discovered id: ids follow arrival order), ``null`` for outside. A
    declared id wins over a discovered key of the same text."""
    only(op, ("id", "from", "to", "name", "note"), "declare_flow")
    a, b = text(op.get("from"), "from", limit=1000), text(op.get("to"), "to", limit=1000)
    if a is None and b is None:
        raise IntentError("a flow has at least one end in a stock (null is outside)")
    eid = slug(op.get("id") or make_slug(f"{a or 'outside'}_to_{b or 'outside'}"))
    if eid in layer["flows"]:
        el = layer["flows"][eid]
        if not owner_asks(ctx["provenance"]):
            raise IntentError(f"flow {eid} is already {'proposed' if el.get('state') == 'proposed' else 'declared'}")
        changed = {k: v for k, v in (("from", a), ("to", b), ("name", text(op.get("name"), "name", limit=200)),
                                     ("note", text(op.get("note"), "note"))) if op.get(k) is not None}
        revise(el, changed, {}, {}, strings(op.get("guessed"), "guessed"), ctx)
        if el.get("state") == "proposed":
            el.update(state="declared", confirmed={"by": "owner", "change": ctx["change"]})
        return "flow", eid
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
        el = element(layer, part, op["id"])
        guard_owners(el.get("target_by") or el, ctx, part, op["id"])     # who set the target, else whose the element is
        el["target"] = t
        el["target_by"] = {"provenance": ctx["provenance"], "change": ctx["change"]}
        return part, op["id"]
    key = text(op.get("key"), "key", required=True, limit=1000)
    guard_owners(layer["targets"].get(key), ctx, part, key)
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
        other = layer["marks"]["ignored" if which == "expected" else "expected"]
        if key in other:                          # expected or ignored, never both
            guard_owners(other[key], ctx, part, key)
            del other[key]
        if key in marks and owners(marks[key]) and not consents(ctx, part, key):
            return part, key                      # the owner's mark stands, with the owner's provenance
        marks[key] = {"part": part, "key": key, "provenance": ctx["provenance"], "change": ctx["change"]}
        return part, key
    if key not in marks:
        raise IntentError(f"{key} is not {which}")
    guard_owners(marks[key], ctx, part, key)
    del marks[key]
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
    old = layer["events"].get(t)
    if old is not None and not old.get("implicit"):          # an undescribed type is described at once
        guard_owners(old, ctx, "event", t)
    layer["events"][t] = {"type": t, "description": text(op.get("description"), "description"), "implicit": False,
                          "provenance": ctx["provenance"], "change": ctx["change"]}
    return "event", t


def record_measurement(layer: dict, op: dict, ctx: dict) -> tuple[str, str]:
    only(op, ("part", "id", "options", "chosen"), "record_measurement")
    part, eid = op.get("part") or "stock", op.get("id")
    if part not in ("stock", "effect"):
        raise IntentError(f"a measurement is recorded for a declared stock or effect, not a {part}")
    el = element(layer, part, eid)
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
        _option_names(o)
        out.append(dict(o))
    keys = [o["key"] for o in out]
    if len(set(keys)) != len(keys):
        raise IntentError("each option's key is used once")
    chosen = op.get("chosen")
    if chosen is not None and chosen not in keys:
        raise IntentError(f"chosen must be one of the options' keys ({', '.join(keys)}), not {chosen!r}")
    el["measure"] = {"options": out, "chosen": chosen, "change": ctx["change"]}
    return part, eid


def _option_names(o: dict) -> None:
    """What an option names is text; its credential only by the environment variable that holds it."""
    for k, limit in OPTION_TEXT.items():
        text(o.get(k), f"an option's {k}", limit=limit)
    if o.get("url") and URL_SECRET.search(o["url"]):
        raise IntentError("an option's url carries no password: name the credential by its environment variable (bearer_env)")
    env = o.get("bearer_env")
    if env is not None and (not isinstance(env, str) or not ENV_NAME.match(env)):
        raise IntentError(f"an option's bearer_env is the name of an environment variable (WORK_TOKEN), never a value, not {env!r}")


def confirm(layer: dict, op: dict, ctx: dict, accept: bool) -> tuple[str, str]:
    only(op, ("part", "id", "change"), op["op"])
    part, eid = op.get("part"), op.get("id")
    el = element(layer, part, eid)
    may_settle(ctx, part, eid, op["op"], op.get("change") or None)
    if op.get("change"):
        settle_pending(el, op["change"], accept, ctx, part)
        if accept and part == "machine":
            machine_ops.implicit_events(layer, el, ctx)
        return part, eid
    if el.get("state") != "proposed":
        raise IntentError(f"{part} {eid} is {el.get('state')}, not proposed" + ("" if accept else ": retract it"))
    if accept:
        el.update(state="declared", guessed=[], confirmed=_confirmed_by(ctx))
    else:
        _remove(layer, part, eid)
    return part, eid


def _confirmed_by(ctx: dict) -> dict:
    """Who confirmed: the owner (asking, or by the request the call answers), else the author."""
    prov, cid = ctx["provenance"], ctx["change"]
    if owner_asks(prov):
        return {"by": "owner", "change": cid}
    if prov.get("request"):                       # may_settle verified it: the owner's request
        return {"by": "owner", "via": "request", "request": prov["request"], "change": cid}
    return {"by": prov.get("author"), "change": cid}


def _names(edits: list, eid: str) -> bool:
    return any(eid in (e.get("stock"), e.get("from"), e.get("to")) for e in edits or [])


def _named_by(layer: dict, eid: str) -> list[str]:
    """What names a declared stock or effect: declared flows (an end), a keyed target, the
    machines' expected-effect edits, and the pending changes that would set one of them."""
    out = [f"flow {fid}" for fid, f in layer["flows"].items() if eid in (f.get("from"), f.get("to"))]
    if eid in layer["targets"]:
        out.append(f"the target on {eid}")
    for mid, m in layer["machines"].items():
        if _names((m.get("expected_effect") or {}).get("edits"), eid):
            out.append(f"machine {mid}'s expected effect")
    for part, group in (("machine", "machines"), ("attachment", "attachments"), ("flow", "flows")):
        for xid, x in layer[group].items():
            for p in x.get("pending") or []:
                s = p.get("set") or {}
                if _names((s.get("expected_effect") or {}).get("edits"), eid) or eid in (s.get("from"), s.get("to")):
                    out.append(f"{part} {xid}'s pending change {p.get('change')}")
    return out


def _remove(layer: dict, part: str, eid: str) -> None:
    """Remove an element: a stock or effect only once nothing declared names it, an event type
    only once no machine names it; a machine takes its attachments with it."""
    if part in ("stock", "effect") and (by := _named_by(layer, eid)):
        raise IntentError(f"{part} {eid} is named by {', '.join(by)}: retract or change {'it' if len(by) == 1 else 'them'} first")
    if part == "event" and (ms := [mid for mid, m in layer["machines"].items()
                                   if eid in [*(m.get("receives") or []), *(m.get("emits") or [])]]):
        raise IntentError(f"event {eid} is named by machine{'s' if len(ms) > 1 else ''} {', '.join(ms)}: change the machine first")
    del layer[GROUP[part]][eid]
    if part == "machine":
        layer["attachments"] = {k: a for k, a in layer["attachments"].items() if a["machine"] != eid}


def retract(layer: dict, op: dict, ctx: dict) -> tuple[str, str]:
    only(op, ("part", "id"), "retract")
    part, eid = op.get("part"), op.get("id")
    guard_owners(element(layer, part, eid), ctx, part, eid)
    _remove(layer, part, eid)
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
              "retract": lambda: retract(layer, op, ctx),
              "declare_subsystem": lambda: declare_subsystem(layer, op, ctx)}
    if name in simple:
        return simple[name]()
    if name in machine_ops.OPS:
        return machine_ops.OPS[name](layer, op, ctx)
    raise IntentError(f"unknown op {name!r}")


__all__ = ["GROUP", "apply_op", "element", "empty"]
