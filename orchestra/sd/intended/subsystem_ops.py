"""The op on a declared **subsystem** (docs/proposals/subsystems.md §5, B15; the owner, 2026-11-02:
"sub 4. yes it can gather"). A subsystem is a group of a partition of the one model, never a split
(AGENTS.md rule 4): declaring one names a group or gathers parts into one, and changes no stock,
flow, equation, hypothesis or version. Discovery never reads it (rule 7 as amended).

Two shapes, one op (``declare_subsystem``):

- ``{id?, name, note?, label, value}``: a name for a label's value ("the hotfix line" for
  ``workflow=hotfix``). The label is never who wrote a series (``NOT_IDENTITY``) nor Orchestra's own
  flags (``simulated``, ``draft``): a writer is never a subsystem (rule 7). A label's value is named
  by one subsystem at a time.
- ``{id?, name, note?, members: {stocks: [keys], flows: [keys], machines: [ids]}}``: parts gathered
  that no label groups. Stocks and flows by key (``keys.py``: discovered ids follow arrival order),
  machines by id; at least one member; a member is in one declared subsystem at a time, so every
  part is in at most one group.

The same op on an id already declared replaces it; what is the owner's is replaced only with the
owner's consent (``consent.guard_owners``). Retract, confirm and discard are the generic ops on
``part: "subsystem"``. What the owner declares (quoted) is declared; what another author proposes
waits as ``proposed`` until the owner confirms it."""

from __future__ import annotations

from ..discover import NOT_IDENTITY
from .checks import IntentError, make_slug, only, slug, text
from .consent import guard_owners

MEMBERS = ("stocks", "flows", "machines")
LEFT = NOT_IDENTITY | {"simulated", "draft"}


def _members(m) -> dict[str, list[str]]:
    if not isinstance(m, dict):
        raise IntentError(f"members is an object {{stocks: [keys], flows: [keys], machines: [ids]}}, not {m!r}")
    if extra := sorted(set(m) - set(MEMBERS)):
        raise IntentError(f"members: unknown field{'s' if len(extra) > 1 else ''} {', '.join(extra)} (stocks, flows, machines)")
    out = {}
    for k in MEMBERS:
        v = m.get(k) or []
        if not isinstance(v, list) or not all(isinstance(x, str) and x.strip() and len(x) <= 1000 for x in v):
            raise IntentError(f"members.{k} is a list of non-empty strings (keys for stocks and flows, ids for machines)")
        if len(set(v)) != len(v):
            raise IntentError(f"members.{k} names each part once")
        out[k] = list(v)
    if not any(out.values()):
        raise IntentError("a subsystem that gathers names at least one member")
    return out


def declare_subsystem(layer: dict, op: dict, ctx: dict) -> tuple[str, str]:
    only(op, ("id", "name", "note", "label", "value", "members"), "declare_subsystem")
    name = text(op.get("name"), "name", required=True, limit=200)
    eid = slug(op.get("id") or make_slug(name))
    by_label = op.get("label") is not None or op.get("value") is not None
    if by_label == (op.get("members") is not None):
        raise IntentError("a subsystem names a label's value (label, value) or gathers members, one of the two")
    fields = {"name": name, "note": text(op.get("note"), "note")}
    if by_label:
        label = text(op.get("label"), "label", required=True, limit=200)
        value = text(op.get("value"), "value", required=True, limit=1000)
        if label in LEFT:
            raise IntentError(f"{label} says who wrote a series or is Orchestra's own flag: never a subsystem")
        if other := next((x for xid, x in layer["subsystems"].items() if xid != eid and (x.get("label"), x.get("value")) == (label, value)), None):
            raise IntentError(f"{label}={value} is already named by subsystem {other['id']}")
        fields.update(label=label, value=value)
    else:
        members = _members(op.get("members"))
        for xid, x in layer["subsystems"].items():
            if xid == eid:
                continue
            for k in MEMBERS:
                if both := sorted(set(members[k]) & set((x.get("members") or {}).get(k) or [])):
                    raise IntentError(f"{k} {', '.join(both)} already in subsystem {xid}: a part is in one subsystem at a time")
        fields["members"] = members
    old = layer["subsystems"].get(eid)
    if old is not None:
        guard_owners(old, ctx, "subsystem", eid)
    layer["subsystems"][eid] = {"id": eid, "part": "subsystem", **fields,
                                "state": "declared" if ctx["provenance"].get("author") == "owner" else "proposed",
                                "provenance": ctx["provenance"], "change": ctx["change"], "guessed": [], "pending": []}
    return "subsystem", eid
