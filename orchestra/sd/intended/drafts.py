"""Whether an edit of a machine's draft expected effect can be published yet (§2, P4.9), one rule
for the Machines page (``machines_view``) and the plugin's summary (``design``): an edit naming a
declared stock or effect with no ``found_as``, as its ``stock`` or as an end of an ``appears``
flow, waits for a series; one naming a stock that is neither declared nor in the model is not in
the model."""

from __future__ import annotations

WAITS = "waits for a series"
ABSENT = "not in the model"


def names_of(model, layer: dict) -> dict[str, str]:
    """What an edit may name, and its display name: the model's stocks and flows by id, and the
    declared stocks and effects."""
    names = {s.id: s.name for s in (model.stocks if model else [])} | {f.id: f.name for f in (model.flows if model else [])}
    return names | {k: v["name"] for g in ("stocks", "effects") for k, v in layer[g].items()}


def _declared(layer: dict, eid) -> dict | None:
    return (layer["stocks"].get(eid) or layer["effects"].get(eid)) if eid else None


def publishable(edit: dict, layer: dict, names: dict[str, str]) -> tuple[bool, str | None]:
    """(whether the edit can be published now, why not)."""
    sid = edit.get("stock")
    if sid is not None:
        decl = _declared(layer, sid)
        if decl is not None and not decl.get("found_as"):
            return False, WAITS
        if decl is None and sid not in names:
            return False, ABSENT
        return True, None
    if edit.get("flow") is not None or edit.get("loop") is not None:
        return True, None
    for end in (edit.get("from"), edit.get("to")):
        decl = _declared(layer, end)
        if decl is not None and not decl.get("found_as"):
            return False, WAITS
    return True, None
