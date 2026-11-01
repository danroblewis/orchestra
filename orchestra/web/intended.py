"""The intended model on the web server (docs/proposals/intended-model.md §6): what the Dynamics and
Machines pages read of the declared layer, and the closed list of page controls.

| route | what it is |
|---|---|
| ``GET /api/intended?version=`` | the declared layer at ``dN`` (the current by default) |
| ``GET /api/intended/versions`` | every ``dN``: when, by whom, its changes |
| ``GET /api/intended/journal?after=`` | the accepted calls after a seq |
| ``GET /api/intended/diff?d=&v=&since=`` | the comparison of ``dN`` with ``vM`` against ``vK`` (the Dynamics block) |
| ``GET /api/intended/design`` | the plugin's summary (``design()``) |
| ``GET /api/intended/script?instrument=`` | an option's script and its ``[[collect]]`` entry, read only inside the repository or the state directory |
| ``POST /api/intended/control`` | an observation: ``expect``, ``unexpect``, ``ignore``, and ``confirm`` / ``discard`` on a stock, effect or flow |
| ``POST /api/intended/request`` | a request: ``confirm``, ``discard``, ``switch_kind`` on a machine or an attachment, published as ``orchestra.intent.requested`` from ``owner`` |

An observation records a declaration with ``via: page`` provenance and changes no machine, no
configuration and no discovered version; a request changes nothing until the Supervisor applies
it (AGENTS.md rule 9 as amended). No control carries a value."""

from __future__ import annotations

import shlex
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from ..sd.intended import IntentError
from ..sd.intended import requests as owner_requests
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


def observation(body) -> tuple[dict, dict]:
    """A page control's op and provenance; refuses a machine or attachment, and any value."""
    if not isinstance(body, dict):
        raise IntentError("the body is an object {control, part, id, change?, from}", status=400)
    if extra := sorted(set(body) - BODY):
        raise IntentError(f"a page control carries no values: {', '.join(extra)} refused", status=400)
    control, part = body.get("control"), body.get("part")
    if control not in OBSERVATIONS:
        raise IntentError(f"control is one of {', '.join(OBSERVATIONS)}; a machine's confirm and discard are requests", status=400)
    if part not in LEVELS:
        raise IntentError("a page observation is on a stock, an effect or a flow; machines and attachments are requests "
                          "(POST /api/intended/request)", status=400)
    if control in MARKS:
        if part == "effect":
            raise IntentError("marks are on discovered stocks and flows", status=400)
        op = {"op": control, "part": part, "key": body.get("key") or body.get("id")}
    else:
        op = {"op": control, "part": part, "id": body.get("id"), **({"change": body["change"]} if body.get("change") else {})}
    prov = {"author": "owner", "via": "page", "control": control, "page": body.get("page") or "dynamics",
            **({"from": body["from"]} if body.get("from") else {})}
    return op, prov


def script_of(project, instrument: str) -> dict:
    """An instrument's ``[[collect]]`` entry (through ``project.config``) and the script its command
    names, read only when it lies inside the repository or the state directory."""
    from .machine_logs import readable

    entry = next((e for e in project.config.raw.get("collect") or [] if isinstance(e, dict) and e.get("name") == instrument), None)
    if entry is None:
        return {"ok": False, "error": f"there is no [[collect]] entry named {instrument}"}
    cmd = entry.get("command")
    words = list(cmd) if isinstance(cmd, list) else shlex.split(str(cmd or ""))
    roots = [project.repo_root, project.state_dir]
    out = {"ok": True, "instrument": instrument, "entry": entry, "script": None}
    for w in words:
        p = Path(w).expanduser()
        p = p if p.is_absolute() else project.repo_root / p
        if not p.exists() or not p.is_file():
            continue
        path, why = readable(str(p), roots)
        if path is None:
            return {**out, "ok": False, "error": why}
        out["script"] = {"path": str(path), "text": path.read_text(encoding="utf-8", errors="replace")[:200_000]}
        break
    return out


def attach_dynamics(project, out: dict, since, metrics) -> None:
    """Add ``model.intended`` to a ``/api/dynamics/model`` answer; a failure is said there and
    never breaks the page."""
    m = out.get("model") or {}
    try:
        model = Model.from_json(m)
        live = bool(m.get("live"))
        out["model"]["intended"] = dynamics_block(ModelStore.for_state(project.state_dir).intended(), model, since,
                                                  version=None if live else m.get("version"), live=live, stamp=m.get("as_of"),
                                                  metrics=metrics, hold=project.config.announce_hold)
    except IntentError as e:
        out["model"]["intended"] = {"error": str(e)}
    except Exception as e:  # noqa: BLE001 - the model is shown without its declared layer
        out["model"]["intended"] = {"error": f"{type(e).__name__}: {e}"}


def attach_machines(project, out: dict, model, measured: dict | None = None) -> None:
    """The declared machines (``machines_view.merge``), and on each what its attached instruments
    measure (``measured.merge_machines``, from the background read ``measured``)."""
    from ..sd import predictions as prediction_record
    from ..sd.intended.machines_view import merge
    from .measured import merge_machines

    store = ModelStore.for_state(project.state_dir)
    try:
        intended = store.intended()
        merge(out, intended, model, prediction_record.recorded(store))
        merge_machines(out, project, intended.read()["layer"], measured)
    except Exception as e:  # noqa: BLE001 - the observed machines are shown without the declared layer
        out["intended_error"] = f"{type(e).__name__}: {e}"


def install(app: FastAPI, project, events, metrics) -> None:
    """The routes of the table above."""
    def intended():
        return ModelStore.for_state(project.state_dir).intended()

    def answer(fn):
        try:
            return fn()
        except IntentError as e:
            return _refused(e)

    @app.get("/api/intended")
    def intended_read(version: int | None = None):
        return answer(lambda: {"ok": True, **intended().read(version)})

    @app.get("/api/intended/versions")
    def intended_versions():
        return {"ok": True, "versions": intended().versions()}

    @app.get("/api/intended/journal")
    def intended_journal(after: int = 0):
        return {"ok": True, "journal": intended().journal(after)}

    @app.get("/api/intended/diff")
    def intended_diff(d: int | None = None, v: str | None = None, since: str | None = None):
        def go():
            store = intended()
            if v in (None, "", "live"):
                return {"ok": True, **store.diff(None, since, d=d, metrics=metrics, hold=project.config.announce_hold)}
            model = store.models.load(int(v))
            if model is None:
                raise IntentError(f"there is no version {v}", status=404)
            return {"ok": True, **dynamics_block(store, model, since, version=int(v), live=False, metrics=metrics, d=d,
                                                 hold=project.config.announce_hold)}
        return answer(go)

    @app.get("/api/intended/design")
    def intended_design():
        return {"ok": True, **intended().design()}

    @app.get("/api/intended/script")
    def intended_script(instrument: str):
        return script_of(project, instrument)

    @app.post("/api/intended/control")
    async def intended_control(request: Request):
        try:
            body = await request.json()
        except ValueError:
            return JSONResponse({"ok": False, "error": "the body must be a JSON object"}, status_code=400)

        def go():
            op, prov = observation(body)
            return {"ok": True, **intended().apply([op], prov, via="page")}
        return answer(go)

    @app.post("/api/intended/request")
    async def intended_request(request: Request):
        try:
            body = await request.json()
        except ValueError:
            return JSONResponse({"ok": False, "error": "the body must be a JSON object"}, status_code=400)
        return answer(lambda: {"ok": True, "event": owner_requests.publish(intended(), events, body)["id"]})
