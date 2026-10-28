"""When the measured levels leave what the model predicted (goal G12; the unexplained-change test
of docs/rationale/lifted-models.md §3.3, fault detection by residuals in
docs/proposals/control-theory.md).

**Predictions.** At each of the host's discoveries the model predicts every stock from its
measured level now, ``horizon_s`` ahead (``predict``: ``sd.whatif`` with no intervention: the
central run and its 10–90% band from the flows' fitted uncertainty). That band is the parameters'
uncertainty only; the events themselves come at random too, so each stock's band is widened by
the spread of a Poisson count of its flows' events over the time since the prediction (its flows'
recent rates, from the history), and never narrower than ``FLOOR_SHARE`` of its level (half an
item for a stock counters balance). ``half`` is the band's half-width so widened.

**The gap.** A stock's gap is its measured level now less the central prediction, in half-widths
of that band (``gap``): within ±1 it is inside the band. It is judged against the **oldest**
prediction that still reaches now, the one made furthest back, so a rate that is wrong shows as a
gap that grows over the horizon instead of starting again from each new level.

**Divergence**, with hysteresis so a stock near the edge does not flip: a stock is out when its
gap passes ``OUT`` half-widths, and **diverged** when it has been out at every check for at least
``after_s`` (``[discovery] diverge_after``). It **returns** when its gap is back within ``BACK``
(inside the band itself). ``judge`` says which stocks diverged and which returned at this check;
``sd.announce`` publishes them."""

from __future__ import annotations

import math

from .model import Model

OUT = 2.0
BACK = 1.0
Z10 = 1.2816            # the 90th percentile of the standard normal: the band's half-width is this many standard deviations
FLOOR_SHARE = 0.05
RECENT_S = 600.0


def predict(model: Model, history: dict, at: float, horizon_s: float) -> dict:
    """A prediction to judge later: per stock, the offsets, central run and band, and the events
    per second its flows move (for the count's own spread)."""
    from .discover import UNITS
    from .whatif import what_if

    r = what_if(model, history, [], horizon_s=horizon_s, now=at, points=61)
    unit = UNITS.get(model.time_unit, 60.0)
    flows = history.get("flows") or {}
    out = {}
    for sid, x in r["stocks"].items():
        rate = 0.0
        for f in model.flows:
            if sid in (f.src, f.dst):
                recent = [v for t, v in flows.get(f.id) or [] if t >= at - RECENT_S]
                rate += abs(sum(recent) / len(recent)) / unit if recent else 0.0
        counted = "balance" in (model.stock(sid).evidence or {})
        out[sid] = {"central": x["baseline"]["central"], "lo": x["baseline"]["lo"], "hi": x["baseline"]["hi"],
                    "per_s": round(rate, 6), "counted": counted}
    return {"at": at, "horizon_s": r["horizon_s"], "t": r["t"], "stocks": out}


def _interp(ts: list[float], xs: list[float], t: float) -> float:
    if t <= ts[0]:
        return xs[0]
    for (t0, x0), (t1, x1) in zip(zip(ts, xs), zip(ts[1:], xs[1:])):
        if t <= t1:
            return x0 + (x1 - x0) * (t - t0) / (t1 - t0) if t1 > t0 else x1
    return xs[-1]


def gap(pred: dict, sid: str, level: float, at: float) -> dict | None:
    """The stock's gap from a prediction at time ``at``: the central level, the half-width and the
    gap in half-widths; None when the prediction does not cover the stock or the time."""
    p = pred["stocks"].get(sid)
    dt = at - pred["at"]
    if p is None or dt < 0 or dt > pred["horizon_s"]:
        return None
    c, lo, hi = (_interp(pred["t"], p[k], dt) for k in ("central", "lo", "hi"))
    noise = Z10 * math.sqrt(p["per_s"] * dt)
    floor = max(FLOOR_SHARE * abs(c), 0.5 if p["counted"] else 1e-9)
    half = max(math.hypot((hi - lo) / 2, noise), floor)
    return {"central": round(c, 4), "lo": round(c - half, 4), "hi": round(c + half, 4), "half": round(half, 4),
            "level": level, "gap": round((level - c) / half, 2), "predicted_at": pred["at"]}


def judge(state: dict, predictions: list[dict], levels: dict[str, float], at: float, after_s: float) -> tuple[dict, list[dict], list[dict]]:
    """One check: the state (each stock out since when, and the diverged ones), the stocks that
    diverged now and those that returned now. ``levels``: each stock's measured level now."""
    out_since = dict(state.get("out_since") or {})
    diverged = dict(state.get("diverged") or {})
    usable = [p for p in predictions if 0 < at - p["at"] <= p["horizon_s"]]
    oldest = min(usable, key=lambda p: p["at"]) if usable else None
    went, came = [], []
    for sid, level in sorted(levels.items()):
        g = gap(oldest, sid, level, at) if oldest else None
        if g is None:
            continue
        if abs(g["gap"]) > OUT:
            out_since.setdefault(sid, at)
        else:
            out_since.pop(sid, None)
        if sid not in diverged and sid in out_since and at - out_since[sid] >= after_s:
            diverged[sid] = {**g, "since": out_since[sid]}
            went.append({"stock": sid, **diverged[sid]})
        elif sid in diverged and abs(g["gap"]) <= BACK:
            came.append({"stock": sid, **g, "diverged_since": diverged.pop(sid)["since"]})
        elif sid in diverged:
            diverged[sid] = {**g, "since": diverged[sid]["since"]}
    return {"out_since": out_since, "diverged": diverged}, went, came
