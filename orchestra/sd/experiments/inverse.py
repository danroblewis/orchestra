"""The inverse run (goal-seek): "if we ran this window again but X were different, what else would
have had to be true?" The caller names targets over a past window and what must hold; the solver
finds the smallest set of changes to the model's equations under which a replay of the window
(``replay``: its measured inputs, from its measured levels at the start) meets the targets.

**Targets** (each over the whole window, on the replay):

- ``{"stock": S, "scale": r}``: S's mean level r times the base replay's;
- ``{"stock": S, "level": x}``: S's mean level x;
- ``{"stock": S, "below": x}`` / ``{"stock": S, "above": x}``: S's highest (lowest) level;
- ``{"flow": F, "scale": r}``: what F moved over the window, r times the base replay's;
- ``{"flow": F, "total": x}``: F moved x.

A scale is of the base replay, not of the measurement, so the model's own error on the window
cancels; the base replay's and the measured values are both reported. A target is met within
``TOL`` (5%); a bound exactly.

**Holds**: ``{"flow": F}`` keeps F's equation as it is (it is no candidate); ``{"series": X}``
keeps X's history: a stock's mean level, or what a flow moved, within ``TOL`` of the base replay's.

**Candidates.** Each number of each equation not held, as a factor on its value (one change), and
each whole rate of more than one number, as a factor on the rate (one change); with
``new_flows``, for each target stock, a new constant inflow from outside and a new outflow
proportional to it (one change each, preferred after a change of a number at the same count).
Numbers that are 0 are no candidates (a factor on 0 is 0).

**The method.** Greedy forward selection, which is how the smallest set is sought: from no
change, every candidate is tried alone at ``GRID`` values of its factor (1/10 to 10, log-spaced; a
new flow's number from 0 to a few times what the stock's flows carry), all in one batch of the
engine (one column each); the best is kept and refined (a finer grid around it, coordinate by
coordinate, ``PASSES`` times), then the next is tried alongside it, and so on, until every target
is met and every hold kept, or ``max_changes`` are used. The loss is the sum of each target's and
hold's relative miss over ``TOL``, squared (a bound's only when it is crossed). Changing fewer
numbers is preferred over meeting the targets more closely: the count is the penalty, and the base
is the prior (decision D4), so a number moves only when it must.

**What it returns**: whether the targets were reached (or the best approach, and how far it
fell short: **unreachable**); the changes (each flow, number, base value, solved value, factor);
the **side effects**: every stock and flow the targets do not name whose replay mean or total moved
by more than ``SIDE`` (5%) from the base replay's, with how much: what would also have had to be
different; **alternatives**: other sets of the same size that reach the targets (or come within
``ALT`` of the best loss), the cheap evidence of ambiguity; and the **uniqueness check**
(``uniqueness``): the base and the solved model each fabricate the window's data
(``fabricate``), ordinary discovery (conservation, ``sd.discover``) is run on both, and each
flow's law is tested as a verdict tests a form change (``sd.verdict``): the factual model's
equation, on the counterfactual data, against the counterfactual model's own (``replay.one_step``;
a deviance ``LAW_GAIN`` worse is a law that changed). The flows whose laws changed should be the
solved changes. A solved change discovery does not see (``missed``), or a
change it sees that was not solved (``extra``), says the data would not tell this solution from
another. ``ambiguous`` is true when an alternative reaches the targets or the check disagrees.

**Limits, honestly.** Greedy selection is not exhaustive: a pair of changes that only work
together, neither helping alone, is not found (the search looks one change ahead). Factors are
searched between 1/10 and 10. The replay is deterministic (the central run), so a target within
the noise of the window is "met" by changes the data could not show; the uniqueness check is
what says so. A new hidden stock is not a candidate yet (add one by an edit, and the solver
tunes its flows). It optimises the targets it is given: anything not targeted or held may move,
and does (the side effects say how much), so a solution that meets a target by an unintended but
acceptable side effect is reported, not avoided; hold what must not move. The search stops at
``deadline_s`` with the best found so far (``stopped``)."""

from __future__ import annotations

