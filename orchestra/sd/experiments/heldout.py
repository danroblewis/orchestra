"""How well each stock's projection holds up: the model run forward from part-way through its own
window, as a forward run would be from now, and compared with what was then measured. System
dynamics calls this the behaviour-reproduction test; it is what a projection should be trusted by,
where a stock's identity trust (``sd.stocktrust``) only says its accounting holds.

**The runs.** From each of ``FRACTIONS`` of the window (half-way, two thirds, five sixths), each
stock starts at its measured level, the measured inputs are held at their values then and each
replayed flow at its recent rate (as ``forward`` does from now), and the model runs to the
window's end. Nothing after the start of a run reaches it. The equations were fitted on the whole
window, so the test is held out in time, not in fitting: what it measures is how far the
equations, integrated, drift from the level they were fitted beside, which is what a forward run
does.

**What is kept, per measured stock** (``measure``):

- ``error``: the RMS of run minus measurement over all runs, over the level's spread (its standard
  deviation over the window, at least a tenth of its mean: ``sd.trust.era_errors``' scale);
- ``hold_error``: the same for the level held where each run started (persistence, the forecast
  any model should beat), and ``beats_hold``;
- ``growth``: how fast the error grows with the horizon, in the level's unit per time unit
  (``sqrt(Σ e² / Σ h²)``: an error that grows in proportion to the horizon, as one of a wrong rate
  does), and ``z``: the share of ``COVER`` of the errors within ``z × growth × h``, so that a band
  of ``± z × growth × h`` covered ``COVER`` of the held-out truth;
- ``score``: ``1 / (1 + error)``, 1 for a perfect replay and ½ for one off by the level's whole
  spread, with its ``level`` and ``why``.

``forward`` widens its band by this (``band``): the band the parameters' uncertainty gives is far
too narrow for a model whose structure is wrong, and nothing else tells it so."""

from __future__ import annotations

import math

from ..model import Model
from . import engine
from .history import at, holds, inputs_until, levels_at, unit_s

FRACTIONS = (0.5, 2 / 3, 5 / 6)
COVER = 0.8               # the band a forward run draws, 10th to 90th percentile
Z_RANGE = (0.5, 4.0)      # the multiplier a stock's errors may set
LEVELS = ((0.8, "high"), (0.5, "medium"), (0.2, "low"), (0.0, "very low"))


def _runs(model: Model, history: dict, start: float, end: float, step_s: float) -> dict[str, list[tuple[float, float, float]]]:
    """Per measured stock, (horizon in the model's unit, run − measured, the level held − measured)."""
    measured = history.get("stocks") or {}
    unit = unit_s(model)
    flows = engine.compiled(model)
    out: dict[str, list] = {}
    for f in FRACTIONS:
        t0 = start + f * (end - start)
        steps = int((end - t0) // step_s)
        if steps < 2:
            continue
        levels, missing = levels_at(model, history, t0)
        r = engine.run(model, t0=t0, steps=steps, step_s=step_s, unit_s=unit, levels=levels, inputs=inputs_until(history, t0),
                       observed=holds(history, [x.id for x in flows if x.observed], t0), flows=flows)
        for k, sid in enumerate(r.stocks):
            if sid in missing or not measured.get(sid):
                continue
            for i in range(1, steps + 1):
                t = float(r.t[i])
                m = at(measured[sid], t)
                v = float(r.levels[0, k, i])
                if m is None or not math.isfinite(v):
                    continue
                out.setdefault(sid, []).append(((t - t0) / unit, v - m, levels[sid] - m))
    return out


def _scale(points: list, start: float, end: float) -> float:
    ms = [v for t, v in points if start <= t <= end]
    if len(ms) < 2:
        return 0.0
    mean = sum(ms) / len(ms)
    sd = math.sqrt(sum((m - mean) ** 2 for m in ms) / len(ms))
    return max(sd, 0.1 * abs(mean))


def record(pairs: list[tuple[float, float, float]], scale: float, horizon: float) -> dict:
    """One stock's behaviour record from its held-out (horizon, error, persistence error)."""
    rms = lambda xs: math.sqrt(sum(x * x for x in xs) / len(xs))
    err, hold = rms([e for _, e, _ in pairs]), rms([p for _, _, p in pairs])
    rel = err / scale if scale > 0 else (0.0 if err < 1e-9 else math.inf)
    rel_hold = hold / scale if scale > 0 else (0.0 if hold < 1e-9 else math.inf)
    hh = sum(h * h for h, _, _ in pairs)
    growth = math.sqrt(sum(e * e for _, e, _ in pairs) / hh) if hh > 0 else 0.0
    ratios = sorted(abs(e) / (growth * h) for h, e, _ in pairs if growth > 0 and h > 0)
    z = ratios[min(len(ratios) - 1, int(COVER * len(ratios)))] if ratios else 1.0
    z = min(Z_RANGE[1], max(Z_RANGE[0], z))
    score = 1 / (1 + rel) if math.isfinite(rel) else 0.0
    why = []
    if rel > 1:
        why.append(f"run forward from part-way through the window, it misses the measured level by {rel:.1f}× the level's spread")
    if rel > rel_hold:
        why.append(f"holding the level does better ({rel_hold:.2f} against {rel:.2f} of the spread)")
    return {"score": round(score, 4), "level": next(n for bar, n in LEVELS if score >= bar), "error": round(rel, 4),
            "hold_error": round(rel_hold, 4), "beats_hold": rel < rel_hold, "growth": growth, "z": round(z, 3),
            "horizon": round(horizon, 3), "pairs": len(pairs), "why": why}


def measure(model: Model, history: dict, start: float, end: float, step_s: float) -> dict[str, dict]:
    """Each measured stock's behaviour record over [start, end] (``history`` covers it)."""
    if end - start < 4 * step_s:
        return {}
    pairs = _runs(model, history, start, end, step_s)
    unit = unit_s(model)
    measured = history.get("stocks") or {}
    return {sid: record(ps, _scale(measured.get(sid) or [], start, end), (1 - FRACTIONS[0]) * (end - start) / unit)
            for sid, ps in pairs.items() if len(ps) >= 2}


def widen(b: dict, rec: dict | None, offsets: list[float], unit: float, floor: bool) -> dict:
    """A forward band (``central``, ``lo``, ``hi`` at ``offsets`` seconds) widened by the stock's
    held-out error: ``± z × growth × h`` added to the parameters' spread in quadrature."""
    if not rec or not rec.get("growth"):
        return b
    g, z = float(rec["growth"]), float(rec.get("z") or 1.0)
    lo, hi = [], []
    for o, c, a, h in zip(offsets, b["central"], b["lo"], b["hi"]):
        s = z * g * o / unit
        lo.append(round(c - math.hypot(c - min(a, c), s), 4))
        hi.append(round(c + math.hypot(max(h, c) - c, s), 4))
    if floor:
        lo = [max(0.0, x) for x in lo]
    return {**b, "lo": lo, "hi": hi}
