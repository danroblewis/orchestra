"""The intended model on the web server (docs/proposals/intended-model.md §6): what the Dynamics and
Machines pages read of the declared layer, and the closed list of page controls.

| route | what it is |
|---|---|
| ``GET /api/intended?version=`` | the declared layer at ``dN`` (the current by default) |
| ``GET /api/intended/versions`` | every ``dN``: when, by whom, its changes |
| ``GET /api/intended/journal?after=`` | the accepted calls after a seq |
| ``GET /api/intended/diff?d=&v=&since=`` | the comparison of ``dN`` with ``vM`` against ``vK`` (the Dynamics block) |
| ``GET /api/intended/design`` | the declared layer's summary (``design()``) |
| ``GET /api/intended/script?instrument=`` | an option's script and its ``[[collect]]`` entry, read only inside the repository or the state directory (404 no such entry, 403 a script outside) |
| ``POST /api/intended/control`` | an observation: ``expect``, ``unexpect``, ``ignore``, and ``confirm`` / ``discard`` on a stock, effect or flow; ``ignore`` / ``unignore`` on a machine (``id``, or ``keys``: several at once), hiding it from the Machines page and the Event Map |
| ``POST /api/intended/request`` | a request: ``confirm``, ``discard``, ``switch_kind`` on a machine or an attachment, published as ``orchestra.intent.requested`` from ``owner`` |

An observation records a declaration with ``via: page`` provenance and changes no machine, no
configuration and no discovered version; a request changes nothing until a machine that listens for it (a plugin's)
applies it (AGENTS.md rule 9 as amended). No control carries a value. A refusal is ``{ok: false, error}``
with its status: 400 a bad parameter or body, 403 a path outside the project, 404 not found,
422 an op refused, 500 a version that cannot be read."""

from __future__ import annotations

import shlex
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse

from ..sd.intended import IntentError
from ..sd.intended import requests as owner_requests
from ..sd.intended.controls import MACHINE_MARKS, OBSERVATIONS, PAGE_MARKS, PAGE_PARTS
from ..sd.intended.keys import mark_key
from ..sd.intended.params import integer, saved_version
from ..sd.intended.view import dynamics_block
from ..sd.model import Model
from ..sd.store import ModelStore

BODY = {"control", "part", "id", "key", "keys", "change", "from", "page"}
MAX_KEYS = 1000          # machines hidden in one call ("Hide all of these")


def _refused(e: IntentError) -> JSONResponse:
    out = {"ok": False, "error": str(e)}
    if e.index is not None:
        out["index"] = e.index
    return JSONResponse(out, status_code=e.status)


def observation(body, models, machines=None) -> tuple[list[dict], dict]:
    """A page control's ops and provenance; refuses an attachment, a machine's control other than
    ``ignore`` / ``unignore``, and any value. A mark is stored by key: ``key`` when the page has it
    (a Changes row), else the key of the part with that ``id`` in the latest model; an ``expect``
    or ``ignore`` of a key no latest model has is refused. A machine is marked by its source
    (``id``, or ``keys`` for several at once); ``machines`` (the ids the Machines page lists, None
    while it cannot say) refuses hiding one it does not list."""
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
    prov = {"author": "owner", "control": control, "page": body.get("page") or ("machines" if part == "machine" else "dynamics"),
            **({"from": body["from"]} if body.get("from") else {})}
    if part == "machine" and control in MACHINE_MARKS:
        return machine_marks(body, control, machines), prov
    if body.get("keys") is not None:
        raise IntentError("several at once (keys) are only machines hidden or shown again", status=400)
    if control == "unignore":
        raise IntentError("listing a stock or flow again (unignore) is asked of the Supervisor", status=400)
    if part not in PAGE_PARTS:
        raise IntentError("a page observation is on a stock, an effect or a flow; machines and attachments are requests "
                          "(POST /api/intended/request)", status=400)
    if control in PAGE_MARKS:
        if part == "effect":
            raise IntentError("marks are on discovered stocks and flows", status=400)
        if not body.get("key") and not body.get("id"):
            raise IntentError("a mark names its part's key (or its id in the latest model)", status=400)
        key = mark_key(models, part, body.get("key"), body.get("id"), known=control in ("expect", "ignore"))
        op = {"op": control, "part": part, "key": key}
    else:
        op = {"op": control, "part": part, "id": body.get("id"), **({"change": body["change"]} if body.get("change") else {})}
    return [op], prov