import copy
import math
import time
from dataclasses import dataclass, field

import numpy as np

from ..model import Equation, Flow, Model
from . import engine
from .forms import Names, flow_text
from .forms import equation_of as _equation_of
from .history import levels_at, step_for, unit_s
from .language import parse
from .replay import central, window_of

TOL = 0.05
SIDE = 0.05
ALT = 1.25
GRID = 41
FINE = 15
PASSES = 3
COLUMNS = 256         # columns per batch of the engine; the deadline is checked between batches
STRUCTURE = 0.5        # a new flow counts this much more than a changed number, to break ties
SPAN = (0.1, 10.0)
LAW_GAIN = 9.0         # a deviance this much worse (three standard errors on one number) is a law that changed


class InverseError(ValueError):
    pass


class Late(Exception):
    """The deadline passed during a batch of runs."""


@dataclass
class Candidate:
    key: str                       # flow:param, flow:*rate, or new:<flow id>
    flow: str
    param: str | None              # None: the whole rate
    base: float
    new: dict | None = None        # a new flow: id, from, to, equation, param
    grid: np.ndarray = field(default_factory=lambda: np.array([]))

    @property
    def structural(self) -> bool:
        return self.new is not None

    def value(self, factor: float) -> float:
        return factor if self.structural else self.base * factor


def _targets(targets, stocks: set[str], flows: set[str]) -> list[dict]:
    if not isinstance(targets, list):
        raise InverseError("targets: a list")
    out = []
    for i, t in enumerate(targets):
        if not isinstance(t, dict) or ("stock" in t) == ("flow" in t):
            raise InverseError(f"targets[{i}]: an object naming one stock or one flow")
        part = "stock" if "stock" in t else "flow"
        ident = t[part]
        if ident not in (stocks if part == "stock" else flows):
            raise InverseError(f"targets[{i}]: no {part} {ident!r} in the model")
        allowed = ("scale", "level", "below", "above") if part == "stock" else ("scale", "total")
        kinds = [k for k in t if k != part]
        if len(kinds) != 1 or kinds[0] not in allowed:
            raise InverseError(f"targets[{i}]: one of {', '.join(allowed)} for a {part}")
        v = t[kinds[0]]
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or (kinds[0] == "scale" and v < 0):
            raise InverseError(f"targets[{i}]: {kinds[0]} must be a finite number{' at least 0' if kinds[0] == 'scale' else ''}")
        out.append({"part": part, "id": ident, "kind": kinds[0], "value": float(v), "hold": False})
    return out


def _holds(hold, stocks: set[str], flows: set[str]) -> tuple[list[dict], set[str]]:
    """What must hold: ``{"flow": F}`` keeps F's equation (it is no candidate); ``{"series": X}``
    (or ``{"stock": S}``) keeps X's history: a stock's mean level or what a flow moved, within TOL
    of the base replay's."""
    if not isinstance(hold, list):
        raise InverseError("hold: a list")
    kept, equations = [], set()
    for i, h in enumerate(hold):
        if not isinstance(h, dict) or len(h) != 1 or next(iter(h)) not in ("flow", "series", "stock"):
            raise InverseError(f"hold[{i}]: {{\"flow\": F}} (its equation stays), or {{\"series\": X}} (a stock's or flow's history stays)")
        (k, x), = h.items()
        if k == "flow":
            if x not in flows:
                raise InverseError(f"hold[{i}]: no flow {x!r} in the model")
            equations.add(x)
            continue
        if x not in stocks and x not in flows:
            raise InverseError(f"hold[{i}]: no stock or flow {x!r} in the model")
        kept.append({"part": "stock" if x in stocks else "flow", "id": x, "kind": "scale", "value": 1.0, "hold": True})
    return kept, equations


