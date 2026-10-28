"""The operations on an experiment's draft, each checked, applied as one batch or not at all.

Every edit is an object with ``op``:

| op | fields | what it does |
|---|---|---|
| ``add_flow`` | ``id``, ``from``, ``to`` (a stock id, or null for outside), ``equation``, ``params``, ``name`` | a new flow |
| ``replace_flow`` | ``id``, ``equation``, ``params``, and optionally ``from``, ``to`` | the flow's whole equation (and ends) |
| ``remove_flow`` | ``id`` | the flow is gone |
| ``set_params`` | ``flow``, ``params`` | some of the flow's parameters, by name |
| ``add_stock`` | ``id``, ``initial`` (default 0), ``name``, ``unit`` | a hidden stock: no series measures it |
| ``remove_stock`` | ``id`` | the stock is gone (no flow may still end at it or read it) |
| ``set_level`` | ``stock``, ``level`` (null to clear) | where a forward run starts the stock |
| ``set_input`` | ``input``, ``scenario`` | what a forward run assumes of an input (below) |
| ``load_model`` | ``model`` | the whole draft: ``{"stocks": [{id, initial?}], "flows": [{id, from, to, equation, params}]}``, or a model as Orchestra writes it |

An input's ``scenario``, from the start of a forward run: ``{"kind": "hold"}`` (its last measured
value; the default), ``{"kind": "value", "value": v}``, ``{"kind": "scale", "factor": r}`` (its last
value times r), ``{"kind": "step", "at_s": s, "value": v}`` (held until s seconds in, then v),
``{"kind": "ramp", "to_s": s, "value": v}`` (straight from its last value to v at s seconds, then
held), or ``{"kind": "series", "points": [[s, v], …]}`` (seconds from the start, held between).

**Checked.** Each edit is checked as it is applied, against the draft as the batch has made it so
far: ids known (or new, for an add), ends that are stocks, equations that parse and read only the
draft's stocks, the measured inputs (and inputs a scenario defines), and their own parameters. At
the end the whole draft is checked again (no flow may end at or read a stock the batch removed,
ids once each, every equation parses), so the edits of a batch may come in any order that leaves
the draft whole. The first failure refuses the whole batch, saying
which edit and why; the draft is left as it was.

**Origins** (AGENTS.md rule 6). An equation written by an edit is ``declared``, with method
``experiment <id> by <source>``. One a ``load_model`` writes identically to the base's keeps the
base's own (its fit). A stock an edit adds is hidden (``evidence.hidden``), with its initial level
and the experiment that added it."""

from __future__ import annotations

import copy
import math
import re

from ..model import Flow, Model, Stock
from .forms import Names, equation_of, flow_text, measured_inputs
from .language import EquationError, parse

MAX_EDITS = 256
MAX_ID = 256
ID = re.compile(r"^[\x21-\x7e]+$")
KINDS = {"hold": (), "value": ("value",), "scale": ("factor",), "step": ("at_s", "value"), "ramp": ("to_s", "value"),
         "series": ("points",)}
OPS = {"add_flow": {"id", "from", "to", "equation", "params", "name"}, "replace_flow": {"id", "equation", "params", "from", "to"},
       "remove_flow": {"id"}, "set_params": {"flow", "params"}, "add_stock": {"id", "initial", "name", "unit"},
       "remove_stock": {"id"}, "set_level": {"stock", "level"}, "set_input": {"input", "scenario"}, "load_model": {"model"}}


class EditError(ValueError):
    def __init__(self, message: str, index: int | None = None):
        super().__init__(message)
        self.index = index


def _id(v, what: str) -> str:
    if not isinstance(v, str) or not ID.match(v) or len(v) > MAX_ID:
        raise EditError(f"{what} must be an id: a non-empty string of printable characters without spaces (at most {MAX_ID})")
    return v


def _num(v, what: str) -> float:
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        raise EditError(f"{what} must be a finite number, not {v!r}")
    return float(v)


