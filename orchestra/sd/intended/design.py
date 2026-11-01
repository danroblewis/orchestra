"""``design()`` (§6.3, P4.10): the declared layer in brief for the plugin that keeps it: its version,
each element with its state, presence, link and guessed fields, the open items (unconfirmed
proposals, pending changes, unanswered requests, unsettled suggestions, absent expected parts,
unpublishable drafts with why, and confirmed machines not heard: their ``comparison``; a proposed
one is already open as unconfirmed) and the last 20 changes. Small: under 20 KB for 100 elements,
so a row leaves out a field it has no value for.

Presence is read from the Dynamics comparison: a declared element's by its id, a mark's by its
key. Before any model exists (no saved version, no discovery), a declared stock or effect with
no ``found_as`` is certainly absent. The unsettled suggestions are the comparison's
(``view.unsettled_of``), read from the saved versions' history, whatever the base. A comparison
that fails leaves presence, suggestions and ``stabilised`` unknown and says why
(``comparison_error``), so a broken comparison never reads as nothing open. Every open request
is listed (``requests.open_requests``), not only the latest per element.

Whether a machine is heard is the Machines page's rule (``machines_view.heard_as``: its id or an
alias among the observed machines). ``observed``: the ids the Machines page has observed (the bus
and counted traffic), which the web server gives; without them they are read from Orchestra's
count of the bus (``orchestra_events_total``, by ``source``) under the time limit, for a store
made with its project, so a machine known only by counted traffic is heard only where the web
server's counted read is given. Unknown (past the limit, or neither), no comparison item is
listed."""

from __future__ import annotations

from .checks import IntentError
from .drafts import publishable
from .expected import is_mark
from .facts import LIMIT_S, within
from .keys import Keys
from .machines_view import comparison, heard_as
from .requests import open_requests

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
    got, ok = within(read, LIMIT_S)
    return got if ok else None


def _model(models):
    cached = models.latest_discovery()
    return cached[1] if cached else models.load()


def _presence(block: dict | None) -> dict[tuple[str, str, str], bool]:
    """(part, "id", id) for a declared element's entry, (part, "key", key) for a mark's."""
    out = {}
    for e in (block or {}).get("expected", []):
        out[(e["part"], "key", e.get("key")) if is_mark(e) else (e["part"], "id", e.get("id"))] = e["present"]
    return out


def design(intended, hold: int, block: dict | None = None, observed: set[str] | None = None) -> dict:
    """``block``: the Dynamics comparison to read presence and suggestions from (computed from the
    latest discovery when not given; with no model, presence is unknown except for what cannot
    be there yet). ``hold``: the project's ``announce_hold``. ``observed``: the machine ids the
    Machines page has observed. A ``dN`` that cannot be read raises ``IntentError``."""
    cur = intended.read()
    layer = cur["layer"]
    no_model = not (intended.models.current_version() or intended.models.latest_discovery())
    error = None
    if block is None and not no_model:
        try:
            block = intended.diff(limit_s=0.0, hold=hold)
        except IntentError:
            raise
        except Exception as e:  # noqa: BLE001 - the summary stands without the comparison, and says so
            block, error = None, f"{type(e).__name__}: {e}"
    present = _presence(block)
    elements, absent = [], []
    for part, group in (("stock", "stocks"), ("effect", "effects"), ("flow", "flows"), ("machine", "machines"),
                        ("attachment", "attachments")):
        for eid, el in layer[group].items():
            row = {"part": part, "id": eid, "state": el.get("state")}
            if part in ("stock", "effect", "flow"):
                row["present"] = present.get((part, "id", eid))
            if no_model and part in ("stock", "effect") and not el.get("found_as"):
                row["present"] = False                     # nothing to be found in: certainly absent
                absent.append({"what": "absent expected part", "part": part, "id": eid})
            if el.get("found_as"):
                row["found_as"] = el["found_as"]
            if el.get("guessed"):
                row["guessed"] = el["guessed"]
            if el.get("pending"):
                row["pending"] = [p["change"] for p in el["pending"]]
            elements.append(row)
    for key, mk in layer["marks"]["expected"].items():
        elements.append({"part": mk["part"], "key": key, "state": "expected", "present": present.get((mk["part"], "key", key))})
    open_items = [{"what": "unconfirmed", "part": e["part"], "id": e["id"]} for e in elements if e.get("state") == "proposed"]
    open_items += [{"what": "pending change", "part": e["part"], "id": e["id"], "change": c} for e in elements for c in e.get("pending", [])]
    open_items += [{"what": "unanswered request", "part": r["part"], "id": r["id"], "control": r["control"], "event": r["event"],
                    "change": r.get("change")}
                   for r in open_requests(intended, layer).values()]
    open_items += absent + [{"what": "absent expected part", "part": e["part"], "id": e.get("id"), "key": e.get("key")}
                            for e in (block or {}).get("expected", []) if not e["present"]]
    open_items += [{"what": "unsettled suggestion", "part": s["part"], "key": s["key"]} for s in (block or {}).get("suggestions", [])]
    keys = Keys(_model(intended.models) if layer["machines"] and not no_model else None)
    for mid, m in layer["machines"].items():
        for e in (m.get("expected_effect") or {}).get("edits") or []:
            ok, why = publishable(e, layer, keys)
            if not ok:
                open_items.append({"what": "unpublishable draft", "part": "machine", "id": mid, "edit": e, "why": why,
                                   **({"stock": e["stock"]} if e.get("stock") is not None else {})})
    heard = (observed if observed is not None else _heard(intended)) if layer["machines"] else None
    if heard is not None:
        # C4 (P5) refines this where it derives ``measured``: "attached, nothing measured"
        open_items += [{"what": comparison(False), "part": "machine", "id": mid}
                       for mid, m in layer["machines"].items()
                       if m.get("state") == "declared" and heard_as(mid, m, heard) is None]
    last = [c for e in intended.journal()[-LAST:] for c in e.get("changes", [])][-LAST:]
    out = {"version": cur["version"], "elements": _compact(elements), "open": _compact(open_items), "last_changes": last,
           "stabilised": (block or {}).get("stabilised")}
    if error is not None:
        out["comparison_error"] = error
    return out


def _compact(rows: list[dict]) -> list[dict]:
    return [{k: v for k, v in r.items() if v is not None} for r in rows]