def candidates(model: Model, held_flows: set[str], target_stocks: list[str], history: dict, new_flows: bool) -> list[Candidate]:
    names = Names.of(model)
    out = []
    for f in model.flows:
        if f.id in held_flows:
            continue
        text, params = flow_text(f, names)
        nonzero = {k: v for k, v in params.items() if v != 0}
        for k, v in nonzero.items():
            out.append(Candidate(f"{f.id}:{k}", f.id, k, v))
        if len(params) > 1 or text.strip() == "observed()":
            out.append(Candidate(f"{f.id}:*rate", f.id, None, 1.0))
    grid = np.exp(np.linspace(math.log(SPAN[0]), math.log(SPAN[1]), GRID))
    for c in out:
        c.grid = grid
    if new_flows:
        unit = unit_s(model)
        for sid in target_stocks:
            moved = sum(abs(v) for f in model.flows if sid in (f.src, f.dst) for _, v in (history.get("flows") or {}).get(f.id) or [])
            n = sum(len((history.get("flows") or {}).get(f.id) or []) for f in model.flows if sid in (f.src, f.dst)) or 1
            pts = [v for _, v in (history.get("stocks") or {}).get(sid) or []]
            level = max(1.0, sum(pts) / len(pts)) if pts else 1.0
            rate = max(moved / n, level / (3600.0 / unit))          # what its flows carry, per time unit
            ref = names.ref(sid)
            fin, fout = f"{sid}_inflow_found", f"{sid}_outflow_found"
            out.append(Candidate(f"new:{fin}", fin, "c", 0.0, {"id": fin, "from": None, "to": sid, "equation": "c", "param": "c"},
                                 np.concatenate([[0.0], np.exp(np.linspace(math.log(rate / 100), math.log(rate * 4), GRID - 1))])))
            k = rate / level
            out.append(Candidate(f"new:{fout}", fout, "k", 0.0, {"id": fout, "from": sid, "to": None, "equation": f"k * {ref}", "param": "k"},
                                 np.concatenate([[0.0], np.exp(np.linspace(math.log(k / 100), math.log(k * 4), GRID - 1))])))
    return out


def _with_new(model: Model, cands: list[Candidate]) -> Model:
    m = copy.deepcopy(model)
    for c in cands:
        if c.structural:
            p = parse(c.new["equation"], stocks=[s.id for s in m.stocks], inputs=Names.of(m).inputs, params={c.new["param"]: 0.0})
            m.flows.append(Flow(c.new["id"], c.new["id"].replace("_", " "), c.new["from"], c.new["to"], None,
                                [_equation_of(p, "inverse candidate")], [], {"inverse": True}))
    return m


