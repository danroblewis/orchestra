"""SD Lab server: stores models as JSON files and serves the editor.

Models live in ``$SDLAB_HOME/models/<id>.json`` (default ``~/.sdlab``). The examples
in ``sdlab/examples/`` are copied in the first time the server starts."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

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


def seed_examples() -> None:
    for ex in EXAMPLES.glob("*.json"):
        dest = models_dir() / ex.name
        if not dest.exists():
            shutil.copyfile(ex, dest)


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
    seed_examples()
    runs: dict[str, LiveRun] = {}

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        yield
        for r in runs.values():
            r.stop()

    app = FastAPI(title="SD Lab", lifespan=lifespan)

    def live(model_id: str) -> LiveRun:
        p = _path(model_id)
        if model_id not in runs:
            runs[model_id] = LiveRun(model_id, p, home() / "runs" / model_id, EXAMPLES)
        return runs[model_id]

    @app.get("/api/programs")
    def programs() -> dict:
        return {"programs": available_programs(EXAMPLES)}

    @app.get("/api/models/{model_id}/live")
    def live_state(model_id: str, since: int = 0) -> dict:
        return live(model_id).snapshot(since)

    @app.post("/api/models/{model_id}/live/{action}")
    def live_control(model_id: str, action: str, body: dict[str, Any] | None = None) -> dict:
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
        rec = live(model_id).firing(n)
        if rec is None:
            raise HTTPException(404, "that firing is no longer kept; only the most recent 60 are")
        return rec

    @app.get("/api/models/{model_id}/live/stocks/{stock_id}")
    def live_items(model_id: str, stock_id: str) -> dict:
        return live(model_id).stock_items(stock_id)


    @app.get("/api/models")
    def list_models() -> dict:
        out = []
        for p in sorted(models_dir().glob("*.json")):
            try:
                m = json.loads(p.read_text())
            except ValueError:
                continue
            out.append({"id": p.stem, "name": m.get("name", p.stem)})
        return {"models": out}

    # Hidden flows stand for parts of the real system nobody has modelled: the runner runs them,
    # but the page never receives them, and saving the page's model keeps them as they were.
    @app.get("/api/models/{model_id}")
    def get_model(model_id: str, reveal: bool = False) -> dict:
        m = json.loads(_path(model_id).read_text())
        if not reveal:
            m["flows"] = [f for f in m.get("flows", []) if not f.get("hidden")]
        return m

    @app.put("/api/models/{model_id}")
    def put_model(model_id: str, model: dict[str, Any]) -> dict:
        p = _path(model_id, must_exist=False)
        model["id"] = model_id
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

    @app.post("/api/models/{model_id}/reset")
    def reset_model(model_id: str) -> dict:
        ex = EXAMPLES / f"{model_id}.json"
        if not ex.exists():
            raise HTTPException(404, "no example by that id")
        shutil.copyfile(ex, _path(model_id, must_exist=False))
        return json.loads(ex.read_text())

    @app.get("/")
    def index() -> HTMLResponse:
        # stamp each asset with its modification time so caches (Cloudflare's included) never serve a stale copy
        html = (STATIC / "index.html").read_text()
        for name in ("app.js", "sim.js", "discover.js", "simplify.js", "style.css"):
            html = html.replace(f"/static/{name}", f"/static/{name}?v={int((STATIC / name).stat().st_mtime)}")
        return HTMLResponse(html, headers={"Cache-Control": "no-cache"})

    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    return app


def _path(model_id: str, must_exist: bool = True) -> Path:
    if not ID_RE.match(model_id):
        raise HTTPException(400, "bad model id")
    p = models_dir() / f"{model_id}.json"
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