class Draft:
    """A draft model and its scenario, being edited by ``source`` in experiment ``eid``;
    ``known_inputs`` are the inputs measured in the base."""

    def __init__(self, model: Model, scenario: dict, base: Model, eid: str, source: str):
        self.model = copy.deepcopy(model)
        self.scenario = copy.deepcopy(scenario or {})
        self.scenario.setdefault("inputs", {})
        self.scenario.setdefault("levels", {})
        self.base = base
        self.eid, self.source = eid, source
        self.measured = measured_inputs(base)

    @property
    def method(self) -> str:
        return f"experiment {self.eid} by {self.source}"

    def inputs(self) -> list[str]:
        return list(dict.fromkeys([*self.measured, *self.scenario["inputs"]]))

    def names(self) -> Names:
        return Names([s.id for s in self.model.stocks], self.inputs())

    def stock_ids(self) -> set[str]:
        return {s.id for s in self.model.stocks}

    def flow(self, fid: str) -> Flow:
        f = next((x for x in self.model.flows if x.id == fid), None)
        if f is None:
            raise EditError(f"no flow {fid} in the draft; its flows: {', '.join(x.id for x in self.model.flows) or 'none'}")
        return f

    def equation(self, text, params):
        n = self.names()
        try:
            return equation_of(parse(text, stocks=n.stocks, inputs=n.inputs, params=params), self.method)
        except EquationError as e:
            raise EditError(f"equation: {e}") from None

    def end(self, v, what: str) -> str | None:
        if v is None:
            return None
        _id(v, what)
        if v not in self.stock_ids():
            raise EditError(f"{what}: no stock {v} in the draft (null for outside); its stocks: {', '.join(sorted(self.stock_ids()))}")
        return v

    # ---- the operations
    def add_flow(self, e: dict) -> None:
        fid = _id(e.get("id"), "id")
        if any(f.id == fid for f in self.model.flows):
            raise EditError(f"flow {fid} is already in the draft: replace_flow changes it")
        src, dst = self.end(e.get("from"), "from"), self.end(e.get("to"), "to")
        self._ends(src, dst)
        eq = self.equation(e.get("equation"), e.get("params"))
        name = e.get("name") if isinstance(e.get("name"), str) and e["name"].strip() else fid.replace("_", " ")
        self.model.flows.append(Flow(fid, name[:MAX_ID], src, dst, None, [eq], [], {"experiment": self.eid}))

    def replace_flow(self, e: dict) -> None:
        f = self.flow(_id(e.get("id"), "id"))
        src = self.end(e["from"], "from") if "from" in e else f.src
        dst = self.end(e["to"], "to") if "to" in e else f.dst
        self._ends(src, dst)
        eq = self.equation(e.get("equation"), e.get("params"))
        f.src, f.dst = src, dst
        f.equations = [*f.equations, eq][-4:]

    def remove_flow(self, e: dict) -> None:
        f = self.flow(_id(e.get("id"), "id"))
        self.model.flows.remove(f)
        for m in self.model.machines:
            m.attributed = [x for x in m.attributed if x != f.id]

    def set_params(self, e: dict) -> None:
        f = self.flow(_id(e.get("flow"), "flow"))
        if not isinstance(e.get("params"), dict) or not e["params"]:
            raise EditError("params: an object of the parameters to set, by name")
        text, params = flow_text(f, self.names())
        if unknown := sorted(set(e["params"]) - set(params)):
            raise EditError(f"flow {f.id} has no parameter {', '.join(unknown)}; its equation is {text!r} with "
                            f"{', '.join(sorted(params)) or 'no parameters'}")
        new = {**params, **{k: _num(v, f"params.{k}") for k, v in e["params"].items()}}
        f.equations = [*f.equations, self.equation(text, new)][-4:]

    def add_stock(self, e: dict) -> None:
        sid = _id(e.get("id"), "id")
        if sid in self.stock_ids():
            raise EditError(f"stock {sid} is already in the draft")
        if sid in self.inputs():
            raise EditError(f"{sid} is a measured input's name: a stock needs another")
        initial = _num(e.get("initial", 0.0), "initial")
        if initial < 0:
            raise EditError("initial: a stock's level is at least 0")
        name = e.get("name") if isinstance(e.get("name"), str) and e["name"].strip() else sid.replace("_", " ")
        unit = e.get("unit") if isinstance(e.get("unit"), str) and e["unit"].strip() else "items"
        self.model.stocks.append(Stock(sid, name[:MAX_ID], unit[:64], None,
                                       {"hidden": True, "initial": initial, "experiment": self.eid, "by": self.source}))

    def remove_stock(self, e: dict) -> None:
        sid = _id(e.get("id"), "id")
        st = next((s for s in self.model.stocks if s.id == sid), None)
        if st is None:
            raise EditError(f"no stock {sid} in the draft")
        if ends := [f.id for f in self.model.flows if sid in (f.src, f.dst)]:
            raise EditError(f"stock {sid} is an end of flow{'s' if len(ends) > 1 else ''} {', '.join(ends)}: remove or move them first")
        self.model.stocks.remove(st)
        self.scenario["levels"].pop(sid, None)

    def set_level(self, e: dict) -> None:
        sid = _id(e.get("stock"), "stock")
        if sid not in self.stock_ids():
            raise EditError(f"no stock {sid} in the draft")
        if e.get("level") is None:
            self.scenario["levels"].pop(sid, None)
            return
        v = _num(e["level"], "level")
        if v < 0:
            raise EditError("level: a stock's level is at least 0")
        self.scenario["levels"][sid] = v

    def set_input(self, e: dict) -> None:
        name = _id(e.get("input"), "input")
        if name in self.stock_ids():
            raise EditError(f"{name} is a stock, not an input")
        sc = e.get("scenario")
        if not isinstance(sc, dict) or sc.get("kind") not in KINDS:
            raise EditError(f"scenario: an object with kind, one of {', '.join(KINDS)}")
        if extra := sorted(set(sc) - {"kind", *KINDS[sc["kind"]]}):
            raise EditError(f"scenario {sc['kind']}: unknown field{'s' if len(extra) > 1 else ''} {', '.join(extra)}")
        out = {"kind": sc["kind"]}
        for k in KINDS[sc["kind"]]:
            if k not in sc:
                raise EditError(f"scenario {sc['kind']} needs {k}")
            if k == "points":
                pts = sc["points"]
                if not isinstance(pts, list) or not 1 <= len(pts) <= 10_000 or not all(isinstance(p, list) and len(p) == 2 for p in pts):
                    raise EditError("scenario series: points are [[seconds from the start, value], ...], 1 to 10000 of them")
                out["points"] = sorted([_num(a, "a point's time"), _num(b, "a point's value")] for a, b in pts)
            else:
                out[k] = _num(sc[k], f"scenario.{k}")
        if name not in self.measured and sc["kind"] in ("hold", "scale", "ramp"):
            raise EditError(f"{name} is not measured, so it has no last value to {sc['kind']}: give it a value, a step or a series")
        if sc["kind"] == "hold" and name in self.measured:
            self.scenario["inputs"].pop(name, None)
        else:
            self.scenario["inputs"][name] = out

    def load_model(self, e: dict) -> None:
        m = e.get("model")
        if not isinstance(m, dict) or not isinstance(m.get("stocks"), list) or not isinstance(m.get("flows"), list):
            raise EditError("model: {\"stocks\": [...], \"flows\": [...]}")
        if m["flows"] and isinstance(m["flows"][0], dict) and "equations" in m["flows"][0]:
            m = self._simple(m)
        base_stocks = {s.id: s for s in self.base.stocks}
        base_flows = {f.id: f for f in self.base.flows}
        bn = Names.of(self.base)
        self.model.stocks, self.model.flows = [], []
        for i, s in enumerate(m["stocks"]):
            if not isinstance(s, dict):
                raise EditError(f"model.stocks[{i}]: an object with id")
            sid = _id(s.get("id"), f"model.stocks[{i}].id")
            if sid in base_stocks and not (base_stocks[sid].evidence or {}).get("hidden") and "initial" not in s:
                self.model.stocks.append(copy.deepcopy(base_stocks[sid]))
            else:
                self.add_stock({k: v for k, v in s.items() if k in OPS["add_stock"]})
        for i, f in enumerate(m["flows"]):
            if not isinstance(f, dict):
                raise EditError(f"model.flows[{i}]: an object with id, from, to, equation and params")
            fid = _id(f.get("id"), f"model.flows[{i}].id")
            b = base_flows.get(fid)
            if b is not None and (b.src, b.dst) == (f.get("from"), f.get("to")) and _text(b, bn) == (f.get("equation"), f.get("params") or {}):
                self.model.flows.append(copy.deepcopy(b))           # as the base has it: its own origin
                continue
            self.add_flow({k: v for k, v in f.items() if k in OPS["add_flow"]})
            if b is not None:                                      # the base's flow, its equation declared anew
                new = self.model.flows[-1]
                new.name, new.counter, new.measured_by = b.name, b.counter, list(b.measured_by)
                new.evidence = {**b.evidence, "experiment": self.eid}
        keep = {f.id for f in self.model.flows}
        for mc in self.model.machines:
            mc.attributed = [x for x in mc.attributed if x in keep]
        for sid in list(self.scenario["levels"]):
            if sid not in self.stock_ids():
                self.scenario["levels"].pop(sid)

    def _simple(self, m: dict) -> dict:
        """A model as Orchestra writes it, in the simple form."""
        try:
            full = Model.from_json({"id": "loaded", "name": "loaded", **m})
        except (KeyError, TypeError, ValueError) as e:
            raise EditError(f"model: not a model as Orchestra writes it: {e}") from None
        n = Names.of(full, self.inputs())
        flows = []
        for f in full.flows:
            try:
                text, params = flow_text(f, n)
            except EquationError as e:
                raise EditError(f"model: flow {f.id}: {e}") from None
            flows.append({"id": f.id, "from": f.src, "to": f.dst, "equation": text, "params": params})
        return {"stocks": [{"id": s.id, **({"initial": float((s.evidence or {}).get("initial") or 0.0)} if (s.evidence or {}).get("hidden") else {})}
                           for s in full.stocks], "flows": flows}

    def _ends(self, src, dst) -> None:
        if src is None and dst is None:
            raise EditError("a flow has at least one end in a stock (from or to)")
        if src == dst:
            raise EditError("a flow from a stock to itself moves nothing")

    # ---- the batch
    def check(self) -> None:
        if errs := self.model.check():
            raise EditError("; ".join(errs))
        n = self.names()
        for f in self.model.flows:
            text, params = flow_text(f, n)
            try:
                parse(text, stocks=n.stocks, inputs=n.inputs, params=params)
            except EquationError as e:
                raise EditError(f"flow {f.id}: {e}") from None