class Problem:
    """The window, the targets and holds, and the batched replay of any set of changes."""

    def __init__(self, model: Model, history: dict, targets: list[dict], cands: list[Candidate], start: float, end: float,
                 step_s: float):
        self.model = _with_new(model, cands)
        self.history = history
        self.targets = targets
        self.cands = cands
        self.start, self.end, self.step_s = start, end, step_s
        self.flows = engine.compiled(self.model)
        self.fids = [f.id for f in self.flows]
        self.sids = [s.id for s in self.model.stocks]
        self.unit = unit_s(model)
        self.levels = levels_at(self.model, history, start)[0]
        self.evals = 0
        self.deadline: float | None = None
        base = self.run([{}])
        self.base_means, self.base_totals = base["means"][0], base["totals"][0]
        self.base_max, self.base_min = base["max"][0], base["min"][0]

    def run(self, columns: list[dict[str, float]]) -> dict:
        """The replay of each column (``{candidate key: factor}``), in batches: each stock's mean,
        highest and lowest level and each flow's total."""
        out = {"means": [], "totals": [], "max": [], "min": []}
        for i in range(0, len(columns), COLUMNS):
            if self.deadline is not None and time.monotonic() > self.deadline:
                raise Late
            chunk = columns[i:i + COLUMNS]
            M = len(chunk)
            params: dict[str, dict] = {}
            factors: dict[str, np.ndarray] = {}
            for c in self.cands:
                vals = [col.get(c.key) for col in chunk]
                if all(v is None for v in vals):
                    continue
                if c.param is None:
                    factors[c.flow] = np.array([1.0 if v is None else v for v in vals])
                else:
                    params.setdefault(c.flow, {})[c.param] = np.array([c.base if v is None else c.value(v) for v in vals])
            r = central(self.model, self.history, self.start, self.end, step_s=self.step_s, flows=self.flows, columns=M,
                        params=params, factors=factors, levels=self.levels)
            self.evals += M
            out["means"] += list(r.levels.mean(axis=2))
            out["max"] += list(r.levels.max(axis=2))
            out["min"] += list(r.levels.min(axis=2))
            out["totals"] += list(r.rates.sum(axis=2) * (self.step_s / self.unit))
        return out

    def goal(self, t: dict) -> float:
        if t["kind"] == "scale":
            base = self.base_means[self.sids.index(t["id"])] if t["part"] == "stock" else self.base_totals[self.fids.index(t["id"])]
            return t["value"] * base
        return t["value"]

    def misses(self, res: dict, j: int) -> list[float]:
        """Each target's relative miss in column ``j`` (0 when a bound holds)."""
        out = []
        for t in self.targets:
            g = self.goal(t)
            if t["part"] == "stock":
                k = self.sids.index(t["id"])
                v = res["max"][j][k] if t["kind"] == "below" else res["min"][j][k] if t["kind"] == "above" else res["means"][j][k]
            else:
                v = res["totals"][j][self.fids.index(t["id"])]
            scale = max(abs(g), 1e-6)
            if t["kind"] == "below":
                out.append(float(max(0.0, v - g) / scale))
            elif t["kind"] == "above":
                out.append(float(max(0.0, g - v) / scale))
            else:
                out.append(float((v - g) / scale))
        return out

    def loss(self, res: dict) -> np.ndarray:
        return np.array([sum((m / TOL) ** 2 for m in self.misses(res, j)) for j in range(len(res["means"]))])

    def met(self, res: dict, j: int) -> bool:
        return bool(all(abs(m) <= TOL * (1 + 1e-9) if t["kind"] not in ("below", "above") else m <= 1e-9
                        for t, m in zip(self.targets, self.misses(res, j))))


def _cost(support: dict, cands: dict[str, Candidate]) -> float:
    return sum(1 + (STRUCTURE if cands[k].structural else 0.0) for k in support)


def _refine(p: Problem, support: dict[str, float], deadline: float) -> tuple[dict[str, float], float]:
    """The support's factors refined coordinate by coordinate on a finer grid around each."""
    by = {c.key: c for c in p.cands}
    best = dict(support)
    try:
        loss = float(p.loss(p.run([best]))[0])
    except Late:
        return best, math.inf
    try:
        _passes(p, by, best, loss, deadline, out := {})
    except Late:
        pass
    return out.get("best", best), out.get("loss", loss)


def _passes(p: Problem, by: dict, best: dict, loss: float, deadline: float, out: dict) -> None:
    out.update(best=best, loss=loss)
    for ps in range(PASSES):
        for key in list(best):
            if time.monotonic() > deadline:
                return
            c = by[key]
            x = best[key]
            if c.structural:
                hi = max(x * 2, (c.grid[1] if len(c.grid) > 1 else 1.0))
                vals = np.linspace(max(0.0, x - (hi - x) / (ps + 1)), x + (hi - x) / (ps + 1), FINE)
            else:
                w = math.log(SPAN[1] / SPAN[0]) / (GRID - 1) * 2 / (ps + 1)
                vals = np.exp(np.linspace(math.log(x) - w, math.log(x) + w, FINE)) if x > 0 else np.linspace(0, 2, FINE)
            cols = [{**best, key: float(v)} for v in vals]
            ls = p.loss(p.run(cols))
            j = int(np.argmin(ls))
            if ls[j] < loss:
                best, loss = cols[j], float(ls[j])
                out.update(best=best, loss=loss)


