"""The previous era's model as the prior of the new one (goal G11; decision D4 in
docs/roadmap/decisions.md: a prior is a skeleton that may be wrong, and discovery adds to it and
removes from it as the evidence arrives).

Discovery reads only the current era (``sd.eras``), so right after a change it has little to go
on. ``merge`` combines what it found in the era with the model of the era before:

- **a flow found in both, in the same form** (the same equation form reading the same stocks):
  its numbers are the era's own, pulled towards the prior's by a prior worth ``PRIOR_EVENTS``
  events (at most as many as the prior was fitted on), against the events the era counted: each
  number is ``(w × prior + n × own) / (w + n)``. Early in the era the prior dominates; once
  the era has counted many more events than ``PRIOR_EVENTS`` its own evidence does. The equation
  keeps its origin (``fitted``, ``discovered``) and records the prior in ``Equation.prior``:
  the era it came from, its weight ``w / (w + n)``, its numbers and the era's own;
- **a flow found in both in another form**, when the era counted fewer than ``MIN_EVENTS`` of its
  events (too few to choose a form: discovery offers such a flow only the constant): the prior's
  equation, with origin ``prior``; with ``MIN_EVENTS`` or more, the era's own form stands;
- **a flow or stock only the prior has**: carried, with origin ``prior`` (and ``evidence["prior"]``)
  while the era is younger than ``keep_s`` (``[discovery] prior_for``, by default the discovery
  window): long enough that discovery would have found it again were it still there. After that
  it is dropped, and the comparison reports it disappeared at the boundary (``sd.compare``);
- **a flow or stock only the era has**: kept as it is (it appeared).

Machines are the era's (its own events); a machine of the prior is kept only for the prior's
flows that are carried. Nothing is fitted here: the numbers come from the two models."""

from __future__ import annotations

import copy

from .discover import MIN_EVENTS
from .model import Equation, Machine, Model

PRIOR_EVENTS = 20.0
PRIOR = "prior"


def _events(e: Equation | None) -> float:
    return float((e.quality or {}).get("events") or 0.0) if e else 0.0


def _same_form(a: Equation, b: Equation) -> bool:
    return a.form == b.form and list(a.inputs) == list(b.inputs) and set(a.params) == set(b.params) and not a.spec and not b.spec


def _carried(e: Equation, era: str | None, why: str) -> Equation:
    """The prior's equation, carried: its origin becomes ``prior``, and what it was is kept. One
    already carried from an older era keeps saying which."""
    out = copy.deepcopy(e)
    if e.origin == PRIOR:
        return out
    out.prior = {"era": era, "weight": 1.0, "origin": e.origin, "why": why}
    out.origin = PRIOR
    return out


def merge(model: Model, prior: Model | None, *, age_s: float, keep_s: float) -> Model:
    """The era's discovered ``model`` with the previous era's model ``prior`` (see above); what
    was carried, blended and dropped is in ``model.discovery["prior"]``."""
    if prior is None:
        return model
    era = prior.era
    keep = age_s < keep_s
    report = {"era": era, "keep_s": keep_s, "age_s": round(age_s, 1), "carried": {"stocks": [], "flows": []},
              "blended": [], "dropped": {"stocks": [], "flows": []}}
    stocks = {s.id for s in model.stocks}
    for s in prior.stocks:
        if s.id in stocks:
            continue
        if keep:
            c = copy.deepcopy(s)
            c.evidence = {**c.evidence, "prior": {"era": era, "why": "not yet found in this era"}}
            model.stocks.append(c)
            stocks.add(s.id)
            report["carried"]["stocks"].append(s.id)
        else:
            report["dropped"]["stocks"].append(s.id)
    before = {f.id: f for f in prior.flows}
    for f in model.flows:
        p = before.get(f.id)
        e, pe = f.current(), p.current() if p else None
        if not e or not pe or not pe.params:
            continue
        n = _events(e)
        if _same_form(e, pe):
            w = min(PRIOR_EVENTS, _events(pe) or PRIOR_EVENTS)
            own = dict(e.params)
            e.params = {k: round((w * pe.params[k] + n * v) / (w + n), 6) for k, v in own.items()}
            e.prior = {"era": era, "weight": round(w / (w + n), 4), "params": dict(pe.params), "own": own, "events": w}
            report["blended"].append(f.id)
        elif n < MIN_EVENTS:
            f.equations[-1] = _carried(pe, era, f"this era's {n:g} events are too few to choose a form; the prior's {pe.form} stands")
            report["carried"]["flows"].append(f.id)
    flows = {f.id for f in model.flows}
    for p in prior.flows:
        if p.id in flows:
            continue
        ends_ok = all(x is None or x in stocks for x in (p.src, p.dst))
        if keep and ends_ok:
            c = copy.deepcopy(p)
            c.equations = [_carried(e, era, "not yet found in this era") for e in c.equations[-1:]]
            c.evidence = {**c.evidence, "prior": {"era": era, "why": "not yet found in this era"}}
            model.flows.append(c)
            flows.add(p.id)
            report["carried"]["flows"].append(p.id)
        else:
            report["dropped"]["flows"].append(p.id)
    carried = set(report["carried"]["flows"])
    mine = {m.id: m for m in model.machines}
    for m in prior.machines:
        theirs = [fid for fid in m.attributed if fid in carried]
        if not theirs:
            continue
        if m.id in mine:
            mine[m.id].attributed = list(dict.fromkeys([*mine[m.id].attributed, *theirs]))
        else:
            model.machines.append(Machine(m.id, m.name, m.kind, m.description, theirs, list(m.observed_by), m.bootstrap))
    model.discovery["prior"] = report
    return model


def rests_on_prior(e: Equation | None) -> bool:
    """Whether an equation is the prior's alone: nothing of this era's evidence is in it."""
    return bool(e) and e.origin == PRIOR
