"""A model as a machine reads it: each flow's equation in the language, what it reads, its origin
and whether to trust it; and a draft's difference from its base.

``model_view`` is what ``GET /model`` and an experiment's ``draft`` answer: compact enough for an
LLM's context (no series bindings, no discovery record unless asked), complete enough to write any
edit from."""

from __future__ import annotations

from ..model import Model
from ..trust import spread, weak_flow
from .forms import Names, flow_text, measured_inputs
from .history import hidden, initial
from .language import EquationError, parse


def flow_view(f, names: Names, *, trust: bool = True) -> dict:
    e = f.current()
    try:
        text, params = flow_text(f, names)
        reads = parse(text, stocks=names.stocks, inputs=names.inputs, params=params).describe()["reads"]
    except EquationError as err:
        text, params, reads = None, {}, {"error": str(err)}
    out = {"id": f.id, "name": f.name, "from": f.src, "to": f.dst, "equation": text, "params": params, "reads": reads,
           "origin": e.origin if e else None, "method": e.method if e else None,
           "measured": bool(f.counter or f.measured_by)}
    if e and e.quality.get("events") is not None:
        out["events"] = e.quality["events"]
    if trust:
        out["spread"] = round(spread(f)[0], 4)
        if why := weak_flow(f, e is None):
            out["not_trusted"] = why
    return out


def model_view(model: Model, label: dict | None = None, levels: dict | None = None, *, raw: bool = False,
               extra_inputs=()) -> dict:
    """The model with its equations in the language. ``levels``: each stock's level now
    (``{id: {"t", "v"}}`` or a number); ``raw``: with the model as Orchestra stores it."""
    names = Names.of(model, extra_inputs)
    stocks = []
    for s in model.stocks:
        row = {"id": s.id, "name": s.name, "unit": s.unit, "hidden": hidden(s)}
        if hidden(s):
            row["initial"] = initial(s)
        lv = (levels or {}).get(s.id)
        if lv is not None:
            row["level"] = lv["v"] if isinstance(lv, dict) else lv
        stocks.append(row)
    out = {"time_unit": model.time_unit, "era": model.era, **({"label": label} if label else {}),
           "stocks": stocks, "flows": [flow_view(f, names) for f in model.flows], "inputs": measured_inputs(model),
           "machines": [{"id": m.id, "kind": m.kind, "flows": list(m.attributed)} for m in model.machines if m.attributed]}
    from ..loops import loops
    out["loops"] = [{"id": lp["id"], "stocks": lp["stocks"]} for lp in loops(model)]
    if raw:
        out["raw"] = model.to_json()
    return out


def _flow_row(f, names: Names) -> dict:
    try:
        text, params = flow_text(f, names)
    except EquationError:
        text, params = None, {}
    e = f.current()
    return {"from": f.src, "to": f.dst, "equation": text, "params": params, "origin": e.origin if e else None,
            "method": e.method if e else None}


def diff(base: Model, draft: Model, scenario: dict | None = None) -> dict:
    """What the draft changed of its base: stocks added and removed, flows added, removed and
    changed (ends, equation or parameters), and the scenario."""
    bn, dn = Names.of(base), Names.of(draft, list((scenario or {}).get("inputs") or {}))
    bs, ds = {s.id: s for s in base.stocks}, {s.id: s for s in draft.stocks}
    bf, df = {f.id: f for f in base.flows}, {f.id: f for f in draft.flows}
    changed = []
    for fid in [f.id for f in draft.flows if f.id in bf]:
        a, b = _flow_row(bf[fid], bn), _flow_row(df[fid], dn)
        if (a["from"], a["to"], a["equation"], a["params"]) != (b["from"], b["to"], b["equation"], b["params"]):
            what = [k for k in ("from", "to", "equation") if a[k] != b[k]]
            if a["equation"] == b["equation"] and a["params"] != b["params"]:
                what.append("params")
            changed.append({"id": fid, "what": what, "before": a, "after": b})
    out = {"stocks": {"added": [{"id": s.id, "initial": initial(s)} for s in draft.stocks if s.id not in bs],
                      "removed": [s for s in bs if s not in ds]},
           "flows": {"added": [{"id": f.id, **_flow_row(f, dn)} for f in draft.flows if f.id not in bf],
                     "removed": [{"id": f.id, **_flow_row(f, bn)} for f in base.flows if f.id not in df],
                     "changed": changed},
           "scenario": scenario or {"inputs": {}, "levels": {}}}
    out["edits"] = len(out["stocks"]["added"]) + len(out["stocks"]["removed"]) + sum(len(v) for v in out["flows"].values())
    return out
