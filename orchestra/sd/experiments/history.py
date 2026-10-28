"""What a run reads of the measured history: the web server's ``history`` shape
(``web.background.history``: ``stocks`` levels, ``flows`` rates per the model's time unit, measured
``inputs``, each ``[[t, v]]``, with ``at`` and ``start``), for any window, and the pieces each run
takes from it: levels at a time, inputs up to a time (and a forward run's scenario after it), the
flows' measured rates."""

from __future__ import annotations

from bisect import bisect_right

from ..discover import UNITS
from ..model import Model
from .engine import Rate

HOLD_S = 600.0           # a forward run holds a measured flow at its mean over this long before now
STEPS_MAX = 1000         # a run takes at most this many steps; a longer window takes longer steps


def unit_s(model: Model) -> float:
    return UNITS.get(model.time_unit, 60.0)


def at(points, t: float) -> float | None:
    """The value at or before ``t`` (the first after it when ``t`` is before every point);
    ``points`` in time order."""
    if not points:
        return None
    i = bisect_right(points, t, key=lambda p: p[0])
    return points[max(0, i - 1)][1]


def hidden(stock) -> bool:
    """A stock no series measures: one discovery inferred (``evidence.hidden``) or an edit added."""
    return bool((stock.evidence or {}).get("hidden"))


def initial(stock) -> float:
    return float((stock.evidence or {}).get("initial") or 0.0)


def levels_at(model: Model, history: dict, t: float, overrides: dict | None = None) -> tuple[dict, list[str]]:
    """Each stock's level at ``t``: ``overrides`` first, then as measured, then a hidden stock's
    initial level; and the stocks with none of these (they start at 0)."""
    measured = history.get("stocks") or {}
    out, missing = {}, []
    for s in model.stocks:
        if overrides and s.id in overrides:
            out[s.id] = float(overrides[s.id])
        elif not hidden(s) and (v := at(measured.get(s.id), t)) is not None:
            out[s.id] = float(v)
        else:
            out[s.id] = initial(s)
            if not hidden(s):
                missing.append(s.id)
    return out, missing


def inputs_until(history: dict, t: float) -> dict[str, list]:
    return {k: [p for p in pts if p[0] <= t] for k, pts in (history.get("inputs") or {}).items()}


def held(history: dict, fid: str, now: float) -> list[float]:
    return [v for t, v in (history.get("flows") or {}).get(fid) or [] if now - HOLD_S <= t <= now]


def holds(history: dict, fids, now: float) -> dict[str, Rate]:
    """A forward run's measured rates: each flow's mean over the last HOLD_S, from now."""
    out = {}
    for fid in fids:
        xs = held(history, fid, now)
        out[fid] = Rate([], hold=sum(xs) / len(xs) if xs else 0.0)
    return out


def measured_rates(history: dict, fids) -> dict[str, Rate]:
    """A replay's measured rates: each flow's as counted, over the stretch that contains a time."""
    return {fid: Rate((history.get("flows") or {}).get(fid) or []) for fid in fids}


def step_for(span_s: float, step_s: float | None, least: float = 15.0) -> float:
    return float(step_s or max(least, span_s / STEPS_MAX))


def read_window(model: Model, raw, start: float, end: float, stock_step: float, flow_step: float | None = None) -> dict:
    """The history of ``model``'s series over [start, end], read through ``raw(ref, start, end)``
    (``sd.judge.reader``)."""
    from ...web.background import history

    return history(model, raw, end, stock_step, span_s=end - start, flow_step=flow_step)
