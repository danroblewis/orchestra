"""The Prometheus HTTP API (the read side) over a Dataset, as a FastAPI app."""

import json
import math
import time
from datetime import datetime
from urllib.parse import parse_qs

from fastapi import FastAPI, Request
from fastapi.responses import Response
from starlette.concurrency import run_in_threadpool

from . import engine
from .promql import ParseError, Selector, parse, parse_duration
from .store import Dataset

MAX_POINTS = 11000


class Clock:
    """What "now" is. `end`: the last sample. `replay`: starts `replay_from` days
    before the end and runs at `speed` x wall clock, stopping at the end."""

    def __init__(self, ds: Dataset, mode: str = "end", replay_from: float = 1.0, speed: float = 1.0):
        self.ds, self.mode, self.speed = ds, mode, speed
        self.origin = ds.end - replay_from * 86400 if mode == "replay" else ds.end
        self.wall0 = time.time()

    def now(self) -> float:
        if self.mode != "replay":
            return float(self.ds.end)
        return min(float(self.ds.end), self.origin + self.speed * (time.time() - self.wall0))

    def jmax(self, now: float | None = None) -> int:
        now = self.now() if now is None else now
        return min(self.ds.n - 1, math.floor((now - self.ds.start) / self.ds.step))


class ApiError(Exception):
    def __init__(self, kind: str, msg: str, status: int):
        super().__init__(msg)
        self.kind, self.msg, self.status = kind, msg, status


def _json(obj, status=200):
    return Response(json.dumps(obj, separators=(",", ":")), status_code=status, media_type="application/json")


def _ok(data):
    return _json({"status": "success", "data": data})


def _time(value, default: float) -> float:
    if value is None or value == "":
        return default
    try:
        return float(value)
    except ValueError:
        pass
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        raise ApiError("bad_data", f"cannot parse {value!r} to a valid timestamp", 400) from None


def _duration(value) -> float:
    if value is None or value == "":
        raise ApiError("bad_data", "missing step", 400)
    try:
        return float(value)
    except ValueError:
        pass
    try:
        return parse_duration(value)
    except ParseError:
        raise ApiError("bad_data", f"cannot parse {value!r} to a valid duration", 400) from None


async def _params(request: Request) -> dict[str, list[str]]:
    params: dict[str, list[str]] = {}
    for k, v in request.query_params.multi_items():
        params.setdefault(k, []).append(v)
    if request.method == "POST":
        body = (await request.body()).decode()
        for k, vs in parse_qs(body, keep_blank_values=True).items():
            params.setdefault(k, []).extend(vs)
    return params


def _one(params, name):
    vs = params.get(name)
    return vs[-1] if vs else None


def _vector_out(kind, value, t):
    ts = engine.fmt_ts(t)
    if kind == "scalar":
        return {"resultType": "scalar", "result": [ts, engine.fmt_value(value[0])]}
    if kind == "string":
        return {"resultType": "string", "result": [ts, value]}
    if kind == "matrix":
        return {"resultType": "matrix", "result": value}
    result = [{"metric": lb, "value": [ts, engine.fmt_value(vals[0])]} for lb, vals in value if vals[0] == vals[0]]
    return {"resultType": "vector", "result": result}


def _matrix_out(kind, value, times):
    ts = [engine.fmt_ts(t) for t in times]
    if kind == "scalar":
        value = [({}, value)]
    elif kind != "vector":
        raise ApiError(
            "bad_data", f"invalid expression type {kind!r} for range query, must be Scalar or instant Vector", 400
        )
    result = []
    for lb, vals in value:
        kept = [(t, x) for t, x in zip(ts, vals) if x == x]
        pts = [[t, v] for (t, _), v in zip(kept, engine.fmt_values([x for _, x in kept]))]
        if pts:
            result.append({"metric": lb, "values": pts})
    return {"resultType": "matrix", "result": result}


def _selectors(params, required):
    raw = params.get("match[]") or []
    if not raw:
        if required:
            raise ApiError("bad_data", "no match[] parameter provided", 400)
        return None
    out = []
    for text in raw:
        try:
            node = parse(text)
        except ParseError as e:
            raise ApiError("bad_data", str(e), 400) from None
        if not isinstance(node, Selector):
            raise ApiError("bad_data", f'invalid parameter "match[]": {text!r} is not a vector selector', 400)
        out.append(node)
    return out