def _text(f: Flow, names: Names) -> tuple[str, dict] | None:
    try:
        return flow_text(f, names)
    except EquationError:
        return None


def apply(model: Model, scenario: dict, base: Model, edits, eid: str, source: str) -> Draft:
    """The draft after every edit of the batch, or EditError (with the edit's ``index``) and
    nothing changed."""
    if not isinstance(edits, list) or not 1 <= len(edits) <= MAX_EDITS:
        raise EditError(f"edits: a list of 1 to {MAX_EDITS} edits")
    d = Draft(model, scenario, base, eid, source)
    for i, e in enumerate(edits):
        try:
            if not isinstance(e, dict) or e.get("op") not in OPS:
                raise EditError(f"an edit is an object with op, one of {', '.join(OPS)}")
            if extra := sorted(set(e) - {"op"} - OPS[e["op"]]):
                raise EditError(f"{e['op']}: unknown field{'s' if len(extra) > 1 else ''} {', '.join(extra)}")
            getattr(d, e["op"])(e)
        except (EditError, EquationError) as err:
            what = e.get("op") if isinstance(e, dict) else repr(e)
            raise EditError(f"edit {i} ({what}): {err}", i) from None
    try:
        d.check()
    except (EditError, EquationError) as err:
        raise EditError(f"after the batch: {err}") from None
    return d
