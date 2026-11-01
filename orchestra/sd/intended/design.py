"""``design()`` (§6.3, P4.10): the declared layer in brief for the plugin that keeps it: its version,
each element with its state, presence, link and guessed fields, the open items (unconfirmed
proposals, pending changes, unanswered requests, unsettled suggestions, absent expected parts,
unpublishable drafts, and P5's "attached, nothing measured" and "declared, neither heard nor
measured") and the last 20 changes. Small: under 20 KB for 100 elements."""

from __future__ import annotations

import time

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
    open_items += _measured_items(intended, layer)
    last = [c for e in intended.journal()[-LAST:] for c in e.get("changes", [])][-LAST:]
    return {"version": cur["version"], "elements": elements, "open": open_items, "last_changes": last,
            "stabilised": (block or {}).get("stabilised")}


def _measured_items(intended, layer: dict) -> list[dict]:
    """The comparison's entries on attachments (P5 §3), for a store made with its project: each
    declared attachment that selects nothing measured, and each declared machine neither heard
    (its source in ``orchestra_events_total``, Orchestra's count of the bus) nor measured. Read
    from the own store under a time limit; a source's attachments are read by the web server
    only, so here they are unknown and listed as neither."""
    project = getattr(intended, "project", None)
    if project is None or not layer["machines"]:
        return []
    from ...collectors import EVENTS
    from ...metrics import for_project
    from . import measured as m
    from .facts import LIMIT_S, _within
    from .instruments import Instruments

    def read():
        store = for_project(project)
        kinds = Instruments(project).kinds()
        heard = {lab.get("source", "").split("/", 1)[0] for _, lab in store.series(EVENTS, {"project": project.key})}
        views = {}
        for a in layer["attachments"].values():
            own = kinds.get(a["instrument"]) not in ("source", None)
            views[a["id"]] = m.attachment_view(a, m.read_own(store, project.key, a) if own else None, time.time())
        return heard, views
    got, ok = _within(read, LIMIT_S)
    if not ok:
        return [{"what": "measured unknown", "why": "the metrics store did not answer in time"}]
    heard, views = got
    out = [{"what": m.NOTHING, "part": "attachment", "id": aid, "machine": v["machine"]}
           for aid, v in views.items() if v.get("comparison") == m.NOTHING]
    for mid, mach in layer["machines"].items():
        names = {mid, *(mach.get("aliases") or [])}
        mine = m.machine_measured([v for v in views.values() if v["machine"] == mid])
        if not names & heard and not mine["measured"]:
            out.append({"what": m.NEITHER, "part": "machine", "id": mid})
    return out