def create_app(ds: Dataset, clock: Clock | None = None) -> FastAPI:
    clock = clock or Clock(ds)
    app = FastAPI(title="PromLab")
    app.state.ds, app.state.clock = ds, clock

    def matched(params, required=False):
        sels = _selectors(params, required)
        if sels is None:
            return ds.series
        ev = engine.Evaluator(ds, [], clock.jmax())
        seen, out = set(), []
        for sel in sels:
            for s in ev.select(sel):
                if id(s) not in seen:
                    seen.add(id(s))
                    out.append(s)
        return out

    async def handle(request, fn):
        try:
            params = await _params(request)
            return _ok(await run_in_threadpool(fn, params))
        except ApiError as e:
            return _json({"status": "error", "errorType": e.kind, "error": e.msg}, e.status)
        except ParseError as e:
            return _json({"status": "error", "errorType": "bad_data", "error": str(e)}, 400)
        except engine.EvalError as e:
            return _json({"status": "error", "errorType": "execution", "error": str(e)}, 422)

    def query(params):
        text = _one(params, "query")
        if not text:
            raise ApiError("bad_data", 'invalid parameter "query": no expression found in input', 400)
        now = clock.now()
        t = _time(_one(params, "time"), now)
        kind, value = engine.evaluate(ds, text, [t], clock.jmax(now))
        return _vector_out(kind, value, t)

    def query_range(params):
        text = _one(params, "query")
        if not text:
            raise ApiError("bad_data", 'invalid parameter "query": no expression found in input', 400)
        start = _time(_one(params, "start"), math.nan)
        end = _time(_one(params, "end"), math.nan)
        if start != start or end != end:
            raise ApiError("bad_data", 'invalid parameter "start"/"end": both are required', 400)
        step = _duration(_one(params, "step"))
        if end < start:
            raise ApiError("bad_data", 'invalid parameter "end": end timestamp must not be before start time', 400)
        if step <= 0:
            raise ApiError(
                "bad_data",
                'invalid parameter "step": zero or negative query resolution step widths are not accepted. Try a positive integer',
                400,
            )
        if (end - start) / step > MAX_POINTS:
            raise ApiError(
                "bad_data",
                "exceeded maximum resolution of 11,000 points per timeseries. Try decreasing the query resolution (?step=XX)",
                400,
            )
        times = []
        k = 0
        while start + k * step <= end:
            times.append(start + k * step)
            k += 1
        kind, value = engine.evaluate(ds, text, times, clock.jmax())
        return _matrix_out(kind, value, times)

    def labels(params):
        names = set()
        for s in matched(params):
            names.update(s.labels)
        return sorted(names)

    def label_values(name, params):
        return sorted({s.labels[name] for s in matched(params) if name in s.labels})

    def series(params):
        return [s.labels for s in matched(params, required=True)]

    def metadata(params):
        metric = _one(params, "metric")
        return {
            m: [{"type": x["type"], "help": x["help"], "unit": ""}]
            for m, x in ds.meta.items()
            if metric in (None, "", m)
        }

    @app.api_route("/api/v1/query", methods=["GET", "POST"])
    async def api_query(request: Request):
        return await handle(request, query)

    @app.api_route("/api/v1/query_range", methods=["GET", "POST"])
    async def api_query_range(request: Request):
        return await handle(request, query_range)

    @app.api_route("/api/v1/labels", methods=["GET", "POST"])
    async def api_labels(request: Request):
        return await handle(request, labels)

    @app.get("/api/v1/label/{name}/values")
    async def api_label_values(name: str, request: Request):
        return await handle(request, lambda p: label_values(name, p))

    @app.api_route("/api/v1/series", methods=["GET", "POST"])
    async def api_series(request: Request):
        return await handle(request, series)

    @app.get("/api/v1/metadata")
    async def api_metadata(request: Request):
        return await handle(request, metadata)

    @app.get("/api/v1/status/buildinfo")
    async def buildinfo():
        return _ok(
            {
                "version": "2.53.0-promlab",
                "revision": "promlab",
                "branch": "promlab",
                "buildUser": "sdlab",
                "buildDate": "",
                "goVersion": "",
            }
        )

    @app.get("/api/v1/status/promlab")
    async def promlab_status():
        now = clock.now()
        return _ok(
            {
                "now": now,
                "start": ds.start,
                "end": ds.end,
                "step": ds.step,
                "clock": clock.mode,
                "speed": clock.speed,
                "series": len(ds.series),
            }
        )

    @app.get("/-/healthy")
    @app.get("/-/ready")
    async def healthy():
        return Response("PromLab is Healthy.\n", media_type="text/plain")

    return app
