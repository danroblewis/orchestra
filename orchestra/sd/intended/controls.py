"""The page controls that are observations: AGENTS.md rule 9's closed list (as amended), written
once for the store (``page_control``) and the web server (``web/intended.py``). ``expect``,
``unexpect`` and ``ignore`` mark a discovered stock or flow; ``confirm`` and ``discard`` settle a
stock, effect or flow; ``ignore`` and ``unignore`` hide a machine from the Machines page and the
Event Map and show it again (by its source; several machines hidden at once are one call, the
"announced only" group's "Hide all of these"). Hiding is display only: it deletes or alters no
observed event, and discovery and ``sd/attribute.py`` never read it. A machine's other controls,
and an attachment's, are requests (``requests.py``)."""

from __future__ import annotations

from .checks import IntentError

PAGE_MARKS = ("expect", "unexpect", "ignore")
PAGE_SETTLES = ("confirm", "discard")
PAGE_PARTS = ("stock", "effect", "flow")
MACHINE_MARKS = ("ignore", "unignore")
OBSERVATIONS = PAGE_MARKS + PAGE_SETTLES + ("unignore",)


def _one(op) -> bool:
    name = op.get("op") if isinstance(op, dict) else None
    if isinstance(op, dict) and op.get("part") == "machine":
        return name in MACHINE_MARKS
    return name in PAGE_MARKS or (name in PAGE_SETTLES and op.get("part") in PAGE_PARTS)


def page_control(ops: list) -> None:
    """A page's call is one control from the closed list, or one control hiding (or showing) several
    machines at once."""
    ok = isinstance(ops, list) and len(ops) >= 1 and all(_one(op) for op in ops)
    if ok and len(ops) > 1:
        ok = all(op.get("part") == "machine" for op in ops) and len({op.get("op") for op in ops}) == 1
    if not ok:
        raise IntentError("a page records one observation: expect, unexpect, ignore, or confirm or discard on a stock, "
                          "effect or flow, or ignore or unignore on machines; anything else is a plugin's", status=400)
