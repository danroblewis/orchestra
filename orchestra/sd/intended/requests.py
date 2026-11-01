"""The owner's requests from the pages (§6.2): a machine's or an attachment's ``confirm``,
``discard`` and ``switch_kind`` change nothing; the web server publishes each as
``orchestra.intent.requested`` with ``source`` ``owner`` and ``data`` ``{control, part, id, change,
from}``, and the Supervisor answers by ``apply``-ing with ``provenance.request`` the request's event
id. The web server also notes each one it published in ``requests.jsonl``, so the page can show
"asked the Supervisor · waiting" without reading the bus; a request is answered once a journal
entry names it."""

from __future__ import annotations

import json
import time

from .checks import IntentError

REQUESTED = "orchestra.intent.requested"
OWNER = "owner"
CONTROLS = ("confirm", "discard", "switch_kind")
PARTS = ("machine", "attachment")


def check(body: dict) -> dict:
    if not isinstance(body, dict):
        raise IntentError("the body is an object {control, part, id, change?, from}", status=400)
    if extra := sorted(set(body) - {"control", "part", "id", "change", "from"}):
        raise IntentError(f"a request carries no values: {', '.join(extra)} refused", status=400)
    if body.get("control") not in CONTROLS:
        raise IntentError(f"a request's control is one of {', '.join(CONTROLS)}", status=400)
    if body.get("part") not in PARTS:
        raise IntentError("requests are about a machine or an attachment; the rest are observations", status=400)
    if not isinstance(body.get("id"), str) or not body["id"]:
        raise IntentError("id names the machine or attachment", status=400)
    return {"control": body["control"], "part": body["part"], "id": body["id"], "change": body.get("change"),
            "from": body.get("from")}


def publish(intended, events, body: dict) -> dict:
    """Publish one request as the owner and note it; returns the event."""
    data = check(body)
    ev = events.publish(REQUESTED, data, source=OWNER, subject=f"{data['part']}:{data['id']}")
    intended.dir.mkdir(parents=True, exist_ok=True)
    with open(intended.dir / "requests.jsonl", "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"event": ev["id"], "at": time.time(), **data}) + "\n")
    return ev


def noted(intended) -> list[dict]:
    try:
        lines = (intended.dir / "requests.jsonl").read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out = []
    for line in lines:
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def unanswered(intended) -> dict[tuple[str, str], dict]:
    """The latest request per (part, id) that no later op answers."""
    answered = {(e.get("provenance") or {}).get("request") for e in intended.journal()}
    latest: dict[tuple[str, str], dict] = {}
    for r in noted(intended):
        latest[(r["part"], r["id"])] = r
    return {k: r for k, r in latest.items() if r["event"] not in answered}