def solve(model: Model, history: dict, targets: list, *, hold: list | None = None, start: float | None = None,
          end: float | None = None, step_s: float | None = None, new_flows: bool = False, max_changes: int = 3,
          deadline_s: float = 60.0, alternatives: int = 3) -> dict:
    """The smallest set of changes found (see above), with what it implies. The changes are
    applied to ``model`` by ``apply``."""
    began = time.monotonic()
    deadline = began + max(1.0, float(deadline_s))
    start, end = window_of(history, start, end)
    if not isinstance(max_changes, int) or not 1 <= max_changes <= 8:
        raise InverseError("max_changes: 1 to 8")
    stocks, flows = {s.id for s in model.stocks}, {f.id for f in model.flows}
    tg = _targets(targets, stocks, flows)
    if not tg:
        raise InverseError("targets: at least one")
    hd, held_flows = _holds(hold or [], stocks, flows)
    cands = candidates(model, held_flows, [t["id"] for t in tg if t["part"] == "stock"], history, new_flows)
    if not cands:
        raise InverseError("nothing may change: every flow is held")
    step_s = step_for(end - start, step_s)
    p = Problem(model, history, tg + hd, cands, start, end, step_s)
    by = {c.key: c for c in cands}
    support: dict[str, float] = {}
    res0 = p.run([{}])
    loss = float(p.loss(res0)[0])
    stages = [{"changes": {}, "loss": loss, "met": p.met(res0, 0)}]
    stopped = None
    alts: list[dict] = []
    p.deadline = deadline
    while not stages[-1]["met"] and len(support) < max_changes:
        if time.monotonic() > deadline:
            stopped = "deadline"
            break
        cols, owner = [], []
        for c in cands:
            if c.key in support:
                continue
            for v in c.grid:
                cols.append({**support, c.key: float(v)})
                owner.append(c.key)
        if not cols:
            break
        try:
            res = p.run(cols)
        except Late:
            stopped = "deadline"
            break
        ls = p.loss(res)
        per: dict[str, tuple[float, int]] = {}
        for j, key in enumerate(owner):
            if key not in per or ls[j] < per[key][0]:
                per[key] = (float(ls[j]), j)
        ranked = sorted(per, key=lambda k: (per[k][0] + (1e-9 if by[k].structural else 0.0), k))
        # a new flow only when no change of a number does as well (STRUCTURE)
        best_key = ranked[0]
        param_best = next((k for k in ranked if not by[k].structural), None)
        if by[best_key].structural and param_best is not None and per[param_best][0] <= per[best_key][0] * (1 + STRUCTURE) + 1e-12:
            best_key = param_best
        if per[best_key][0] >= loss * (1 - 1e-3):
            break                                            # nothing helps any more
        trial = {**support, best_key: cols[per[best_key][1]][best_key]}
        refined, new_loss = _refine(p, trial, deadline)
        if not math.isfinite(new_loss):
            refined, new_loss = trial, per[best_key][0]
        # the alternatives at this size: the next candidates, refined
        alts = []
        for key in [k for k in ranked if k != best_key][: max(0, alternatives) * 2]:
            if time.monotonic() > deadline or len(alts) >= alternatives:
                break
            if per[key][0] > max(per[best_key][0] * ALT, 1.0) and not p.met(res, per[key][1]):
                continue
            alt, _ = _refine(p, {**support, key: cols[per[key][1]][key]}, deadline)
            p.deadline = None
            r = p.run([alt])
            p.deadline = deadline
            alts.append({"changes": alt, "loss": float(p.loss(r)[0]), "met": p.met(r, 0)})
        support, loss = refined, new_loss
        p.deadline = None
        r = p.run([support])
        p.deadline = deadline
        stages.append({"changes": dict(support), "loss": loss, "met": p.met(r, 0)})
        if time.monotonic() > deadline and not stages[-1]["met"]:
            stopped = "deadline"
            break
    p.deadline = None
    final = stages[-1]
    res = p.run([final["changes"]])
    misses = p.misses(res, 0)
    return {"problem": p, "candidates": by, "stages": stages, "alternatives": alts, "stopped": stopped, "misses": misses,
            "result": res, "elapsed_s": round(time.monotonic() - began, 3), "deadline": deadline}


