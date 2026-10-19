"""SD Lab server: stores models as JSON files and serves the editor.

The examples in ``sdlab/examples/`` are read-only: they always open as shipped. The user's own
models live in ``$SDLAB_HOME/models/<id>.json`` (default ``~/.sdlab``); a copy of an example
(made when it is first edited, or with "Save as") is one of them. Runs live in
``$SDLAB_HOME/runs/<id>/``, examples' included."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Response
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from . import basics
from .discovery.strategies import names as strategy_names
from .discovery_jobs import DiscoveryJobs
from .ladder.analysis_routes import router as analysis_router
from .ladder.routes import router as ladder_router
from .research import router as research_router
from .runner import LiveRun, available_programs, program_path

HERE = Path(__file__).parent
EXAMPLES = HERE / "examples"
STATIC = HERE / "static"
ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
RATE_FORMS = {"constant", "proportional", "gap", "available", "linear"}
MACHINE_KINDS = {"code", "agent", "person"}


def home() -> Path:
    return Path(os.environ.get("SDLAB_HOME", Path.home() / ".sdlab"))


def models_dir() -> Path:
    d = home() / "models"
    d.mkdir(parents=True, exist_ok=True)
    return d


def is_example(model_id: str) -> bool:
    return bool(ID_RE.match(model_id)) and (EXAMPLES / f"{model_id}.json").exists()


def unique_id(base: str) -> str:
    """A free model id made from a name: lower case, letters, digits, dashes."""
    slug = re.sub(r"[^a-z0-9]+", "-", base.lower()).strip("-")[:56] or "model"
    if not slug[0].isalnum():
        slug = "m" + slug
    taken = {p.stem for p in models_dir().glob("*.json")} | {p.stem for p in EXAMPLES.glob("*.json")}
    mid, n = slug, 2
    while mid in taken:
        mid, n = f"{slug}-{n}", n + 1
    return mid


def copy_run(src: str, dst: str) -> None:
    a, b = home() / "runs" / src, home() / "runs" / dst
    if a.is_dir() and not b.exists():
        shutil.copytree(a, b)


def adopt_old_copies() -> None:
    """Servers before examples were read-only copied the examples into the models folder and saved
    edits over them. An untouched copy is dropped; an edited one becomes the user's own model."""
    for ex in EXAMPLES.glob("*.json"):
        old = models_dir() / ex.name
        if not old.exists():
            continue
        try:
            mine, shipped = json.loads(old.read_text()), json.loads(ex.read_text())
        except ValueError:
            continue
        if {**mine, "id": shipped.get("id")} != shipped:
            mid = unique_id(f"{ex.stem}-edited")
            mine.update(id=mid, name=f"{mine.get('name') or ex.stem} (edited)")
            (models_dir() / f"{mid}.json").write_text(json.dumps(mine, indent=2))
            run = home() / "runs" / ex.stem
            if run.is_dir() and not (home() / "runs" / mid).exists():
                run.rename(home() / "runs" / mid)                # the run was of the edited model: it goes with it
        old.unlink()


