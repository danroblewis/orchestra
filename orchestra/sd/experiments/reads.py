"""What a machine reads before it experiments, in shapes an LLM can use: the model (equations in
the language), its versions, the eras and what changed at the last boundary, the observability
report, the predictions, and series, summarised or raw, with a cap and paging.

Every answer is JSON. A series answer holds at most ``MAX_POINTS`` points in all and
``limit`` per series (default ``LIMIT``); a series cut short says where to continue (``next``:
pass it as ``after``)."""

from __future__ import annotations

import math
import time

from .. import eras as era_record
from .. import predictions as prediction_record
from ..store import ModelStore
from .history import unit_s
from .views import model_view

LIMIT = 500
LIMIT_MAX = 5000
MAX_POINTS = 20_000
MAX_SERIES = 64
SPAN_MAX = 90 * 86400


class ReadError(ValueError):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def base_model(store: ModelStore, version: int | None = None):
    """The model to read or copy: a saved version when named; otherwise the host's latest
    discovery (the current era's model, as the Dynamics page shows it), else the current version.
    Returns it with a label saying which."""
    if version is not None:
        if not isinstance(version, int) or isinstance(version, bool) or version < 1:
            raise ReadError("version: a saved version's number")
        m = store.load(version)
        if m is None:
            raise ReadError(f"no version {version}; the versions are 1 to {store.current_version() or 0}", 404)
        return m, {"version": version}
    cached = store.latest_discovery()
    if cached and cached[1].stocks:
        return cached[1], {"version": None, "latest_discovery_at": cached[0], "current_version": store.current_version()}
    m = store.load()
    if m is None:
        raise ReadError("there is no model yet: the host discovers it from the metrics (orchestra run)", 404)
    return m, {"version": store.current_version()}


def levels_now(model, metrics) -> dict:
    """Each stock's latest level in the project's own store (another store's are not read here)."""
    out = {}
    if metrics is None:
        return out
    for s in model.stocks:
        if s.series and s.series.source in (None, "own"):
            try:
                last = metrics.latest(s.series.name, s.series.labels)
            except Exception:  # noqa: BLE001 - a level is left out, the model is still read
                last = None
            if last:
                out[s.id] = {"t": last[0], "v": last[1]}
    return out


def model(store: ModelStore, metrics=None, version: int | None = None, raw: bool = False) -> dict:
    m, label = base_model(store, version)
    return {"ok": True, "model": model_view(m, label, levels_now(m, metrics), raw=raw)}


def versions(store: ModelStore) -> dict:
    return {"ok": True, "versions": store.versions(), "current": store.current_version()}


def eras(store: ModelStore) -> dict:
    """Every era, the versions of each era's model, the era the latest discovery is of, and what
    changed at its boundary (``sd.compare``)."""
    recorded = era_record.recorded(store)
    vs = store.versions()
    cached = store.latest_discovery()
    return {"ok": True, "eras": [vars(e) for e in recorded], "current": cached[1].era if cached else None,
            "versions": {str(e): [v["version"] for v in vs if v.get("era") == e] for e in [None, *(x.id for x in recorded)]},
            "comparison": (cached[1].discovery.get("era_comparison") if cached else None) or None}


def predictions(store: ModelStore, pid: str | None = None) -> dict:
    by_cause = {e.cause: e.id for e in era_record.recorded(store) if e.cause}
    out = [{**p, "era": by_cause.get(p.get("change"))} for p in prediction_record.recorded(store)]
    if pid is None:
        return {"ok": True, "predictions": out}
    one = next((p for p in out if p.get("id") == pid), None)
    if one is None:
        raise ReadError(f"no prediction {pid}", 404)
    return {"ok": True, "prediction": one}


def observability(store: ModelStore, history, version: int | None = None) -> dict:
    """Which stocks what is measured determines (``sd.observability``), at the last hour's means."""
    from ..observability import operating_point, report

    m, label = base_model(store, version)
    now = time.time()
    levels, inputs, point = operating_point(history(m, now - 3600.0, now))
    return {"ok": True, "label": label, **report(m, levels, inputs, point=point)}


def _summary(pts: list) -> dict:
    vs = [v for _, v in pts]
    n = len(vs)
    if not n:
        return {"n": 0}
    mean = sum(vs) / n
    sd = math.sqrt(sum((v - mean) ** 2 for v in vs) / n)
    ts = [t for t, _ in pts]
    tm = sum(ts) / n
    var_t = sum((t - tm) ** 2 for t in ts)
    slope = sum((t - tm) * (v - mean) for t, v in pts) / var_t * 3600.0 if var_t > 0 else 0.0
    return {"n": n, "from": ts[0], "to": ts[-1], "first": vs[0], "last": vs[-1], "min": min(vs), "max": max(vs),
            "mean": round(mean, 6), "sd": round(sd, 6), "slope_per_hour": round(slope, 6)}


def series(store: ModelStore, history, ids, *, start: float | None = None, end: float | None = None, span_s: float | None = None,
           points: bool = False, limit: int = LIMIT, after: float | None = None, version: int | None = None) -> dict:
    """The named series of the model (stock ids: levels; flow ids: rates per the model's time unit;
    measured inputs' names: values) over a window (default: the last hour), each summarised, with
    its points when ``points``."""
    m, label = base_model(store, version)
    if isinstance(ids, str):
        ids = [x for x in ids.split(",") if x]
    if not ids or len(ids) > MAX_SERIES:
        raise ReadError(f"ids: 1 to {MAX_SERIES} stock, flow or input names")
    stocks, flows = {s.id for s in m.stocks}, {f.id for f in m.flows}
    inputs = set((m.discovery or {}).get("inputs") or {})
    if unknown := [x for x in ids if x not in stocks | flows | inputs]:
        raise ReadError(f"not a stock, flow or measured input of the model: {', '.join(unknown)}", 404)
    end = float(end if end is not None else time.time())
    start = float(start if start is not None else end - float(span_s or 3600.0))
    if not end > start or end - start > SPAN_MAX:
        raise ReadError(f"the window must end after it starts, and span at most {SPAN_MAX // 86400} days")
    if not isinstance(limit, int) or not 1 <= limit <= LIMIT_MAX:
        raise ReadError(f"limit: 1 to {LIMIT_MAX}")
    h = history(m, start, end)
    out, budget = {}, MAX_POINTS
    for x in ids:
        kind = "stock" if x in stocks else "flow" if x in flows else "input"
        pts = (h.get({"stock": "stocks", "flow": "flows", "input": "inputs"}[kind]) or {}).get(x) or []
        pts = [p for p in pts if start <= p[0] <= end]
        row = {"kind": kind, "unit": f"per {m.time_unit}" if kind == "flow" else (m.stock(x).unit if kind == "stock" else None),
               "summary": _summary(pts)}
        if points:
            page = [p for p in pts if after is None or p[0] > after]
            take = min(limit, budget)
            row["points"] = page[:take]
            budget -= len(row["points"])
            if len(page) > take:
                row["next"] = row["points"][-1][0] if row["points"] else after
        out[x] = row
    return {"ok": True, "label": label, "start": start, "end": end, "time_unit": m.time_unit, "unit_s": unit_s(m),
            "step": {"stock": h.get("stock_step"), "flow": h.get("flow_step")}, "series": out}
