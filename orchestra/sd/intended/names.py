"""The names in a machine's draft expected effect (§2, P4.9), resolved in one place for whether an
edit can be published (``drafts``), its label and link (``machines_view``) and the flows it
predicts (``diff.predicted``). An edit's ``stock``, ``from`` and ``to`` name, in the order tried:

1. a declared stock or effect, by its id: resolved through its ``found_as``, and unresolved
   while it has none: "waits for a link" when its measure has a chosen option (something records
   it, and the operator (a plugin's machine) links it once that is the stock), else "waits for a series";
2. a discovered stock, by its key (§3.1).

Anything else, a discovered id included, is "not in the model": ids follow arrival order, so a
stored draft naming one would point at another stock in a later version. ``None`` (an end of an
``appears`` flow) is outside. A draft names keys, which hold across versions; a plugin publishing a
draft as ``orchestra.prediction.made`` turns its keys into the era's ids (the judge reads ids).
Resolving reads only the layer and the model's keys."""

from __future__ import annotations

from dataclasses import dataclass

from .keys import OUTSIDE, Keys

WAITS = "waits for a series"
WAITS_LINK = "waits for a link"
ABSENT = "not in the model"


@dataclass(frozen=True)
class Name:
    text: str | None          # as the edit names it
    key: str | None           # the discovered stock key it resolves to (None: outside, or unresolved)
    id: str | None            # that stock's id in the model now, if it is there
    label: str                # what a page calls it
    why: str | None = None    # why it is unresolved; None when resolved
    declared: bool = False


def _stock_name(keys: Keys, sid: str | None) -> str | None:
    s = next((x for x in keys.model.stocks if x.id == sid), None) if keys.model and sid else None
    return s.name if s else None


def resolve(text: str | None, layer: dict, keys: Keys) -> Name:
    """One name of an edit, resolved against the declared layer and a model's keys."""
    if text is None:
        return Name(None, None, None, OUTSIDE)
    decl = layer["stocks"].get(text) or layer["effects"].get(text)
    if decl is not None:
        fa = decl.get("found_as")
        if not fa:
            why = WAITS_LINK if (decl.get("measure") or {}).get("chosen") else WAITS
            return Name(text, None, None, decl.get("name") or text, why, True)
        return Name(text, fa, keys.stocks.get(fa), decl.get("name") or text, None, True)
    if text in keys.stocks:
        sid = keys.stocks[text]
        return Name(text, text, sid, _stock_name(keys, sid) or text)
    return Name(text, None, None, text, ABSENT)


def link(name: Name) -> str:
    """The Dynamics page's anchor for a resolved stock: its id now, else the declared id."""
    return f"/dynamics#s:{name.id or name.text}"