def change_rows(sol: dict, changes: dict[str, float]) -> list[dict]:
    by = sol["candidates"]
    out = []
    for key, f in changes.items():
        c = by[key]
        if c.structural:
            out.append({"kind": "new_flow", "flow": c.flow, "from": c.new["from"], "to": c.new["to"], "equation": c.new["equation"],
                        "params": {c.param: round(f, 6)}})
        elif c.param is None:
            out.append({"kind": "rate", "flow": c.flow, "factor": round(f, 4)})
        else:
            out.append({"kind": "param", "flow": c.flow, "param": c.param, "base": c.base, "value": round(c.value(f), 6), "factor": round(f, 4)})
    return out


def apply(model: Model, sol: dict, changes: dict[str, float], method: str) -> Model:
    """``model`` with the solved changes, each a declared equation by ``method``."""
    m = copy.deepcopy(model)
    names = Names.of(m)
    by = sol["candidates"]
    for key, f in changes.items():
        c = by[key]
        if c.structural:
            p = parse(c.new["equation"], stocks=names.stocks, inputs=names.inputs, params={c.param: c.value(f)})
            m.flows.append(Flow(c.flow, c.flow.replace("_", " "), c.new["from"], c.new["to"], None, [_equation_of(p, method)], [],
                                {"inverse": True}))
            names = Names.of(m)
            continue
        fl = next(x for x in m.flows if x.id == c.flow)
        text, params = flow_text(fl, names)
        if c.param is None:
            text = f"{f!r} * ({text})"
        else:
            params = {**params, c.param: c.value(f)}
        fl.equations = [*fl.equations, _eq(text, params, names, method)][-4:]
    return m


def _eq(text: str, params: dict, names: Names, method: str) -> Equation:
    return _equation_of(parse(text, stocks=names.stocks, inputs=names.inputs, params=params), method)


def report(sol: dict, model: Model, history: dict) -> dict:
    """What the solution implies: the targets met or missed, the side effects, the alternatives."""
    p: Problem = sol["problem"]
    final = sol["stages"][-1]
    res = sol["result"]
    rows = []
    for t, m in zip(p.targets, sol["misses"]):
        g = p.goal(t)
        if t["part"] == "stock":
            k = p.sids.index(t["id"])
            v = res["max"][0][k] if t["kind"] == "below" else res["min"][0][k] if t["kind"] == "above" else res["means"][0][k]
            measured = [v2 for tt, v2 in (history.get("stocks") or {}).get(t["id"]) or [] if p.start <= tt <= p.end]
            meas = sum(measured) / len(measured) if measured else None
            base = p.base_means[k]
        else:
            k = p.fids.index(t["id"])
            v, base = res["totals"][0][k], p.base_totals[k]
            pts = [x for tt, x in (history.get("flows") or {}).get(t["id"]) or [] if p.start < tt <= p.end]
            meas = sum(pts) * float(history.get("flow_step") or 30.0) / p.unit if pts else None
        ok = bool(abs(m) <= TOL * (1 + 1e-9) if t["kind"] not in ("below", "above") else m <= 1e-9)
        rows.append({"part": t["part"], "id": t["id"], "kind": "hold" if t["hold"] else t["kind"],
                     "value": t["value"], "goal": round(g, 4), "solved": round(float(v), 4), "base_replay": round(float(base), 4),
                     "measured": None if meas is None else round(meas, 4), "miss": round(float(m), 4), "met": ok})
    named = {(t["part"], t["id"]) for t in p.targets}
    side = []
    real = {s.id for s in model.stocks}
    for k, sid in enumerate(p.sids):
        if ("stock", sid) in named or sid not in real:
            continue
        b, s = p.base_means[k], res["means"][0][k]
        if abs(s - b) > SIDE * max(abs(b), 1e-6) and abs(s - b) > 1e-6:
            side.append({"part": "stock", "id": sid, "base_replay": round(float(b), 4), "solved": round(float(s), 4),
                         "ratio": round(float(s / b), 4) if b else None, "what": "mean level"})
    for k, fid in enumerate(p.fids):
        if ("flow", fid) in named or fid not in {f.id for f in model.flows}:
            continue
        b, s = p.base_totals[k], res["totals"][0][k]
        if abs(s - b) > SIDE * max(abs(b), 1e-6) and abs(s - b) > 1e-6:
            side.append({"part": "flow", "id": fid, "base_replay": round(float(b), 4), "solved": round(float(s), 4),
                         "ratio": round(float(s / b), 4) if b else None, "what": "moved over the window"})
    side.sort(key=lambda x: -abs(math.log(x["ratio"])) if x["ratio"] else 0)
    return {"reached": final["met"], "changes": change_rows(sol, final["changes"]), "count": len(final["changes"]),
            "targets": rows, "side_effects": side,
            "alternatives": [{"changes": change_rows(sol, a["changes"]), "met": a["met"], "loss": round(a["loss"], 4)}
                             for a in sol["alternatives"]],
            "stages": [{"count": len(s["changes"]), "loss": round(s["loss"], 4), "met": s["met"], "changes": change_rows(sol, s["changes"])}
                       for s in sol["stages"]],
            "stopped": sol["stopped"], "evaluations": p.evals, "elapsed_s": sol["elapsed_s"], "step_s": p.step_s,
            "window": [p.start, p.end]}


