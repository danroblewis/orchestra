"""``design()`` (§6.3, P4.10): the declared layer in brief for the plugin that keeps it: its version,
each element with its state, presence, link and guessed fields, the open items (unconfirmed
proposals, pending changes, unanswered requests, unsettled suggestions, absent expected parts,
unpublishable drafts) and the last 20 changes. Small: under 20 KB for 100 elements."""

from __future__ import annotations

from .requests import unanswered

LAST = 20


def design(intended, block: dict | None = None) -> dict:
    """``block``: the Dynamics comparison to read presence and suggestions from (computed from the
    latest discovery when not given; with no model, presence is unknown)."""
    cur = intended.read()
    layer = cur["layer"]
    if block is None:
        try:
            block = intended.diff(limit_s=0.0) if intended.models.current_version() or intended.models.latest_discovery() else None
        except Exception:  # noqa: BLE001 - the summary stands without the comparison
            block = None
    present = {(e["part"], e.get("id") or e.get("key")): e["present"] for e in (block or {}).get("expected", [])}
    elements = []
    for part, group in (("stock", "stocks"), ("effect", "effects"), ("flow", "flows"), ("machine", "machines"),
                        ("attachment", "attachments")):
        for eid, el in layer[group].items():
            row = {"part": part, "id": eid, "state": el.get("state")}
            if part in ("stock", "effect", "flow"):
                row["present"] = present.get((part, eid))
            if el.get("found_as"):
                row["found_as"] = el["found_as"]
            if el.get("guessed"):
                row["guessed"] = el["guessed"]
            if el.get("pending"):
                row["pending"] = [p["change"] for p in el["pending"]]
            elements.append(row)
    for key, mk in layer["marks"]["expected"].items():
        elements.append({"part": mk["part"], "key": key, "state": "expected", "present": present.get((mk["part"], key))})
    open_items = [{"what": "unconfirmed", "part": e["part"], "id": e["id"]} for e in elements if e.get("state") == "proposed"]
    open_items += [{"what": "pending change", "part": e["part"], "id": e["id"], "change": c} for e in elements for c in e.get("pending", [])]
    open_items += [{"what": "unanswered request", "part": p, "id": i, "control": r["control"], "event": r["event"]}
                   for (p, i), r in unanswered(intended).items()]
    open_items += [{"what": "absent expected part", "part": e["part"], "id": e.get("id"), "key": e.get("key")}
                   for e in (block or {}).get("expected", []) if not e["present"]]
    if block:
        open_items += [{"what": "unsettled suggestion", "part": c["part"], "key": c["key"]}
                       for c in block.get("changes", []) if c["sign"] == "+" and "expect" in c.get("controls", [])]
    for mid, m in layer["machines"].items():
        for e in (m.get("expected_effect") or {}).get("edits") or []:
            sid = e.get("stock")
            d = layer["stocks"].get(sid) if sid else None
            if d is not None and not d.get("found_as"):
                open_items.append({"what": "unpublishable draft", "part": "machine", "id": mid, "stock": sid})
    last = [c for e in intended.journal()[-LAST:] for c in e.get("changes", [])][-LAST:]
    return {"version": cur["version"], "elements": elements, "open": open_items, "last_changes": last,
            "stabilised": (block or {}).get("stabilised")}
