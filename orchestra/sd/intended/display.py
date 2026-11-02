"""The declared names of discovered parts (§4.6, the owner, 2026-11-02: "We could allow the user to
give their own custom name, and use the effective ID name we have to associate it"). A declared
stock or effect linked to a discovered stock (``link``: its ``found_as`` is the stock's key), or a
declared flow found as one discovered flow by its ends and declared with a name of its own (not the
"<from> → <to>" the layer makes when none is given), lends its ``name`` to that part: the pages show
it as the part's name, with the generated title kept beneath it as the identifier and "named by
<who>" from the declaration's provenance. Only a declared element lends its name (a proposal waits
for its confirmation), and a part named by two declarations takes the owner's, else the first
declared. The name is display only: it binds no series and changes no key, title or equation
(rule 7), and nothing here reads a metric."""

from __future__ import annotations

from .diff import flow_matches
from .keys import Keys


def _generated(el: dict) -> bool:
    """Whether a declared flow's name is the one the layer made from its ends."""
    return el.get("name") == f"{el.get('from') or 'outside'} → {el.get('to') or 'outside'}"


def _found(part: str, el: dict, layer: dict, keys: Keys) -> str | None:
    """The id in the model of the part a declaration names, if it is there."""
    if part == "flow":
        key, _ = flow_matches(el, layer, keys)
        return keys.flows.get(key) if key else None
    return keys.stocks.get(el.get("found_as")) if el.get("found_as") else None


def declared_names(layer: dict, keys: Keys) -> dict:
    """``{stocks: {id: name}, flows: {id: name}}`` for the parts of a model (``keys``) a declaration
    names, each ``{name, part, id, provenance, linked?}`` (``id``: the declaration's; ``linked``:
    who linked it, for a stock or effect)."""
    out: dict[str, dict] = {"stocks": {}, "flows": {}}
    if keys.model is None:
        return out
    for part, group in (("stock", "stocks"), ("effect", "effects"), ("flow", "flows")):
        for el in layer.get(group, {}).values():
            if el.get("state") != "declared" or not el.get("name") or (part == "flow" and _generated(el)):
                continue
            pid = _found(part, el, layer, keys)
            if pid is None:
                continue
            into = out["flows" if part == "flow" else "stocks"]
            prov = el.get("provenance") or {}
            old = into.get(pid)
            if old is not None and ((old["provenance"] or {}).get("author") == "owner" or prov.get("author") != "owner"):
                continue
            into[pid] = {"name": el["name"], "part": part, "id": el["id"], "provenance": prov,
                         **({"linked": el["linked"]} if el.get("linked") else {})}
    return out
