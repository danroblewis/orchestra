"""``design()`` (§6.3, P4.10): the declared layer in brief for the plugin that keeps it: its version,
each element with its state, presence, link and guessed fields, the open items (unconfirmed
proposals, pending changes, unanswered requests, unsettled suggestions, absent expected parts,
unpublishable drafts with why, and confirmed machines not heard: their ``comparison``; a proposed
one is already open as unconfirmed) and the
last 20 changes. Small: under 20 KB for 100 elements, so a row leaves out a field it has no value
for.

Whether a machine is heard is read from Orchestra's count of the bus (``orchestra_events_total``,
by ``source``) under the time limit, for a store made with its project; past the limit, or
without one, it is unknown and no comparison item is listed."""

from __future__ import annotations

from .checks import IntentError
from .drafts import names_of, publishable
from .facts import LIMIT_S, _within
from .machines_view import comparison
from .requests import unanswered

LAST = 20


def _heard(intended) -> set[str] | None:
    """The machines on the bus (the sources of ``orchestra_events_total``), or None if unknown."""
    project = getattr(intended, "project", None)
    if project is None:
        return None
    from ...collectors import EVENTS
    from ...metrics import for_project

    def read():
        store = for_project(project)
        return {(lab.get("source") or "").split("/", 1)[0] for _, lab in store.series(EVENTS, {"project": project.key})}
    got, ok = _within(read, LIMIT_S)
    return got if ok else None


def _model(models):
    cached = models.latest_discovery()
    return cached[1] if cached else models.load()


def design(intended, hold: int, block: dict | None = None) -> dict:
    """``block``: the Dynamics comparison to read presence and suggestions from (computed from the
    latest discovery when not given; with no model, presence is unknown). ``hold``: the project's
    ``announce_hold``. A ``dN`` that cannot be read raises ``IntentError``."""
    cur = intended.read()
    layer = cur["layer"]
    if block is None:
        try:
            block = intended.diff(limit_s=0.0, hold=hold) if intended.models.current_version() or intended.models.latest_discovery() else None
        except IntentError:
            raise
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
    names = names_of(_model(intended.models) if layer["machines"] else None, layer)
    for mid, m in layer["machines"].items():
        for e in (m.get("expected_effect") or {}).get("edits") or []:
            ok, why = publishable(e, layer, names)
            if not ok:
                open_items.append({"what": "unpublishable draft", "part": "machine", "id": mid, "edit": e, "why": why,
                                   **({"stock": e["stock"]} if e.get("stock") is not None else {})})
    heard = _heard(intended) if layer["machines"] else None
    if heard is not None:
        # C4 (P5) refines this where it derives ``measured``: "attached, nothing measured"
        open_items += [{"what": comparison(False), "part": "machine", "id": mid}
                       for mid, m in layer["machines"].items()
                       if m.get("state") == "declared" and not ({mid, *(m.get("aliases") or [])} & heard)]
    last = [c for e in intended.journal()[-LAST:] for c in e.get("changes", [])][-LAST:]
    return {"version": cur["version"], "elements": _compact(elements), "open": _compact(open_items), "last_changes": last,
            "stabilised": (block or {}).get("stabilised")}


def _compact(rows: list[dict]) -> list[dict]:
    return [{k: v for k, v in r.items() if v is not None} for r in rows]
