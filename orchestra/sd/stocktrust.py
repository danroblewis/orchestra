"""How far to trust each discovered stock: measured at discovery, saved with the model.

Every stock records ``trust`` in its evidence: what kind of evidence it stands on, each measurement
of that evidence, the weakest of them as one ``score`` from 0 to 1, a ``level`` (high, medium, low,
very low) and why. The score is the weakest link because each measurement can sink a stock alone: a
balance that fits at R² 0.997 but whose running total drifts from the level is a proxy, and one that
reproduces the level but that the shift null matches as often is a coincidence.

- **conservation** (a level counters balance, ``sd.identify``): the shift null (1 at a p-value of
  ``1 / (shifts + 1)``, the least the null can say, falling to 0 at p = 1); the held-out R² (the
  balance chosen on one half, scored on the other); the level reproduced (one less the running
  residual's spread over the level's); how many units it was judged on (``1 − e^(−units / 20)``); and
  whether both halves chose the same counters (``UNSTABLE`` when not: the flows are not identified).
- **net flow** (``sd.netflow``): the same, for its fitted form: the shift null over the same
  drivers, held-out R², the level reproduced by the integrated net flow, its stretches, and its R²
  itself (it explains only that share of the level's changes).
- **passage** (``sd.passing``): a measured state each item leaves within a step, joined on its raw
  points: the share of its rises and falls that came at the counters' events, and of steps in step.
- **unmeasured** (a hidden stock: no series measures it): 0. Its level is what counters imply, not a
  measurement; the counters' evidence belongs to its flows.
- **by_construction** (a count of reporters and its own turnover, ``sd.construction``): 0. The
  balance is the count taken apart.

``persistence``, the share of recent discoveries that found the stock with the same flows
(``sd.persistence``), joins the components when there are enough of them.

Nothing here hides a stock: a low score is the honest answer, shown beside it."""

from __future__ import annotations

import math

UNSTABLE = 0.6          # the component of a balance whose halves chose different counters
UNITS_SCALE = 20.0      # units at which the units component is 1 − 1/e
LEVELS = ((0.8, "high"), (0.5, "medium"), (0.2, "low"), (0.0, "very low"))


def _clamp(x: float) -> float:
    return min(1.0, max(0.0, x))


def null_component(p: float | None, shifts: int) -> float | None:
    if p is None or shifts <= 0:
        return None
    floor = 1 / (shifts + 1)
    return _clamp((1 - p) / (1 - floor))


def scored(kind: str, components: dict[str, float | None], measures: dict, why: list[str] | None = None) -> dict:
    """The trust record: the measures, the components, the weakest as the score."""
    comps = {k: round(v, 4) for k, v in components.items() if v is not None}
    score = min(comps.values()) if comps else 0.0
    weakest = min(comps, key=comps.get) if comps else None
    level = next(name for bar, name in LEVELS if score >= bar)
    return {"kind": kind, "score": round(score, 4), "level": level, "weakest": weakest, "components": comps, **measures,
            "why": list(why or [])}


def conservation(idn, exact: float) -> dict:
    """A balanced level's trust, from its identification (``sd.identify.Identification``)."""
    shifts = len(idn.null_r2)
    # an exact balance is its own proof: its held-out evidence is how it does on each half; short of
    # exact, how the balance each half chose does on the other
    held = idn.halves_r2 if idn.is_exact else idn.held_out_r2
    why = []
    if idn.dropped:
        why.append("counters only the whole window chose were dropped: " + ", ".join(c.key for c, _ in idn.dropped))
    if idn.declared:
        why.append("its source declared it a channel's backlog and its traffic: a balance by declaration, not chosen by a search")
    if getattr(idn, "pinned", False):
        why.append("declared in [[series]] as a stock's level and flows: a hypothesis tested by the same evidence, not chosen by a search")
    if idn.stable is False and not idn.is_exact:
        why.append("the halves of the window chose different counters: its flows are not identified")
    return scored("conservation", {
        "null": null_component(idn.p_null, shifts),
        "held_out": None if held is None else _clamp(held),
        "level": None if idn.cum_ratio is None else _clamp(1 - idn.cum_ratio),
        "units": 1 - math.exp(-idn.units / UNITS_SCALE),
        "stable": None if idn.stable is None or idn.is_exact else (1.0 if idn.stable else UNSTABLE),
    }, {"p_null": idn.p_null, "null_shifts": shifts, "held_out_r2": idn.held_out_r2, "halves_r2": idn.halves_r2,
        "exact_share": round(exact, 4), "exact_moved": round(idn.exact_moved, 4), "cum_residual_ratio": idn.cum_ratio,
        "units": idn.units, "stable": idn.stable}, why)


def net_flow(notes: dict, r2: float) -> dict:
    """A net-flow stock's trust, from what ``sd.netflow`` measured of its fit (``Fit.notes``)."""
    shifts = notes.get("null_shifts") or 0
    return scored("net_flow", {
        "null": null_component(notes.get("p_null"), shifts),
        "held_out": None if notes.get("held_out_r2") is None else _clamp(notes["held_out_r2"]),
        "level": None if notes.get("cum_ratio") is None else _clamp(1 - notes["cum_ratio"]),
        "units": 1 - math.exp(-(notes.get("units") or 0) / UNITS_SCALE),
        "fit": _clamp(r2),
    }, {"p_null": notes.get("p_null"), "null_shifts": shifts, "held_out_r2": notes.get("held_out_r2"), "r2": round(r2, 4),
        "cum_residual_ratio": notes.get("cum_ratio"), "units": notes.get("units")},
        ["a net flow: no counter measures what moves it; fitted from how the level changed"])


def passage(p) -> dict:
    """A measured state joined on its raw points (``sd.passing.Passage``)."""
    up, down = (p.rises or [0, 0]), (p.falls or [0, 0])
    matched = (up[0] + down[0]) / max(1, up[1] + down[1])
    in_step = 1 - p.out_of_step / max(1, p.moved)
    return scored("passage", {"matched": matched, "in_step": in_step, "units": 1 - math.exp(-p.moved / UNITS_SCALE)},
                  {"units": p.moved, "matched_share": round(matched, 4)},
                  ["a state each item leaves within a step: judged on its raw points, not on a balance of its changes"])


def unmeasured(note: str = "no series measures it: its level is what the counters imply") -> dict:
    return scored("unmeasured", {"measured": 0.0}, {"units": 0}, [note])


def by_construction() -> dict:
    return scored("by_construction", {"evidence": 0.0}, {},
                  ["a count of reporters balanced by its own turnover: exact by construction, so the balance is no evidence"])


def with_persistence(trust: dict, seen: int, of: int, enough: int) -> dict:
    """The record with the share of the last ``of`` discoveries that found the stock with the same
    flows; a component once there are ``enough`` of them."""
    trust = dict(trust)
    trust["persistence"] = round(seen / of, 4) if of else None
    trust["persistence_of"] = of
    if of >= enough and trust.get("kind") not in ("unmeasured", "by_construction"):
        comps = dict(trust.get("components") or {})
        comps["persistence"] = round(seen / of, 4)
        trust.update({k: v for k, v in scored(trust["kind"], comps, {}).items() if k in ("score", "level", "weakest", "components")})
    return trust
