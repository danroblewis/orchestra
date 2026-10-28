"""How far to trust the model's equations, for a forward run (``sd.experiments.forward``): each flow's spread
(the relative error its fit records) and the reasons a flow or a stock is not trusted.

**Spread.** One number per flow, ``rel``: the relative standard error of its rate, from what its
equation records, and nothing else:

- a Poisson fit (``poisson-mle``) of N events with dispersion φ: ``sqrt(max(1, φ) / N)``, the
  standard error of a rate counted from N events, widened when they came in bursts; ``se`` over
  the parameter when the fit recorded one (``sd.fit``);
- a least-squares net flow at R² over n stretches: ``sqrt((1 − R²) / (R² (n − 2)))``, the relative
  standard error of a regression slope with that R² (1 / its t statistic);
- an SD Lab rate (``sdlab:*``), fitted from the levels: ``1 / sqrt(N)`` of the events its counters
  counted, at least ``FLOOR_SDLAB``, since a fit from the levels is looser than one from the counts;
- a flow that is replayed (no equation the simulator steps): the standard error of the mean of
  the rates it is held at;
- anything else (declared, or nothing recorded): ``UNKNOWN``, said as such.

Every spread is capped at ``CAP``.

**Not trusted.** A flow is not trusted when it is declared (an assumption), a net flow (no counter
measures it), replayed, fitted on fewer than ``MIN_EVENTS`` events or over less than
``MIN_MINUTES``, at R² below ``MIN_R2``, one SD Lab found no flow for in the levels, or one carried
from the previous era's model that this era has not measured yet (origin ``prior``, ``sd.prior``). A stock is
not trusted when a flow into or out of it is not, when it is hidden (no series measures it, so it
starts at 0), when it has no measured level now, or when the model's own run since the era began
(``sd.simulate``) misses its measured level by more than the level's own variation
(``MAX_ERA_ERROR``): the stand-in for a validation bar until one is defined
(docs/proposals/control-theory.md §7.1)."""

from __future__ import annotations

import math

from .model import Flow, Model

UNKNOWN = 0.5
CAP = 1.0
FLOOR_SDLAB = 0.1
FLOOR_REPLAYED = 0.1
MIN_EVENTS = 20
MIN_MINUTES = 10.0
MIN_R2 = 0.5
MAX_ERA_ERROR = 1.0


def spread(f: Flow, replayed_rates: list[float] | None = None) -> tuple[float, str]:
    """The flow's relative standard error, and how it was found."""
    if replayed_rates is not None:
        n = len(replayed_rates)
        if n < 2:
            return UNKNOWN, f"replayed with {n} observed rate{'s' if n != 1 else ''}: ±{UNKNOWN:.0%} assumed"
        m = sum(replayed_rates) / n
        sd = math.sqrt(sum((v - m) ** 2 for v in replayed_rates) / (n - 1))
        rel = sd / math.sqrt(n) / m if m > 0 else UNKNOWN
        return _cap(max(FLOOR_REPLAYED, rel)), f"replayed: standard error of the mean of {n} observed rates"
    e = f.current()
    if e is None or e.origin == "declared":
        return UNKNOWN, f"{'declared' if e else 'no equation'}: no fit to measure its error; ±{UNKNOWN:.0%} assumed"
    q = e.quality or {}
    if "se" in q and (p := next((abs(v) for v in e.params.values() if v), 0.0)):
        return _cap(q["se"] / p), "the fit's standard error over its parameter"
    if "r2" in q and "stretches" in q:
        r2, n = max(1e-3, min(q["r2"], 1.0)), q["stretches"]
        if n <= 2 or r2 >= 1.0:
            return (_cap(UNKNOWN), "least squares with too few stretches") if n <= 2 else (0.0, "least squares at R² 1")
        return _cap(math.sqrt((1 - r2) / (r2 * (n - 2)))), f"least squares at R² {q['r2']:.2f} over {n:g} stretches"
    events = q.get("events") or 0.0
    if events <= 0:
        return UNKNOWN, f"no events recorded for its fit: ±{UNKNOWN:.0%} assumed"
    if e.method.startswith("sdlab:"):
        return _cap(max(FLOOR_SDLAB, 1 / math.sqrt(events))), f"fitted from the levels; its counters counted {events:g} events"
    phi = max(1.0, q.get("dispersion") or 1.0)
    return _cap(math.sqrt(phi / events)), f"{events:g} events, dispersion {phi:.2g}"


def _cap(x: float) -> float:
    return min(CAP, max(0.0, x))


def weak_flow(f: Flow, replayed: bool) -> list[str]:
    """Why a flow's equation is not to be trusted here (empty: nothing against it)."""
    if replayed:
        return ["replayed: no equation the simulator steps; held at its recent observed rate"]
    e = f.current()
    if e is None:
        return ["no equation"]
    why = []
    if e.origin == "declared":
        why.append("declared: an assumption, never fitted")
    if e.origin == "prior":
        why.append(f"carried from the previous era's model (era {(e.prior or {}).get('era') or 'before any era'}): "
                   "not yet measured in this era")
    if f.evidence.get("net_flow_of"):
        why.append("a net flow: no counter measures it; fitted from how the level changed")
    q = e.quality or {}
    if "r2" in q and q["r2"] < MIN_R2:
        why.append(f"fitted at R² {q['r2']:.2f}")
    if e.origin != "declared" and (q.get("events") or 0) < MIN_EVENTS:
        why.append(f"fitted on {q.get('events') or 0:g} events")
    if "live_minutes" in q and q["live_minutes"] < MIN_MINUTES:
        why.append(f"fitted over {q['live_minutes']:g} min")
    if q.get("no_flow_from_levels"):
        why.append("SD Lab found no such flow in the levels")
    return why


def era_errors(model: Model, history: dict, era: dict) -> dict[str, float]:
    """Each measured stock's error in the model's own run since the era began (``era``: the
    ``era`` run of ``sd.simulate``): the RMS of run minus measurement over the level's own spread
    (its standard deviation, or a tenth of its mean when it did not move)."""
    from .simulate import _at

    out = {}
    for s in model.stocks:
        run, measured = era.get(s.id) or [], (history.get("stocks") or {}).get(s.id) or []
        pairs = [(v, m) for t, v in run if (m := _at(measured, t)) is not None]
        if len(pairs) < 2:
            continue
        ms = [m for _, m in pairs]
        mean = sum(ms) / len(ms)
        sd = math.sqrt(sum((m - mean) ** 2 for m in ms) / len(ms))
        rms = math.sqrt(sum((v - m) ** 2 for v, m in pairs) / len(pairs))
        scale = max(sd, 0.1 * abs(mean))
        out[s.id] = rms / scale if scale > 0 else (0.0 if rms < 1e-6 else math.inf)
    return out
