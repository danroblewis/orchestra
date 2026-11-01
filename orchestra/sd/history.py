"""The model's recent history, read from the metrics: each stock's level and each flow's rate over
the last ``HISTORY_S``, for the Dynamics page's sparklines and charts (``web.background``), the
host's announcements (``sd.announce``), the judging of predictions (``sd.judge``) and the model reads
(``sd.reads``, ``sd.equations``).
Levels are sampled at the project's discovery step when that is finer than ``STOCK_STEP_S``, so
the history shows the levels discovery saw."""

from __future__ import annotations

from itertools import pairwise

from ..metrics import step_sample
from .model import SeriesRef

HISTORY_S = 3600.0
STOCK_STEP_S = 15.0          # at most: finer when the project's discovery step is
FLOW_STEP_S = 30.0


def remote_refs(model) -> list:
    """The series in other stores the model's stocks, flows and measured inputs are bound to."""
    refs = [s.series for s in model.stocks if s.series]
    for f in model.flows:
        refs += f.measured_by or ([f.counter] if f.counter else [])
    refs += [SeriesRef(r["name"], r["labels"], source=r.get("source")) for r in (model.discovery.get("inputs") or {}).values()]
    return [r for r in refs if r.source and r.source != "own"]


def stock_step(discovery_step: float) -> float:
    """How often the history samples a level: discovery's own grid when it is finer."""
    return min(STOCK_STEP_S, discovery_step) if discovery_step > 0 else STOCK_STEP_S


def history(model, raw, end: float, stock_step: float = STOCK_STEP_S, span_s: float = HISTORY_S,
            flow_step: float | None = None) -> dict:
    """The model's history over the ``span_s`` (HISTORY_S) before ``end``: each stock's level every
    ``stock_step``, each flow's rate every ``flow_step`` (FLOW_STEP_S), and the measured inputs the
    equations read. ``raw(ref, start, end)`` reads one series' points."""
    start = end - span_s
    fstep = float(flow_step or FLOW_STEP_S)
    unit = {"second": 1.0, "minute": 60.0, "hour": 3600.0}.get(model.time_unit, 60.0)
    stocks, flows = {}, {}
    for s in model.stocks:
        if s.series:
            pts = raw(s.series, start - 300, end)
            t0 = start - start % stock_step
            stocks[s.id] = [[round(t), v] for t, v in step_sample(pts, t0, end, stock_step)]
    for f in model.flows:
        refs = f.measured_by or ([f.counter] if f.counter else [])
        total: dict[int, float] = {}
        for c in refs:                     # a flow measured by several counters: their sum
            pts = raw(c, start - 300, end)
            t0 = start - start % fstep
            for a, b in pairwise(step_sample(pts, t0, end, fstep)):
                total[round(b[0])] = total.get(round(b[0]), 0.0) + ((b[1] - a[1]) if b[1] >= a[1] else b[1]) * unit / fstep
        if refs:
            flows[f.id] = [[t, v] for t, v in sorted(total.items())]
    # measured inputs the model's equations read (levels that are not stocks)
    inputs = {}
    for name, ref in (model.discovery.get("inputs") or {}).items():
        pts = raw(SeriesRef(ref["name"], ref["labels"], source=ref.get("source")), start - 300, end)
        t0 = start - start % stock_step
        inputs[name] = [[round(t), v] for t, v in step_sample(pts, t0, end, stock_step)]
    return {"at": end, "start": start, "stock_step": stock_step, "flow_step": fstep,
            "time_unit": model.time_unit, "stocks": stocks, "flows": flows, "inputs": inputs}
