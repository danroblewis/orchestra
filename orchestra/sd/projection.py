"""Each stock's projection (``sd.simulate``) as the Dynamics page and the Dashboard say it: how far
it is trusted, the band that trust draws, when it empties, or why there is none.

**Trust** is the stock's held-out record (``sd.equations.heldout``, saved at discovery in
``trust["behaviour"]``): the model run forward from part-way through its own window and compared
with what was then measured. ``trusted_s`` is the longest horizon those runs covered (half the fit
window): how far ahead the equations were tested. Without a record the trust is not measured
(``trust: None``) and no band is drawn.

**The band** around the central projection, at ``h`` time units from now: ``± z × growth × h``
while ``h`` is within the tested horizon ``T`` (the band that covered 80% of the held-out truth,
``heldout.record``), and ``± z × growth × h × (h / T)`` beyond it: past what was tested the error
is assumed to grow faster than it was seen to, so the band widens the further the projection
runs past ``T``. A level is never below zero, so neither is the band. ``tested_until`` is where
the tested part ends (``now + T``, or the horizon's end when ``T`` covers it).

**No projection** (``no_projection``, a few words the page prints at the line's end): a stock with
no measured level (hidden, or with no level now): ``no level measured``; a stock whose equations do
worse than holding the level (``beats_hold`` false): ``worse than holding``. The page adds the one
it judges from the live rates: ``equations wrong now`` (a flow of the stock not moving as its
equation says, ``static/flow-check.js``).

Pure: nothing is read or written."""

from __future__ import annotations

from .discover import UNITS
from .model import Model

EMPTY = 1e-6         # a level at or below this is empty


def _why(stock, measured: dict) -> str | None:
    ev = stock.evidence or {}
    t = ev.get("trust") if isinstance(ev.get("trust"), dict) else {}
    if ev.get("hidden") or (t.get("score") == 0 and t.get("kind") == "unmeasured") or not measured.get(stock.id):
        return "no level measured"
    b = t.get("behaviour") or {}
    if b.get("beats_hold") is False:
        return "worse than holding"
    return None


def _trust(stock, unit: float) -> dict | None:
    t = (stock.evidence or {}).get("trust")
    b = (t or {}).get("behaviour") if isinstance(t, dict) else None
    if not b or b.get("horizon") is None:
        return None
    return {"level": b.get("level"), "score": b.get("score"), "beats_hold": b.get("beats_hold"),
            "trusted_s": round(float(b["horizon"]) * unit, 1), "growth": float(b.get("growth") or 0.0), "z": float(b.get("z") or 1.0)}


def band(points: list, now: float, unit: float, trust: dict | None) -> list:
    """``[[t, lo, hi]]`` around the central ``points`` (see the module)."""
    if not trust:
        return []
    g, z, T = trust["growth"], trust["z"], max(trust["trusted_s"] / unit, 1e-9)
    out = []
    for t, c in points:
        h = max(0.0, (t - now) / unit)
        s = z * g * h * max(1.0, h / T)
        out.append([t, round(max(0.0, c - s), 4), round(c + s, 4)])
    return out


def summary(model: Model, result: dict, measured: dict, emptied: dict) -> dict:
    """Per stock: ``trust``, ``band``, ``tested_until``, ``start``, ``end``, ``empties_at`` and
    ``no_projection``, from ``simulate``'s ``result``, the measured levels and when the run's
    outflows first took all a stock held (``emptied``: what flows in during that step may leave
    it a little above zero, so a level alone does not tell)."""
    unit = UNITS.get(model.time_unit, 60.0)
    now, proj = result["now"], result.get("projection") or {}
    out = {}
    for s in model.stocks:
        pts, why, trust = proj.get(s.id) or [], _why(s, measured), _trust(s, unit)
        row = {"trust": trust, "no_projection": why}
        if not why and pts:
            start, end = pts[0][1], pts[-1][1]
            empties = emptied.get(s.id) if start > EMPTY else None
            horizon_end = pts[-1][0]
            row.update(start=start, end=end, empties_at=empties, band=band(pts, now, unit, trust),
                       tested_until=min(horizon_end, now + trust["trusted_s"]) if trust else None)
        out[s.id] = row
    return out