def validate(model: dict[str, Any]) -> list[str]:
    """Structural problems with a model; an empty list means it can be saved."""
    errs: list[str] = []
    stocks = model.get("stocks", [])
    flows = model.get("flows", [])
    machines = model.get("machines", [])
    ids: set[str] = set()
    for kind, items in (("stock", stocks), ("flow", flows), ("machine", machines)):
        for it in items:
            i = it.get("id")
            if not isinstance(i, str) or not i:
                errs.append(f"a {kind} has no id")
            elif i in ids:
                errs.append(f"id {i!r} is used twice")
            ids.add(i)
    stock_ids = {s.get("id") for s in stocks}
    machine_ids = {m.get("id") for m in machines}
    for m in machines:
        if m.get("kind") not in MACHINE_KINDS:
            errs.append(f"machine {m.get('id')!r}: kind must be one of {sorted(MACHINE_KINDS)}")
    for f in flows:
        fid = f.get("id")
        for end in ("from", "to"):
            v = f.get(end)
            if v is not None and v not in stock_ids:
                errs.append(f"flow {fid!r}: {end} names no stock ({v!r})")
        if f.get("from") is None and f.get("to") is None:
            errs.append(f"flow {fid!r} connects nothing")
        rate = f.get("rate") or {}
        if rate.get("form") not in RATE_FORMS:
            errs.append(f"flow {fid!r}: rate form must be one of {sorted(RATE_FORMS)}")
        if rate.get("form") in ("proportional", "gap") and rate.get("stock") not in stock_ids:
            errs.append(f"flow {fid!r}: its equation reads no stock")
        mach = f.get("machine")
        if mach not in (None, "environment") and mach not in machine_ids:
            errs.append(f"flow {fid!r}: machine {mach!r} does not exist")
        for o in f.get("outputs") or []:
            if o not in stock_ids:
                errs.append(f"flow {fid!r}: output {o!r} names no stock")
        names: set[str] = set()
        for inp in f.get("take") or []:
            if inp.get("from") not in stock_ids:
                errs.append(f"flow {fid!r}: input {inp.get('as')!r} takes from no stock")
            if not inp.get("as") or inp["as"] in names:
                errs.append(f"flow {fid!r}: every input needs its own name ('as')")
            names.add(inp.get("as"))
            if inp.get("order", "any") not in ("any", "oldest", "newest"):
                errs.append(f"flow {fid!r}: order is any, oldest or newest")
        for key in ("args",):
            if f.get(key) is not None and not (isinstance(f[key], list) and all(isinstance(a, str) for a in f[key])):
                errs.append(f"flow {fid!r}: {key} must be a list of strings")
        if f.get("program") and program_path(EXAMPLES, f["program"]) is None:
            errs.append(f"flow {fid!r}: no program {f['program']!r}")
    for f in flows:
        for e in f.get("effects") or []:
            if e.get("stock") not in stock_ids:
                errs.append(f"flow {f.get('id')!r}: an effect reads no stock ({e.get('stock')!r})")
            if e.get("shape", "linear") not in ("linear", "table"):
                errs.append(f"flow {f.get('id')!r}: an effect's shape is linear or table")
        for u in f.get("uses") or []:
            if u.get("stock") not in stock_ids:
                errs.append(f"flow {f.get('id')!r}: it uses no stock ({u.get('stock')!r})")
    for sensor in [*(model.get("sensors") or []), *([model["history"]] if model.get("history") else [])]:
        if program_path(EXAMPLES, sensor.get("program", "")) is None:
            errs.append(f"no sensor or history program {sensor.get('program')!r}")
    for m in machines:
        if m.get("capacity_stock") and m["capacity_stock"] not in stock_ids:
            errs.append(f"machine {m.get('id')!r}: its capacity is per unit of no stock ({m['capacity_stock']!r})")
        if m.get("program") and program_path(EXAMPLES, m["program"]) is None:
            errs.append(f"machine {m.get('id')!r}: no program {m['program']!r}")
        if m.get("args") is not None and not (isinstance(m["args"], list) and all(isinstance(a, str) for a in m["args"])):
            errs.append(f"machine {m.get('id')!r}: args must be a list of strings")
    return errs


