"""Running the model's equations forward: what they say the stocks did, and will do.

Two runs, both stepped by SD Lab's simulator (``orchestra.sdlab.discovery.simulate``: effects,
measured inputs, and no stock giving more than it holds):

- **since the era began**: from the measured levels at the start of the era (the time since every
  series the model was fitted on was being written), with nothing but the equations, the measured
  inputs and the flows that are replayed (below) to now. How far it ends from what was measured
  is how well the equations explain the system;
- **projection**: from the measured levels now, ``horizon_s`` into the future, with each measured
  input held at its last value.

A flow whose equation has no form the simulator steps (an SD Lab expression, or no equation) is
replayed: its observed rate in the past, and its mean over the last ``HOLD_S`` in the future. The
result says which flows were replayed. Hidden stocks start at 0."""

from __future__ import annotations

from itertools import pairwise

from .discover import UNITS
from .model import Equation, Model
from .strategies import _scale

STEPPED = {"constant", "proportional", "linear", "gap"}
HOLD_S = 600.0


def _rate(e: Equation | None, src: str | None) -> dict | None:
    """An equation as SD Lab's rate (per time unit), or None when the simulator can't step it."""
    if e is None:
        return None
    if e.spec and e.spec.get("form"):
        return dict(e.spec) if e.spec["form"] in STEPPED else None
    p, x = e.params, (e.inputs[0] if e.inputs else src)
    x = x[6:] if x and x.startswith("input:") else x
    if e.form == "constant":
        return {"form": "constant", "value": p.get("c", 0.0)}
    if e.form == "proportional" and x:
        return {"form": "proportional", "stock": x, "k": p.get("k", 0.0)}
    if e.form == "linear" and x:
        return {"form": "linear", "c": p.get("c", 0.0), "terms": [{"stock": x, "k": p.get("k", 0.0)}]}
    return None


def _at(points: list, t: float) -> float | None:
    """The value at or before t (or the first after it, when t is before every point)."""
    v = None
    for tt, x in points:
        if tt > t:
            break
        v = x
    return v if v is not None else (points[0][1] if points else None)


def simulate(model: Model, history: dict, *, now: float, start: float, horizon_s: float, step_s: float = 15.0) -> dict:
    """Both runs, as ``{"era": {stock: [[t, level]]}, "projection": {...}, "replayed": [flow ids],
    "start", "now", "step"}``. ``history`` is the web server's: measured levels (``stocks``),
    flow rates per time unit (``flows``) and measured inputs (``inputs``), each ``[[t, v]]``."""
    import numpy as np

    from ..sdlab.discovery.simulate import Model as Stepper

    g = step_s / UNITS[model.time_unit]                      # time units per step: rates become amounts per step
    ids = [s.id for s in model.stocks]
    flows, replayed = [], []
    for f in model.flows:
        rate = _rate(f.current(), f.src)
        if rate is not None:
            sp = _scale(rate, g)
            flows.append({"id": f.id, "from": f.src, "to": f.dst, "rate": sp, **({"effects": sp["effects"]} if sp.get("effects") else {})})
            continue
        obs = (history.get("flows") or {}).get(f.id) or []
        recent = [v for t, v in obs if t >= now - HOLD_S]
        hold = sum(recent) / len(recent) if recent else 0.0
        segs = [{"from": a[0], "to": b[0], "value": a[1] * g} for a, b in pairwise(obs)]
        segs.append({"from": obs[-1][0] if obs else start, "to": float("inf"), "value": hold * g})
        flows.append({"id": f.id, "from": f.src, "to": f.dst, "inflow": segs})
        replayed.append(f.id)

    def inputs(t_until: float) -> dict | None:
        series = history.get("inputs") or {}
        if not series:
            return None
        ts = sorted({t for pts in series.values() for t, _ in pts if t <= t_until}) or [start]
        return {"t": ts, "values": {k: [_at(pts, t) or 0.0 for t in ts] for k, pts in series.items()}}

    def run(t0: float, t1: float, levels: dict) -> dict:
        times = np.arange(t0, t1, step_s)
        stepper = Stepper(flows, ids, inputs=inputs(min(t1, now)))
        L = np.array([[levels.get(i) or 0.0] for i in ids], dtype=float)
        out = {i: [[round(t0), float(L[k, 0])]] for k, i in enumerate(ids)}
        for t in times:
            L = stepper.step(L, np.array([t]))
            for k, i in enumerate(ids):
                out[i].append([round(t + step_s), round(float(L[k, 0]), 4)])
        return out

    measured = history.get("stocks") or {}
    at_start = {i: _at(measured.get(i) or [], start) for i in ids}
    at_now = {i: _at(measured.get(i) or [], now) for i in ids}
    return {"start": start, "now": now, "step": step_s, "replayed": replayed,
            "era": run(start, now, at_start) if now > start else {},
            "projection": run(now, now + horizon_s, at_now)}
