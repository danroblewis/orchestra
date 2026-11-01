"""Whether an edit of a machine's draft expected effect can be published yet (§2, P4.9), one rule
for the Machines page (``machines_view``) and the plugin's summary (``design``), on the names as
``names.resolve`` reads them: an edit naming a declared stock or effect with no ``found_as``, as
its ``stock`` or as an end of an ``appears`` flow, waits for a series (or a link); one naming what
is neither declared nor in the model is not in the model. For a flow's end, the why names the end
("orders_open: not in the model"). An edit on a flow or a loop names the model's id and is
published as it is."""

from __future__ import annotations

from .keys import Keys
from .names import resolve

__all__ = ["publishable"]


def publishable(edit: dict, layer: dict, keys: Keys) -> tuple[bool, str | None]:
    """(whether the edit can be published now, why not)."""
    if edit.get("stock") is not None:
        why = resolve(edit["stock"], layer, keys).why
        return why is None, why
    if edit.get("flow") is not None or edit.get("loop") is not None:
        return True, None
    for end in (edit.get("from"), edit.get("to")):
        if (why := resolve(end, layer, keys).why) is not None:
            return False, f"{end}: {why}"
    return True, None