def create_app() -> FastAPI:
    adopt_old_copies()
    runs: dict[str, LiveRun] = {}
    jobs = DiscoveryJobs()

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        yield
        for r in runs.values():
            r.stop()
        jobs.close()

    app = FastAPI(title="SD Lab", lifespan=lifespan)
    app.add_middleware(GZipMiddleware, minimum_size=64 * 1024)      # the ladder's summary is megabytes of JSON

    def live(model_id: str) -> LiveRun:
        p = _path(model_id)
        if model_id not in runs:
            runs[model_id] = LiveRun(model_id, p, home() / "runs" / model_id, EXAMPLES)
        return runs[model_id]

    @app.get("/api/programs")
    def programs() -> dict:
        return {"programs": available_programs(EXAMPLES)}

    # A basic model (a ladder case, basics.py) plays back its recorded data in one variant; it never runs.
    @app.get("/api/models/{model_id}/live")
    def live_state(model_id: str, since: int = 0, variant: str | None = None) -> dict:
        if basics.is_basic(model_id):
            return basics.snapshot(model_id, variant, since)
        return live(model_id).snapshot(since)

    @app.post("/api/models/{model_id}/live/{action}")
    def live_control(model_id: str, action: str, body: dict[str, Any] | None = None) -> dict:
        if basics.is_basic(model_id):
            raise HTTPException(409, "a basic model plays back its recorded data: it does not run")
        run = live(model_id)
        if action == "start":
            run.start((body or {}).get("seconds_per_tick"))
        elif action == "stop":
            run.stop()
        elif action == "reset":
            run.reset()
        elif action == "step":
            run.tick()
        elif action == "import":
            try:
                run.import_history()
            except ValueError as e:
                raise HTTPException(422, str(e))
        else:
            raise HTTPException(404, "unknown action")
        return run.snapshot(0)

    @app.get("/api/models/{model_id}/live/firings/{n}")
    def live_firing(model_id: str, n: int) -> dict:
        rec = None if basics.is_basic(model_id) else live(model_id).firing(n)
        if rec is None:
            raise HTTPException(404, "that firing is no longer kept; only the most recent 60 are")
        return rec
        rec = live(model_id).firing(n)
        if rec is None:
            raise HTTPException(404, "that firing is no longer kept; only the most recent 60 are")
        return rec

    @app.get("/api/models/{model_id}/live/stocks/{stock_id}")
    def live_items(model_id: str, stock_id: str) -> dict:
        if basics.is_basic(model_id):
            return {"count": 0, "items": []}
        return live(model_id).stock_items(stock_id)

    # Discovery runs as a background job per model (discovery_jobs.py): the page posts what it
    # measured, then waits for the job; a newer request supersedes an older one.
    @app.get("/api/discovery/strategies")
    def discovery_strategies() -> dict:
        return {"strategies": strategy_names(), "default": "matrix"}

    @app.post("/api/models/{model_id}/discovery")
    def start_discovery(model_id: str, body: dict[str, Any]) -> dict:
        _known(model_id)
        req = check_discovery_request(body)
        return jobs.submit(model_id, req).view(with_result=False)

    @app.get("/api/models/{model_id}/discovery")
    async def discovery_status(model_id: str, job: int | None = None, wait: float = 0) -> dict:
        _known(model_id)
        if wait > 0:
            return await jobs.wait(model_id, job, min(wait, 30.0))
        return jobs.status(model_id, job)

    @app.delete("/api/models/{model_id}/discovery")
    def cancel_discovery(model_id: str) -> dict:
        _known(model_id)
        return jobs.cancel(model_id)


    @app.get("/api/models")
    def list_models() -> dict:
        def listing(folder: Path) -> list[dict]:
            out = []
            for p in sorted(folder.glob("*.json")):
                try:
                    m = json.loads(p.read_text())
                except ValueError:
                    continue
                row = {"id": p.stem, "name": m.get("name", p.stem), "modified": int(p.stat().st_mtime)}
                r = runs.get(p.stem)
                if r is not None and r.running:                   # running now: the page marks it
                    row.update(running=True, t=r.t)
                out.append(row)
            return out
        return {"basics": basics.listing(), "examples": listing(EXAMPLES), "models": [m for m in listing(models_dir()) if not is_example(m["id"])]}

    # Hidden flows stand for parts of the real system nobody has modelled: the runner runs them,
    # but the page never receives them, and saving the page's model keeps them as they were.
    @app.get("/api/models/{model_id}")
    def get_model(model_id: str, reveal: bool = False) -> dict:
        if basics.is_basic(model_id):
            return {**basics.model(model_id), "example": True}
        m = json.loads(_path(model_id).read_text())
        m["example"] = is_example(model_id)
        if not reveal:
            m["flows"] = [f for f in m.get("flows", []) if not f.get("hidden")]
        return m

    @app.put("/api/models/{model_id}")
    def put_model(model_id: str, model: dict[str, Any]) -> dict:
        if is_example(model_id) or basics.is_basic(model_id):
            raise HTTPException(409, "examples are read-only: save a copy")
        p = _path(model_id, must_exist=False)
        model["id"] = model_id
        model.pop("example", None)
        if p.exists():
            kept = [f for f in json.loads(p.read_text()).get("flows", []) if f.get("hidden")]
            ids = {f.get("id") for f in model.get("flows", [])}
            model["flows"] = [f for f in model.get("flows", []) if not f.get("hidden")] + [f for f in kept if f["id"] not in ids]
        errs = validate(model)
        if errs:
            raise HTTPException(422, {"errors": errs})
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(model, indent=2))
        tmp.replace(p)
        return {"ok": True}

    @app.post("/api/models")
    def new_model(model: dict[str, Any]) -> dict:
        """A new model of the user's own (an uploaded file, say), with an id made from its name."""
        mid = unique_id(str(model.get("name") or model.get("id") or "model"))
        put_model(mid, {**model, "flows": model.get("flows", []), "stocks": model.get("stocks", []), "machines": model.get("machines", [])})
        return {"id": mid}

    @app.post("/api/models/{model_id}/copy")
    def copy_model(model_id: str, body: dict[str, Any] | None = None) -> dict:
        """Save as: a copy of any model (hidden flows and the run included) under a new name."""
        body = body or {}
        if basics.is_basic(model_id):                         # the true model alone, without the ladder's data
            src = {k: v for k, v in basics.model(model_id).items() if k not in ("recorded", "basic")}
            body = {**body, "run": False}
        else:
            src = json.loads(_path(model_id).read_text())
        name = str(body.get("name") or f"{src.get('name', model_id)} (copy)")
        mid = unique_id(name)
        src.update(id=mid, name=name)
        src.pop("example", None)
        (models_dir() / f"{mid}.json").write_text(json.dumps(src, indent=2))
        if body.get("run", True):
            # the run goes with the copy: a running one is paused while its record is copied, and
            # carries on as the copy's (the original keeps its record up to here)
            was = runs[model_id] if model_id in runs and runs[model_id].running else None
            if was:
                was.stop()
            copy_run(model_id, mid)
            if was:
                live(mid).start(was.seconds_per_tick)
        return {"id": mid, "name": name}

    @app.delete("/api/models/{model_id}")
    def delete_model(model_id: str) -> dict:
        if is_example(model_id) or basics.is_basic(model_id):
            raise HTTPException(409, "examples cannot be deleted")
        p = _path(model_id)
        if model_id in runs:
            gone = runs.pop(model_id)
            gone.stop()
            gone.programs.close()
        jobs.forget(model_id)
        p.unlink()
        shutil.rmtree(home() / "runs" / model_id, ignore_errors=True)
        return {"ok": True}

    @app.get("/api/models/{model_id}/download")
    def download_model(model_id: str) -> Response:
        """The model as a file to keep, hidden flows included (it is the user's own copy)."""
        m = basics.model(model_id) if basics.is_basic(model_id) else json.loads(_path(model_id).read_text())
        m.pop("example", None)
        return Response(json.dumps(m, indent=2), media_type="application/json",
                        headers={"Content-Disposition": f'attachment; filename="{model_id}.json"'})

    def page(file: str) -> HTMLResponse:
        # stamp each asset with its modification time so caches (Cloudflare's included) never serve a stale copy
        html = (STATIC / file).read_text()
        for name in ("app.js", "sim.js", "simplify.js", "research.js", "diagram.js", "ladder.js", "ladder-compare.js", "ladder-board.js", "style.css"):
            html = html.replace(f"/static/{name}", f"/static/{name}?v={int((STATIC / name).stat().st_mtime)}")
        return HTMLResponse(html, headers={"Cache-Control": "no-cache"})

    @app.get("/")
    def index() -> HTMLResponse:
        return page("index.html")

    @app.get("/research")
    def research_page() -> HTMLResponse:
        return page("research.html")

    @app.get("/ladder")
    def ladder_page() -> HTMLResponse:
        return page("ladder.html")

    @app.get("/ladder/run")
    def ladder_run_page() -> HTMLResponse:
        return page("ladder-run.html")

    @app.get("/ladder/leaderboard")
    def leaderboard_page() -> HTMLResponse:
        return page("leaderboard.html")

    @app.get("/ladder/glossary")
    def glossary_page() -> HTMLResponse:
        return page("glossary.html")

    @app.get("/ladder/probes")
    def probes_page() -> HTMLResponse:
        return page("probes.html")

    app.include_router(research_router)
    app.include_router(ladder_router)
    app.include_router(analysis_router)

    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    return app


