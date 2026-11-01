"""The intended model on the web server (docs/proposals/intended-model.md §6): what the Dynamics and
Machines pages read of the declared layer, and the closed list of page controls.

| route | what it is |
|---|---|
| ``GET /api/intended?version=`` | the declared layer at ``dN`` (the current by default) |
| ``GET /api/intended/versions`` | every ``dN``: when, by whom, its changes |
| ``GET /api/intended/journal?after=`` | the accepted calls after a seq |
| ``GET /api/intended/diff?d=&v=&since=`` | the comparison of ``dN`` with ``vM`` against ``vK`` (the Dynamics block) |
| ``GET /api/intended/design`` | the plugin's summary (``design()``) |
| ``GET /api/intended/script?instrument=`` | an option's script and its ``[[collect]]`` entry, read only inside the repository or the state directory (404 no such entry, 403 a script outside) |
| ``POST /api/intended/control`` | an observation: ``expect``, ``unexpect``, ``ignore``, and ``confirm`` / ``discard`` on a stock, effect or flow |
| ``POST /api/intended/request`` | a request: ``confirm``, ``discard``, ``switch_kind`` on a machine or an attachment, published as ``orchestra.intent.requested`` from ``owner`` |

An observation records a declaration with ``via: page`` provenance and changes no machine, no
configuration and no discovered version; a request changes nothing until the Supervisor applies
it (AGENTS.md rule 9 as amended). No control carries a value. A refusal is ``{ok: false, error}``
with its status: 400 a bad parameter or body, 403 a path outside the project, 404 not found,
422 an op refused, 500 a version that cannot be read."""

from __future__ import annotations

import shlex
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from ..sd.intended import IntentError
from ..sd.intended import requests as owner_requests
from ..sd.intended.keys import mark_key
from ..sd.intended.params import integer, saved_version
from ..sd.intended.view import dynamics_block
from ..sd.model import Model
from ..sd.store import ModelStore

OBSERVATIONS = ("expect", "unexpect", "ignore", "confirm", "discard")      # rule 9 as amended: the closed list
MARKS = ("expect", "unexpect", "ignore")
LEVELS = ("stock", "effect", "flow")
BODY = {"control", "part", "id", "key", "change", "from", "page"}


def _refused(e: IntentError) -> JSONResponse:
    out = {"ok": False, "error": str(e)}
    if e.index is not None:
        out["index"] = e.index
    return JSONResponse(out, status_code=e.status)


def observation(body, models) -> tuple[dict, dict]:
    """A page control's op and provenance; refuses a machine or attachment, and any value. A mark
    is stored by key: ``key`` when the page has it (a Changes row), else the key of the part
    with that ``id`` in the latest model; an ``expect`` or ``ignore`` of a key no latest model has
    is refused."""
    if not isinstance(body, dict):
        raise IntentError("the body is an object {control, part, id, change?, from}", status=400)
    if extra := sorted(set(body) - BODY):
        raise IntentError(f"a page control carries no values: {', '.join(extra)} refused", status=400)
    for k in ("id", "key", "change", "from", "page"):
        if body.get(k) is not None and (not isinstance(body[k], str) or len(body[k]) > 1000):
            raise IntentError(f"{k} is a string of at most 1000 characters", status=400)
    control, part = body.get("control"), body.get("part")
    if control not in OBSERVATIONS:
        raise IntentError(f"control is one of {', '.join(OBSERVATIONS)}; a machine's confirm and discard are requests", status=400)
    if part not in LEVELS:
        raise IntentError("a page observation is on a stock, an effect or a flow; machines and attachments are requests "
                          "(POST /api/intended/request)", status=400)
    if control in MARKS:
        if part == "effect":
            raise IntentError("marks are on discovered stocks and flows", status=400)
        if not body.get("key") and not body.get("id"):
            raise IntentError("a mark names its part's key (or its id in the latest model)", status=400)
        key = mark_key(models, part, body.get("key"), body.get("id"), known=control in ("expect", "ignore"))
        op = {"op": control, "part": part, "key": key}
    else:
        op = {"op": control, "part": part, "id": body.get("id"), **({"change": body["change"]} if body.get("change") else {})}
    prov = {"author": "owner", "control": control, "page": body.get("page") or "dynamics",
            **({"from": body["from"]} if body.get("from") else {})}
    return op, prov


