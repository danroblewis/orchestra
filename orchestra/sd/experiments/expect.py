"""Between an experiment and a prediction (goal G13): the expected edits a committed experiment
states, and the draft a prediction's expected edits make of a model.

**From an experiment** (``expectations``), each difference from the base (``views.diff``):

- a flow whose equation text is unchanged and only numbers of a classic form (``c``, ``k``)
  moved: ``{"flow", "param", "factor"}`` for each, judged by the era comparison's numbers;
- any other changed flow: ``{"flow", "equation", "params"}``, judged by its law;
- a removed flow: ``{"flow", "disappears": true}``;
- an added flow: ``{"from", "to", "appears": true, "equation", "params"}`` (its id is the
  experiment's, which discovery will not know);
- added and removed hidden stocks are not stated: no series measures them, so discovery could
  never find them appear or disappear. Their effect shows in the measured stocks' runs.

**Into a draft** (``draft``), for judging a prediction without its own trajectories: the
previous era's model with each expected edit that can be run applied (a factor on a rate or a
number, a removed flow, an equation, a new flow with an equation); an edit that does not apply to
that model (an unknown flow, an equation reading what it lacks) is left out and listed."""

from __future__ import annotations

import copy

from ..model import Flow, Model
from .forms import Names, equation_of, flow_text
from .language import EquationError, parse
from .views import diff

CLASSIC = {"c", "k"}


def expectations(base: Model, draft: Model, scenario: dict | None = None) -> list[dict]:
    d = diff(base, draft, scenario)
    out = []
    for row in d["flows"]["changed"]:
        a, b = row["before"], row["after"]
        if row["what"] == ["params"] and set(b["params"]) <= CLASSIC and all(a["params"].get(k) for k in b["params"]):
            for k in sorted(b["params"]):
                if b["params"][k] != a["params"][k]:
                    out.append({"flow": row["id"], "param": k, "factor": round(b["params"][k] / a["params"][k], 6)})
            continue
        out.append({"flow": row["id"], "equation": b["equation"], "params": dict(b["params"])})
    out += [{"flow": r["id"], "disappears": True} for r in d["flows"]["removed"]]
    out += [{"from": r["from"], "to": r["to"], "appears": True, "equation": r["equation"], "params": dict(r["params"])}
            for r in d["flows"]["added"]]
    return out


def draft(model: Model, expect: list[dict]) -> tuple[Model, list[dict]]:
    """``model`` with the expected edits that can be run (each in its checked shape,
    ``sd.predictions.expectation``), and those left out."""
    m = copy.deepcopy(model)
    left = []
    for e in expect:
        try:
            _apply(m, e)
        except (EquationError, KeyError, StopIteration, ValueError) as err:
            left.append({**e, "why": str(err)})
    return m, left


def _set(m: Model, f: Flow, text: str, params: dict) -> None:
    n = Names.of(m)
    f.equations = [*f.equations, equation_of(parse(text, stocks=n.stocks, inputs=n.inputs, params=params), "predicted")][-4:]


def _apply(m: Model, e: dict) -> None:
    k = e["kind"]
    if k == "factor":
        f = next(x for x in m.flows if x.id == e["flow"])
        text, params = flow_text(f, Names.of(m))
        if "param" in e:
            if e["param"] not in params:
                raise KeyError(f"flow {f.id} has no parameter {e['param']}")
            _set(m, f, text, {**params, e["param"]: params[e["param"]] * e["factor"]})
        else:
            _set(m, f, f"{e['factor']!r} * ({text})", params)
    elif k == "equation":
        f = next(x for x in m.flows if x.id == e["flow"])
        _set(m, f, e["equation"], e.get("params") or {})
    elif k == "disappears" and e.get("part") == "flow":
        m.flows = [x for x in m.flows if x.id != e["id"]]
    elif k == "appears" and e.get("part") == "flow" and e.get("id") is None and "equation" in e:
        ends = {s.id for s in m.stocks}
        if any(x is not None and x not in ends for x in (e["from"], e["to"])):
            raise KeyError("an end of the new flow is not in the model")
        n = Names.of(m)
        fid = f"predicted:{e['from'] or 'outside'}>{e['to'] or 'outside'}"
        m.flows.append(Flow(fid, fid, e["from"], e["to"], None,
                            [equation_of(parse(e["equation"], stocks=n.stocks, inputs=n.inputs, params=e.get("params") or {}), "predicted")]))
