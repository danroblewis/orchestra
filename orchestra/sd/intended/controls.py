"""The page controls that are observations: AGENTS.md rule 9's closed list (as amended), written
once for the store (``page_control``) and the web server (``web/intended.py``). ``expect``,
``unexpect`` and ``ignore`` mark a discovered stock or flow; ``confirm`` and ``discard`` settle a
stock, effect or flow. A machine's or an attachment's controls are requests (``requests.py``)."""

from __future__ import annotations

from .checks import IntentError

PAGE_MARKS = ("expect", "unexpect", "ignore")
PAGE_SETTLES = ("confirm", "discard")
PAGE_PARTS = ("stock", "effect", "flow")
OBSERVATIONS = PAGE_MARKS + PAGE_SETTLES


def page_control(ops: list) -> None:
    """A page's call is one control from the closed list."""
    op = ops[0] if len(ops) == 1 and isinstance(ops[0], dict) else None
    name = (op or {}).get("op")
    if op is None or not (name in PAGE_MARKS or (name in PAGE_SETTLES and op.get("part") in PAGE_PARTS)):
        raise IntentError("a page records one observation: expect, unexpect, ignore, or confirm or discard on a stock, "
                          "effect or flow; anything else is a plugin's", status=400)