def machine_marks(body: dict, control: str, machines) -> list[dict]:
    """The ops hiding (``ignore``) or showing again (``unignore``) machines by their source: ``id``
    (or ``key``) for one, ``keys`` for several in one change. Hiding a machine the page does not
    list is refused, so a typo leaves no lasting mark."""
    keys = body.get("keys")
    if keys is not None:
        if not isinstance(keys, list) or not keys or len(keys) > MAX_KEYS or \
                not all(isinstance(k, str) and 0 < len(k) <= 1000 for k in keys):
            raise IntentError(f"keys is a list of 1 to {MAX_KEYS} machine ids", status=400)
    else:
        one = body.get("id") or body.get("key")
        if not one:
            raise IntentError("a machine is hidden or shown again by its id", status=400)
        keys = [one]
    keys = list(dict.fromkeys(keys))
    if control == "ignore" and machines is not None and (unknown := [k for k in keys if k not in machines]):
        raise IntentError(f"no machine {', '.join(sorted(unknown)[:5])} on the Machines page", status=400)
    return [{"op": control, "part": "machine", "key": k} for k in keys]


def script_of(project, instrument: str) -> dict:
    """An instrument's ``[[collect]]`` entry (through ``project.config``) and the script its command
    names: the first word that is a file inside the repository or the state directory. A word
    outside them (an interpreter such as ``/bin/sh``, ``/usr/bin/env`` or a virtualenv's Python)
    is passed over; only when no word is inside and some word was a file outside is the call
    refused (403). No such entry is a 404. The configuration is read again if it changed since
    (``config.fresh_config``): a plugin writes entries while the web server runs."""
    from ..config import fresh_config
    from .machine_logs import readable

    fresh_config(project)
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
    try:                     # how each instrument made its series, and what it says of them (collect.views)
        from ..collect.views import declared, tables
        out["model"]["views"] = {name: tables(vs) for name, vs in declared(project).items()}
    except Exception as e:  # noqa: BLE001 - the parts are named without their instruments' words
        out["model"]["views_error"] = f"{type(e).__name__}: {e}"
    try:
        model = Model.from_json(m)
        live = bool(m.get("live"))
        out["model"]["intended"] = dynamics_block(project.intended, model, since,
                                                  version=None if live else m.get("version"), live=live, stamp=m.get("as_of"),
                                                  metrics=metrics, hold=project.config.announce_hold)
        removed_facts(out["model"]["intended"], project.intended.models)
        lend_names(m, out["model"]["intended"])
        out["model"]["subsystems"] = with_subsystems(project, m.get("subsystems") or {}, model)
    except IntentError as e:
        out["model"]["intended"] = {"error": str(e)}
    except Exception as e:  # noqa: BLE001 - the model is shown without its declared layer
        out["model"]["intended"] = {"error": f"{type(e).__name__}: {e}"}


def with_subsystems(project, subs: dict, model) -> dict:
    """The derived partitions with the declared subsystems (``sd.intended.subsystems``), declared
    first; the derived alone when the declared layer cannot be read."""
    from ..sd.intended.subsystems import with_declared
    try:
        layer = project.intended.read()["layer"]
    except Exception:  # noqa: BLE001 - the derived partitions are shown without the declared ones
        return subs
    return with_declared(subs, layer, model)


def machine_subsystems(project, out: dict, model, announced: dict) -> None:
    """``/api/machines``'s ``subsystems`` (web/machine_subsystems.py): the model's partitions, the
    declared first, carried to the machines; then one per announced field. A failure is said in
    ``subsystems_error`` and never breaks the page."""
    from ..sd.subsystems import subsystems as derived
    from .machine_subsystems import subsystems
    try:
        base = model if model is not None else Model("none", "none")
        out["subsystems"] = subsystems(out, with_subsystems(project, derived(base), base), announced)
    except Exception as e:  # noqa: BLE001 - the map is drawn without boxes
        out["subsystems"] = {"default": None, "partitions": []}
        out["subsystems_error"] = f"{type(e).__name__}: {e}"


