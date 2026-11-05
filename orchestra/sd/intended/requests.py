"""The owner's requests from the pages (§6.2): a machine's or an attachment's ``confirm``,
``discard`` and ``switch_kind`` change nothing; the web server publishes each as
``orchestra.intent.requested`` with ``source`` ``owner`` and ``data`` ``{control, part, id, change,
from}``, and the machine that listens for it (a plugin's) answers by ``apply``-ing with ``provenance.request`` the request's event
id. The web server notes each request in ``requests.jsonl`` before it publishes it (the event's id
chosen first), so a plugin answering at once finds it open, and the page can show "asked <machine> ·
waiting" without reading the bus; a request whose publish failed is taken out again.

A request is answered once an accepted call's op answered it (the journal line's ``answered``,
filled by ``consent.verified``), not merely cited it. It stays open only while it can still be
acted on: its element is in the layer, its ``change`` (when it names one) is still pending, and a
``confirm`` or ``discard`` naming no change is of an element still proposed. A request names
something declared (a machine or attachment in the layer, and for ``change`` one of its pending
changes; a ``confirm`` or ``discard`` with no change, a proposed one) and carries no values
(AGENTS.md rule 9 as amended)."""

from __future__ import annotations

import time
import uuid

from . import lines
from .checks import IntentError, text
from .consent import by_standing
from .ops import GROUP

REQUESTED = "orchestra.intent.requested"
OWNER = "owner"
CONTROLS = ("confirm", "discard", "switch_kind")
PARTS = ("machine", "attachment")
SETTLES = ("confirm", "discard")


def listens(t: str) -> bool:
    """Whether a type a machine announced it listens for takes in an owner's request."""
    return t in (REQUESTED, "*", "orchestra.*") or (t.endswith(".*") and REQUESTED.startswith(t[:-1]))


def askers(machines: list[dict]) -> list[str]:
    """The machines (as the Machines page lists them) that listen for the owner's requests: who a
    page names when it says to ask, the same rule as the pages' (static/intended-core.js). A
    placeholder a plugin declared but the bus has not heard (``unseen``) is not one: nothing on
    the bus listens yet."""
    return sorted(m["id"] for m in machines if not m.get("unseen") and any(listens(t) for t in m.get("subscribes") or ()))


def check(body: dict) -> dict:
    if not isinstance(body, dict):
        raise IntentError("the body is an object {control, part, id, change?, from}", status=400)
    if extra := sorted(set(body) - {"control", "part", "id", "change", "from"}):
        raise IntentError(f"a request carries no values: {', '.join(extra)} refused", status=400)
    if body.get("control") not in CONTROLS:
        raise IntentError(f"a request's control is one of {', '.join(CONTROLS)}", status=400)
    if body.get("part") not in PARTS:
        raise IntentError("requests are about a machine or an attachment; the rest are observations", status=400)
    if body["control"] == "switch_kind" and body["part"] != "machine":
        raise IntentError("switch_kind is a machine's (Universal | Programmatic)", status=400)
    if not isinstance(body.get("id"), str) or not body["id"]:
        raise IntentError("id names the machine or attachment", status=400)
    try:
        text(body["id"], "id", limit=200)
        change = text(body.get("change"), "change", limit=40)
        origin = text(body.get("from"), "from", limit=200)
    except IntentError as e:
        raise IntentError(str(e), status=400) from None
    return {"control": body["control"], "part": body["part"], "id": body["id"], "change": change, "from": origin}


def named(intended, data: dict) -> None:
    """The request's machine or attachment is in the declared layer, its change pending there, and
    a confirm or discard naming no change is of a proposed element (409 otherwise), except the
    discard of one its author confirmed under the owner's standing consent (``consent.by_standing``)."""
    el = intended.read()["layer"][GROUP[data["part"]]].get(data["id"])
    if el is None:
        raise IntentError(f"there is no declared {data['part']} {data['id']!r}", status=404)
    if data["change"] is not None and data["change"] not in {p.get("change") for p in el.get("pending") or []}:
        raise IntentError(f"{data['part']} {data['id']} has no pending change {data['change']}", status=404)
    if data["change"] is None and data["control"] in SETTLES and el.get("state") != "proposed" \
            and not (data["control"] == "discard" and by_standing(el)):
        raise IntentError(f"{data['part']} {data['id']} is {el.get('state')}, not proposed: there is nothing to {data['control']}",
                          status=409)


def _file(intended):
    return intended.dir / "requests.jsonl"


def publish(intended, events, body: dict) -> dict:
    """Note one request, then publish it as the owner; returns the event. A publish that fails
    takes the note out again."""
    from .store import LOCK

    data = check(body)
    named(intended, data)
    eid = uuid.uuid4().hex
    with intended.models.locked(LOCK):
        lines.append(_file(intended), {"event": eid, "at": time.time(), **data})
    try:
        return events.publish(REQUESTED, data, source=OWNER, subject=f"{data['part']}:{data['id']}", id=eid)
    except BaseException:
        with intended.models.locked(LOCK):
            lines.rewrite(_file(intended), lambda r: r.get("event") != eid)
        raise


def noted(intended) -> list[dict]:
    return [r for r in lines.records(_file(intended)) if r.get("event")]


def _answered(intended) -> set:
    return {rid for e in intended.journal() for rid in e.get("answered") or []}


def actionable(r: dict, layer: dict) -> bool:
    """Whether a request can still be acted on in ``layer``."""
    el = layer.get(GROUP.get(r.get("part"), ""), {}).get(r.get("id"))
    if el is None:
        return False
    if r.get("change"):
        return r["change"] in {p.get("change") for p in el.get("pending") or []}
    return r.get("control") not in SETTLES or el.get("state") == "proposed" or (r.get("control") == "discard" and by_standing(el))


def open_requests(intended, layer: dict | None = None) -> dict[str, dict]:
    """Every noted request no accepted call has answered and that can still be acted on, by its
    event id, oldest first: what a call's ``provenance.request`` may cite (``consent.verified``).
    ``layer``: the declared layer to judge by (the current one by default)."""
    answered = _answered(intended)
    layer = intended.read()["layer"] if layer is None else layer
    return {r["event"]: r for r in noted(intended) if r["event"] not in answered and actionable(r, layer)}


def unanswered(intended, layer: dict | None = None) -> dict[tuple[str, str], dict]:
    """The latest open request per (part, id): what the page shows as ``requested``."""
    latest: dict[tuple[str, str], dict] = {}
    for r in open_requests(intended, layer).values():
        latest[(r["part"], r["id"])] = r
    return latest
