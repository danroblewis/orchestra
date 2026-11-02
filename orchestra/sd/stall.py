"""When work stops moving (``orchestra.model.stalled``, SPEC §4.3): Orchestra says so in terms of
the model alone, stocks and flows, never what they mean (rule 1).

From the history read after each discovery (each stock's level, each flow's rate; reading series,
no simulator), over the last ``window_s`` (``[discovery] stall_after``):

- a **stock is stalled** when its level rose over the window while every outflow it has drains
  less than ``share`` (``[discovery] stall_share``) of that flow's usual rate, and at least one
  outflow usually drains it (a usual rate above zero). A flow's **usual** rate is its mean over the
  history before the window; its **recent** rate its mean within it;
- a **flow is stalled** when its usual rate is above zero and every rate measured within the
  window is zero.

Silence is evidence only where events were due: a flow is judged stalled, or counted as usually
draining a stock, only when at its usual rate the window should have held at least
``MIN_EXPECTED`` events, and, when its equation was fitted, only when the fit had at least
``MIN_EVENTS`` events (``sd.balance``: the minimum the fit itself takes, the Dynamics page's
"too few to fit"). A flow fitted on two events says nothing about when the next is due.

An item is judged only when the history covers both parts (points before the window and within
it); otherwise it is left as it was. ``step`` keeps, in the announce record, what is stalled
since when, so each stall is announced once (``orchestra.model.stalled``) and its end once
(``orchestra.model.resumed``), when the item is judged again and no longer stalled. An item that
leaves the model is forgotten without a word."""

from __future__ import annotations

from .balance import MIN_EVENTS
from .model import Flow, Model

ZERO = 1e-12
MIN_EXPECTED = 3        # the events the window should have held at the usual rate, at the least, for silence to say anything
UNIT_S = {"second": 1.0, "minute": 60.0, "hour": 3600.0}


def _split(points: list, cut: float) -> tuple[list[float], list[float]]:
    before = [v for t, v in points if t < cut]
    within = [v for t, v in points if t >= cut]
    return before, within


def _mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def due(f: Flow, usual: float, window_s: float, time_unit: str) -> bool:
    """Whether the flow's silence over the window says anything: at its usual rate (per
    ``time_unit``) at least ``MIN_EXPECTED`` events were due, and its equation, when fitted, was
    fitted on at least ``MIN_EVENTS``."""
    if usual * window_s / UNIT_S.get(time_unit, 60.0) < MIN_EXPECTED:
        return False
    eq = f.current()
    return not (eq is not None and eq.origin == "fitted" and ((eq.quality or {}).get("events") or 0) < MIN_EVENTS)


def find(model: Model, history: dict, at: float, window_s: float, share: float) -> tuple[dict[str, dict], set[str]]:
    """The items stalled now (key ``stock:<id>`` or ``flow:<id>`` -> data) and the keys that could
    be judged at all."""
    cut = at - window_s
    flows_h = history.get("flows") or {}
    rates: dict[str, tuple[float, float, list[float]]] = {}       # flow -> usual, recent, the recent rates
    for f in model.flows:
        before, within = _split(flows_h.get(f.id) or [], cut)
        if before and within:
            rates[f.id] = (_mean(before), _mean(within), within)
    stalled: dict[str, dict] = {}
    judged: set[str] = set()
    for f in model.flows:
        if f.id not in rates:
            continue
        usual, recent, within = rates[f.id]
        judged.add(f"flow:{f.id}")
        if usual > ZERO and all(abs(v) <= ZERO for v in within) and due(f, usual, window_s, model.time_unit):
            last_moving = max((t for t, v in flows_h.get(f.id) or [] if abs(v) > ZERO), default=cut)
            stalled[f"flow:{f.id}"] = {"kind": "flow", "id": f.id, "name": f.name, "since": last_moving, "window_s": window_s,
                                       "rate": round(recent, 6), "usual": round(usual, 6), "per": model.time_unit}
    stocks_h = history.get("stocks") or {}
    for s in model.stocks:
        outs = [f for f in model.flows if f.src == s.id]
        pts = stocks_h.get(s.id) or []
        before, within = _split(pts, cut)
        if not outs or not before or not within or any(f.id not in rates for f in outs):
            continue
        judged.add(f"stock:{s.id}")
        rose_by = within[-1] - before[-1]
        drains = [{"flow": f.id, "rate": round(rates[f.id][1], 6), "usual": round(rates[f.id][0], 6)} for f in outs]
        usually = any(d["usual"] > ZERO and due(f, rates[f.id][0], window_s, model.time_unit) for d, f in zip(drains, outs, strict=True))
        held = all(d["rate"] <= share * d["usual"] if d["usual"] > ZERO else abs(d["rate"]) <= ZERO for d in drains)
        if rose_by > ZERO and usually and held:
            stalled[f"stock:{s.id}"] = {"kind": "stock", "id": s.id, "name": s.name, "since": cut, "window_s": window_s,
                                        "level": within[-1], "rose_by": round(rose_by, 6), "outflows": drains,
                                        "per": model.time_unit}
    return stalled, judged


def step(state: dict, model: Model, history: dict, at: float, window_s: float, share: float) -> tuple[dict, list[dict], list[dict]]:
    """One discovery's part in announcing stalls: the new state (``{"stalled": {key: data}}``), the
    items stalled now that were not, and those that move again."""
    was = dict(state.get("stalled") or {})
    now, judged = find(model, history, at, window_s, share)
    keys = {f"stock:{s.id}" for s in model.stocks} | {f"flow:{f.id}" for f in model.flows}
    went = [now[k] for k in sorted(now) if k not in was]
    came = [{**was[k], "stalled_since": was[k]["since"]} for k in sorted(was) if k in judged and k not in now]
    kept = {k: was[k] for k in was if k in keys and k not in judged}      # not judgeable now: as it was
    kept.update({k: was.get(k, v) for k, v in now.items()})              # still stalled: since its first announcement
    return {**state, "stalled": kept}, went, came