def uniqueness(model: Model, solved: Model, history: dict, changes: list[dict], start: float, end: float, *, seed: int = 0,
               deadline: float | None = None) -> dict:
    """Fabricate the window's data from the base and from the solved model, discover a model from
    each with conservation, and say which flows' laws changed between them (see above)."""
    from ..discover import discover
    from .fabricate import counter_name, dump, fabricate, history_of_dump
    from .replay import one_step

    step = float(history.get("stock_step") or 15.0)
    if deadline is not None and time.monotonic() > deadline:
        return {"checked": False, "why": "no time left before the deadline"}
    dumps, found = [], []
    for i, m in enumerate((model, solved)):
        d = dump(m, fabricate(m, history, start=start, end=end, step_s=step, seed=seed + i))
        dumps.append(d)
        found.append(discover(d, start=start, end=end, step=step, time_unit=model.time_unit))
    by_counter = {counter_name(f): f.id for f in model.flows if f.counter or f.measured_by}
    named = lambda m: {by_counter.get(f.counter.name if f.counter else f.id, f.id): f for f in m.flows}
    f0, f1 = named(found[0]), named(found[1])
    cf0 = one_step(found[0], history_of_dump(found[0], dumps[1], step), start, end)
    cf1 = one_step(found[1], history_of_dump(found[1], dumps[1], step), start, end)
    laws = {}
    for orig in sorted(set(f0) | set(f1)):
        if orig not in f0 or orig not in f1:
            laws[orig] = {"status": "appeared" if orig in f1 else "disappeared"}
            continue
        a, b = cf0.get(f0[orig].id), cf1.get(f1[orig].id)
        if a is None or b is None:
            continue
        gain = a["deviance"] - b["deviance"]
        laws[orig] = {"status": "changed" if gain >= LAW_GAIN else "unchanged", "deviance_gain": round(gain, 2),
                      "factual_law": {"predicted": a["predicted"], "counted": a["counted"]}}
    seen = {k for k, v in laws.items() if v["status"] != "unchanged"}
    solved_flows = {x["flow"] for x in changes if x["kind"] != "new_flow"}
    measured = {f.id for f in model.flows if f.counter or f.measured_by}
    missed = sorted(f for f in solved_flows if f in measured and f not in seen)
    extra = sorted(seen - solved_flows)
    return {"checked": True, "recovered": sorted(solved_flows & seen), "missed": missed, "extra": extra,
            "unmeasured": sorted({x["flow"] for x in changes if x["kind"] == "new_flow"} | (solved_flows - measured)),
            "laws": laws, "consistent": not missed and not extra,
            "stocks": {"factual": sorted(s.id for s in found[0].stocks), "counterfactual": sorted(s.id for s in found[1].stocks)},
            "how": f"the base and the solved model each fabricated the window's data (Poisson counts, seeds {seed} and {seed + 1}); "
                   "conservation discovered a model from each; a flow's law changed when the factual model's equation explains the "
                   f"counterfactual counts worse than the counterfactual model's own by a deviance of {LAW_GAIN:g} or more"}