def script_of(project, instrument: str) -> dict:
    """An instrument's ``[[collect]]`` entry (through ``project.config``) and the script its command
    names: the first word that is a file inside the repository or the state directory. A word
    outside them (an interpreter such as ``/bin/sh``, ``/usr/bin/env`` or a virtualenv's Python)
    is passed over; only when no word is inside and some word was a file outside is the call
    refused (403). No such entry is a 404."""
    from .machine_logs import readable

    entry = next((e for e in project.config.raw.get("collect") or [] if isinstance(e, dict) and e.get("name") == instrument), None)
    if entry is None:
        raise IntentError(f"there is no [[collect]] entry named {instrument}", status=404)
    cmd = entry.get("command")
    words = list(cmd) if isinstance(cmd, list) else shlex.split(str(cmd or ""))
    roots = [project.repo_root, project.state_dir]
    out = {"ok": True, "instrument": instrument, "entry": entry, "script": None}
    outside = None
    for w in words:
        p = Path(str(w)).expanduser()
        p = p if p.is_absolute() else project.repo_root / p
        if not p.is_file():
            continue
        path, why = readable(str(p), roots)
        if path is None:
            outside = outside or why
            continue
        out["script"] = {"path": str(path), "text": path.read_text(encoding="utf-8", errors="replace")[:200_000]}
        return out
    if outside is not None:
        raise IntentError(outside, status=403)
    return out


def attach_dynamics(project, out: dict, since, metrics) -> None:
    """Add ``model.intended`` to a ``/api/dynamics/model`` answer; a failure is said there and
    never breaks the page."""
    m = out.get("model") or {}
    try:
        model = Model.from_json(m)
        live = bool(m.get("live"))
        out["model"]["intended"] = dynamics_block(project.intended, model, since,
                                                  version=None if live else m.get("version"), live=live, stamp=m.get("as_of"),
                                                  metrics=metrics, hold=project.config.announce_hold)
    except IntentError as e:
        out["model"]["intended"] = {"error": str(e)}
    except Exception as e:  # noqa: BLE001 - the model is shown without its declared layer
        out["model"]["intended"] = {"error": f"{type(e).__name__}: {e}"}


def attach_machines(project, out: dict, model) -> None:
    from ..sd import predictions as prediction_record
    from ..sd.intended.machines_view import merge

    store = ModelStore.for_state(project.state_dir)
    try:
        merge(out, store.intended(), model, prediction_record.recorded(store))
    except Exception as e:  # noqa: BLE001 - the observed machines are shown without the declared layer
        out["intended_error"] = f"{type(e).__name__}: {e}"


def install(app: FastAPI, project, events, metrics, observed=None) -> None:
    """The routes of the table above. ``observed``: what gives the machine ids the Machines page
    has observed (None while it cannot say), so ``design()`` says heard as that page does."""
    def intended():
        return project.intended

    def answer(fn):
        try:
            return fn()
        except IntentError as e:
            return _refused(e)

    @app.get("/api/intended")
    def intended_read(version: str | None = None):
        return answer(lambda: {"ok": True, **intended().read(integer(version, "version"))})

    @app.get("/api/intended/versions")
    def intended_versions():
        return {"ok": True, "versions": intended().versions()}

    @app.get("/api/intended/journal")
    def intended_journal(after: str | None = None):
        return answer(lambda: {"ok": True, "journal": intended().journal(integer(after, "after") or 0)})

    @app.get("/api/intended/diff")
    def intended_diff(d: str | None = None, v: str | None = None, since: str | None = None):
        def go():
            store = intended()
            d_ = integer(d, "d")
            if v in (None, "", "live"):
                return {"ok": True, **store.diff(None, since, d=d_, metrics=metrics, hold=project.config.announce_hold)}
            n = saved_version(v, [x["version"] for x in store.models.versions()], "v")
            model = store.models.load(n)
            if model is None:
                raise IntentError(f"v{n} cannot be read", status=500)
            return {"ok": True, **dynamics_block(store, model, since, version=n, live=False, metrics=metrics, d=d_,
                                                 hold=project.config.announce_hold)}
        return answer(go)

    @app.get("/api/intended/design")
    def intended_design():
        return answer(lambda: {"ok": True, **intended().design(observed=observed() if observed else None)})

    @app.get("/api/intended/script")
    def intended_script(instrument: str):
        return answer(lambda: script_of(project, instrument))

    @app.post("/api/intended/control")
    async def intended_control(request: Request):
        try:
            body = await request.json()
        except ValueError:
            return JSONResponse({"ok": False, "error": "the body must be a JSON object"}, status_code=400)

        def go():
            store = intended()
            op, prov = observation(body, store.models)
            return {"ok": True, **store.apply([op], prov, via="page")}
        return answer(go)

    @app.post("/api/intended/request")
    async def intended_request(request: Request):
        try:
            body = await request.json()
        except ValueError:
            return JSONResponse({"ok": False, "error": "the body must be a JSON object"}, status_code=400)
        return answer(lambda: {"ok": True, "event": owner_requests.publish(intended(), events, body)["id"]})
