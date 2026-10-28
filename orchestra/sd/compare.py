"""Two models compared: what changed at an era's boundary (goal G11), and which parts a structure
change added or removed (goal G12).

``compare(before, after)``, with ``before`` the previous era's model and ``after`` the new era's:

- **stocks, flows and loops** (``sd.loops``) present in only one: ``appeared`` or
  ``disappeared`` at the boundary. A part the new era carries from its prior (``sd.prior``) is
  neither: it is ``carried``, not yet found in the era;
- **each flow in both**: ``form changed`` (another equation form, or reading other stocks), or,
  for each of its numbers, before and after with their standard errors and ``z``, the difference
  over its standard error. ``after`` is the era's own number (before the prior is blended in), so
  the comparison weighs the era's evidence alone. The flow ``changed`` when any number's ``|z|``
  is at least ``Z``, else ``unchanged``; ``carried`` when the era has not found it yet, and
  ``prior`` when it has, on too few events to fit its form.

A number's standard error is its relative spread (``sd.trust.spread``: from the events it was
fitted on, the fit's dispersion or standard error) times the number. This is the comparison the
intended-effect test (G13) judges a prediction against."""

from __future__ import annotations

import copy
import math

from .loops import loops
from .model import Model
from .prior import rests_on_prior
from .trust import spread

Z = 2.0


def ids(model: Model) -> dict[str, list[str]]:
    """The model's parts by id: its stocks, flows and loops."""
    return {"stocks": sorted(s.id for s in model.stocks), "flows": sorted(f.id for f in model.flows),
            "loops": [x["id"] for x in loops(model)]}


def diff(before: dict[str, list[str]], after: dict[str, list[str]]) -> dict:
    """What ``after`` added and removed, of each kind; empty lists when nothing."""
    return {"added": {k: sorted(set(after.get(k, [])) - set(before.get(k, []))) for k in ("stocks", "flows", "loops")},
            "removed": {k: sorted(set(before.get(k, [])) - set(after.get(k, []))) for k in ("stocks", "flows", "loops")}}


def _carried(model: Model) -> tuple[set[str], set[str]]:
    return ({s.id for s in model.stocks if "prior" in (s.evidence or {})},
            {f.id for f in model.flows if rests_on_prior(f.current())})


def compare(before: Model, after: Model) -> dict:
    carried_s, carried_f = _carried(after)
    b, a = ids(before), ids(after)
    own_after = {k: [x for x in v if x not in carried_s and x not in carried_f] for k, v in a.items()}
    d = diff(b, own_after)
    out = {"from": before.era, "to": after.era,
           "stocks": {"appeared": d["added"]["stocks"], "disappeared": sorted(set(b["stocks"]) - set(a["stocks"])),
                      "carried": sorted(carried_s)},
           "loops": {"appeared": sorted(set(a["loops"]) - set(b["loops"])), "disappeared": sorted(set(b["loops"]) - set(a["loops"]))},
           "flows": []}
    prev = {f.id: f for f in before.flows}
    for f in after.flows:
        p = prev.get(f.id)
        if p is None:
            out["flows"].append({"id": f.id, "status": "carried" if f.id in carried_f else "appeared"})
            continue
        e, pe = f.current(), p.current()
        if "prior" in (f.evidence or {}):
            out["flows"].append({"id": f.id, "status": "carried", "why": "not yet found in this era"})
            continue
        if rests_on_prior(e) or e is None or pe is None:
            out["flows"].append({"id": f.id, "status": "prior", "why": "no evidence of its own in this era yet"})
            continue
        if e.form != pe.form or list(e.inputs) != list(pe.inputs):
            out["flows"].append({"id": f.id, "status": "form changed", "before": {"form": pe.form, "inputs": pe.inputs},
                                 "after": {"form": e.form, "inputs": e.inputs}})
            continue
        own = copy.deepcopy(f)
        own.current().params = dict((e.prior or {}).get("own") or e.params)
        rb, ra = spread(p)[0], spread(own)[0]
        nums = []
        for k in sorted(set(pe.params) & set(own.current().params)):
            x0, x1 = pe.params[k], own.current().params[k]
            s0, s1 = abs(x0) * rb, abs(x1) * ra
            se = math.hypot(s0, s1)
            z = (x1 - x0) / se if se > 0 else (0.0 if x1 == x0 else math.inf)
            nums.append({"param": k, "before": x0, "after": x1, "se_before": round(s0, 6), "se_after": round(s1, 6),
                         "z": round(z, 2) if math.isfinite(z) else None,
                         "ratio": round(x1 / x0, 4) if x0 else None})
        changed = any(n["z"] is None or abs(n["z"]) >= Z for n in nums)
        out["flows"].append({"id": f.id, "status": "changed" if changed else "unchanged", "params": nums,
                             "events_before": (pe.quality or {}).get("events"), "events_after": (e.quality or {}).get("events")})
    out["flows"] += [{"id": fid, "status": "disappeared"} for fid in sorted(set(prev) - {f.id for f in after.flows})]
    return out