def lend_names(m: dict, block: dict) -> None:
    """Each stock and flow a declaration names (``block["names"]``, ``sd.intended.display``) carries
    it as ``declared_name``: the pages show it as the part's name, the generated one beneath it."""
    names = (block or {}).get("names") or {}
    for group in ("stocks", "flows"):
        for x in m.get(group) or []:
            if (n := (names.get(group) or {}).get(x.get("id"))) is not None:
                x["declared_name"] = n


def removed_facts(block: dict, models) -> None:
    """What the Changes panel says of a part the base version had and the version shown does not,
    from the base's own record: how it got there (``origin``: a flow's current equation's,
    ``fitted``, ``discovered`` or ``declared``; a stock with evidence was discovered, one without
    declared), its series or counter, and a flow's name, so a removed part is named as the shown
    ones are, never by its id, and one the base named by its places or in words (``named``) by that
    name, never by its series, with its tags (sd.titles)."""
    removed = (block or {}).get("removed") or {}
    if not (removed.get("stocks") or removed.get("flows")) or block.get("since") is None:
        return
    try:
        base = models.load(block["since"])
    except Exception:  # noqa: BLE001 - the rows keep what the comparison gave
        return

    def ref(r):
        return {"name": r.name, "labels": dict(r.labels)} if r is not None else None
    stocks, flows = {s.id: s for s in base.stocks}, {f.id: f for f in base.flows}
    for r in removed.get("stocks") or []:
        s = stocks.get(r.get("id"))
        if s is not None:
            r.update(origin="discovered" if s.evidence else "declared", series=ref(s.series), full_name=s.name,
                     named=bool((s.evidence or {}).get("named")), tags=list((s.evidence or {}).get("tags") or []))
    for r in removed.get("flows") or []:
        f = flows.get(r.get("id"))
        if f is not None:
            eq = f.current()
            r.update(origin=eq.origin if eq is not None else "declared", name=f.name, counter=ref(f.counter),
                     named=bool((f.evidence or {}).get("named")), tags=list((f.evidence or {}).get("tags") or []),
                     from_named=f.src in stocks and bool((stocks[f.src].evidence or {}).get("named")),
                     to_named=f.dst in stocks and bool((stocks[f.dst].evidence or {}).get("named")),
                     measured_by=[ref(c) for c in f.measured_by],
                     from_name=stocks[f.src].name if f.src in stocks else None, to_name=stocks[f.dst].name if f.dst in stocks else None,
                     from_series=ref(stocks[f.src].series) if f.src in stocks else None,
                     to_series=ref(stocks[f.dst].series) if f.dst in stocks else None)


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


def install(app: FastAPI, project, events, metrics, observed=None) -> None:
    """The routes of the table above. ``observed``: what gives the machine ids the Machines page
    has observed (None while it cannot say), so ``design()`` says heard as that page does."""
    def intended():
        return project.intended

    def listed(store) -> set[str] | None:
        """The machines the Machines page lists: observed (``observed``) and declared; None while
        the bus has not been read."""
        seen = observed() if observed else None
        if seen is None:
            return None
        return set(seen) | set(store.read()["layer"]["machines"])

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
            ops, prov = observation(body, store.models, machines=listed(store) if body.get("part") == "machine" else None)
            return {"ok": True, **store.apply(ops, prov, via="page")}
        return await run_in_threadpool(answer, go)     # the file lock off the event loop (rule 8)

    @app.post("/api/intended/request")
    async def intended_request(request: Request):
        try:
            body = await request.json()
        except ValueError:
            return JSONResponse({"ok": False, "error": "the body must be a JSON object"}, status_code=400)
        return await run_in_threadpool(answer, lambda: {"ok": True, "event": owner_requests.publish(intended(), events, body)["id"]})