def check_discovery_request(body: dict[str, Any]) -> dict[str, Any]:
    """What the page sends for discovery, checked: the stocks in scope, the measured series, the
    announced eras, the known change per stock and step, and a strategy by name."""
    stocks, run = body.get("stocks"), body.get("run") or {}
    t, levels = run.get("t"), run.get("levels")
    if not isinstance(stocks, list) or not stocks or not all(isinstance(s, dict) and isinstance(s.get("id"), str) for s in stocks):
        raise HTTPException(422, "stocks: a list of stocks with ids")
    if not isinstance(t, list) or not isinstance(levels, dict):
        raise HTTPException(422, "run: {t: [...], levels: {stock: [...]}}")
    ids = {s["id"] for s in stocks}
    if any(not isinstance(levels.get(i, []), list) or len(levels.get(i, [])) not in (0, len(t)) for i in ids):
        raise HTTPException(422, "run.levels: one value per step for every stock in scope")
    known = body.get("known") or {}
    if not isinstance(known, dict) or any(not isinstance(v, list) or len(v) != len(t) for v in known.values()):
        raise HTTPException(422, "known: one change per step for each stock")
    strategy = body.get("strategy") or "matrix"
    if strategy not in strategy_names():
        raise HTTPException(422, f"no strategy {strategy!r}")
    eras = [{"start": e["start"], "label": e.get("label")} for e in body.get("eras") or [] if isinstance(e, dict) and isinstance(e.get("start"), (int, float))]
    return {"stocks": stocks, "run": {"t": t, "levels": {i: levels.get(i) or [0] * len(t) for i in ids}}, "eras": eras,
            "known": {i: v for i, v in known.items() if i in ids}, "strategy": strategy}


def _known(model_id: str) -> None:
    """404 unless the model exists (a stored model, an example, or a basic model)."""
    if not basics.is_basic(model_id):
        _path(model_id)


def _path(model_id: str, must_exist: bool = True) -> Path:
    if not ID_RE.match(model_id):
        raise HTTPException(400, "bad model id")
    p = EXAMPLES / f"{model_id}.json" if is_example(model_id) else models_dir() / f"{model_id}.json"
    if must_exist and not p.exists():
        raise HTTPException(404, "no such model")
    return p


def main() -> None:
    import uvicorn

    ap = argparse.ArgumentParser(prog="sdlab")
    ap.add_argument("--port", type=int, default=8020)
    ap.add_argument("--host", default="127.0.0.1")
    args = ap.parse_args()
    uvicorn.run(create_app(), host=args.host, port=args.port)
