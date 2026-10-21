"""The scorer's simulator for a truth that uses queue item 2d's engine features (expressions,
auxiliaries, switches, signed stocks, two-way flows, flows that read flows, fixed delays; MODEL.md).

The discovery library's simulator (sdlab/discovery/simulate.py) is pinned (CLAUDE.md rule 11) and
knows only the linear forms with effects, so a truth that uses one of 2d's features is run and read
here instead, by the engine itself (sdlab/sdtruth.py, noise none):

- truth_end: skill@H's truth side (sdlab/skill.py): the engine run H steps from every start's recorded
  state (every stock, hidden ones and switches too; the schedule, inputs and injections at their own
  times), the levels it ends at;
- whole(): which of the truth's flows the scorer compares as a whole (score.py): an expression rate, a
  two-way flow, or a rate or effect that reads an auxiliary or a switch. Such a flow has no numbers
  to compare one by one; its amount on the run's states is compared with the found flows' between the
  same stocks (both directions for a two-way flow), as a flow with effects is;
- amounts: such a flow's amount per step on the run's states (its rate x effects, floored at 0 unless
  two-way; auxiliaries computed from the state, a switch read from its recorded level, flow(id) read
  from the run's counters of that flow). At a sub-step (dt < 1) this is the rate at the step's start,
  not the sum over its sub-steps (substep.py refits only the linear forms).

A truth that uses none of these is scored as before, through simulate.py (sdlab/skill.py, score.py).

**Found models that say they are two-way or signed** (the user, 2026-10-19): a found flow marked
`"two_way": true` is not floored at 0 (a negative rate moves material back, from `to` to `from`), and a
stock a found flow marks signed (`"signed": true` for the stocks that flow moves, or `"signed": [ids]`)
may go below 0 (no floor on its level or its outflows; an injection may take it below 0), as the engine
runs them (MODEL.md). simulate.py (pinned) floors every rate and level, so skill@H and the physics' long
run step such a found model with `SignedModel` here instead (`found_model`); a found model with neither
mark runs through simulate.Model exactly as before.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np

from ..discovery.simulate import Model, _Rate
from ..sdtruth import Truth, _Program, uses_2d

HERE = Path(__file__).resolve().parent


def code_hash(base: str) -> str:
    """The score hash of a case whose truth uses 2d's features: the scorer's, and this module's."""
    return hashlib.sha256((base + (HERE / "sim.py").read_text()).encode()).hexdigest()[:16]


def uses_new(truth_model: dict) -> bool:
    """Does the truth need this simulator (an engine feature of queue item 2d)?"""
    return uses_2d(truth_model)


def _quiet(truth_model: dict) -> Truth:
    t = Truth.__new__(Truth)
    m = {**truth_model, "noise": {}}
    t.path, t.model = None, m
    t.seed, t.steps = int(m.get("seed", 20261016)), int(m.get("steps") or 1)
    t.long_steps = int(m.get("long_steps", t.steps * 10))
    t.measured_ids = [s["id"] for s in m["stocks"] if s.get("measured", True)]
    t.stock_ids = [s["id"] for s in m["stocks"]]
    return t


def truth_end(truth_model: dict, A: np.ndarray, ids: list[str], s0: np.ndarray, t: list, horizon: int) -> np.ndarray:
    """The truth's levels (ids x starts) `horizon` steps after each start's recorded state A[:, s - 1],
    the first step being t[s] (the engine, no noise)."""
    truth = _quiet(truth_model)
    out = np.zeros((len(ids), len(s0)))
    order = truth.stock_ids
    for j, s in enumerate(s0):
        start = {sid: float(A[ids.index(sid), s - 1]) for sid in order if sid in ids}
        run = truth.run(steps=horizon, start=start, t0=int(t[s]))
        for i, sid in enumerate(ids):
            out[i, j] = run["levels"][sid][-1] if sid in run["levels"] else A[i, s - 1]
    return out


def _reads(f: dict) -> set[str]:
    r = f.get("rate") or {}
    out = {r.get("stock")} | {x.get("stock") for x in r.get("terms") or []} | {e.get("stock") for e in f.get("effects") or []}
    return {x for x in out if x}


def whole(truth_model: dict) -> set[str]:
    """The ids of the truth's flows compared as a whole (see the module docstring)."""
    if not uses_new(truth_model):
        return set()
    aux = truth_model.get("auxiliaries") or {}
    names = set(aux if isinstance(aux, dict) else (a["id"] for a in aux)) | {s["id"] for s in truth_model["stocks"] if s.get("switch")}
    rates = lambda f: [f.get("rate")] + [c["set"][f["id"]] for c in ((truth_model.get("schedule") or {}).get("changes") or [])  # noqa: E731
                                         if f["id"] in (c.get("set") or {})]
    return {f["id"] for f in truth_model["flows"] if f.get("two_way") or any((r or {}).get("form") == "expr" for r in rates(f))
            or _reads(f) & names}


def mark(truth_flows: list[dict], truth_model: dict) -> list[dict]:
    """The truth's flows with the whole ones marked (copies): "whole" holds what amounts() needs."""
    ids = whole(truth_model)
    if not ids:
        return truth_flows
    aux = truth_model.get("auxiliaries") or {}
    return [{**f, "whole": {"auxiliaries": aux}} if f.get("id") in ids else f for f in truth_flows]


def mark_found(found_flows: list[dict], truth_model: dict) -> list[dict]:
    """A found model's flows with the ones only the engine can evaluate marked as mark() marks the
    truth's (an expression, a two-way flow, a rate or effect that reads one of the truth's auxiliaries
    or switches: a strategy's flows never are; the truth itself given as found, test_ladder's
    `perfect`, is)."""
    aux = truth_model.get("auxiliaries") or {}
    names = set(aux if isinstance(aux, dict) else (a["id"] for a in aux)) | {s["id"] for s in truth_model.get("stocks") or [] if s.get("switch")}
    out = []
    for f in found_flows:
        rates = [f.get("rate")] + [g.get("rate") for g in f.get("byTime") or []]
        if f.get("two_way") or any((r or {}).get("form") == "expr" for r in rates) or _reads(f) & names:
            f = {**f, "whole": {"auxiliaries": aux}}
        out.append(f)
    return out


def _two_args(prog: _Program, flow: dict):
    """prog.flow(flow) as fn(view, flows): the engine compiles a rate that is neither an expression nor
    two-way (a linear rate that reads a switch, `8 * heater`) as fn(levels), which reads no flows."""
    fn = prog.flow(flow)
    if (flow.get("rate") or {}).get("form") == "expr" or flow.get("two_way"):
        return fn
    return lambda view, fl=None: fn(view)


def amounts(f: dict, data: dict, states: list[dict]) -> np.ndarray:
    """A whole flow's amount per step on the run's states (see the module docstring); byTime segments
    (its schedule) followed."""
    names = set(states[0]) if states else set()
    aux = (f.get("whole") or {}).get("auxiliaries") or {}
    prog = _Program({"stocks": [{"id": n} for n in sorted(names)], "auxiliaries": aux, "flows": []})
    segs = f.get("byTime") or [{"from": -np.inf, "to": np.inf, "rate": f.get("rate")}]
    fns = [_two_args(prog, {**f, "rate": g["rate"]}) for g in segs]
    t = data["t"]
    counters = data.get("counters") or {}
    out = np.zeros(len(states))
    for i, state in enumerate(states):
        step = t[i + 1]
        k = next((n for n, g in enumerate(segs) if g["from"] <= step <= g["to"]), len(segs) - 1)
        view = dict(state)
        prog.auxiliaries(view)
        fl = {fid: float(v[i + 1]) for fid, v in counters.items() if i + 1 < len(v)}
        out[i] = fns[k](view, fl)
    return out


# ---- found models with two-way flows or signed stocks ----

def signed_stocks(flows: list[dict]) -> set[str]:
    """The stocks a found model marks signed (module docstring)."""
    out: set[str] = set()
    for f in flows:
        s = f.get("signed")
        if s is True:
            out |= {x for x in (f.get("from"), f.get("to")) if x}
        elif isinstance(s, (list, tuple)):
            out |= {x for x in s if isinstance(x, str)}
    return out


def says_signed(flows: list[dict]) -> bool:
    """Does a found model have a two-way flow or a signed stock (so simulate.Model's floors would not run it)?"""
    return any(f.get("two_way") for f in flows) or bool(signed_stocks(flows))


def _rates(f: dict) -> list[dict]:
    return [g.get("rate") or {} for g in f["byTime"]] if f.get("byTime") else [f.get("rate") or {}]


def says_expr(flows: list[dict]) -> bool:
    """Does a found model have an expression rate (simulate._Rate, pinned, reads one as 0)?"""
    return any(r.get("form") == "expr" for f in flows if not f.get("inflow") for r in _rates(f))


def found_model(flows: list[dict], ids: list[str], inputs: dict | None = None, dt: float = 1.0, ceilings: dict | None = None) -> Model:
    """The simulator for a found model: SignedModel when it says it is two-way or signed, else simulate.Model;
    either with its expression rates evaluated (_ExprRate) where it has any."""
    if says_signed(flows):
        model = SignedModel(flows, ids, inputs=inputs, dt=dt, ceilings=ceilings)
    else:
        model = Model(flows, ids, inputs=inputs, dt=dt, ceilings=ceilings)
    if says_expr(flows):
        rows = list(ids)
        if model.inputs is not None:                      # as simulate.Model indexes the inputs: after the stocks
            rows += [k for k in inputs["values"] if k not in set(ids)]
        index = {s: i for i, s in enumerate(rows)}
        for n, f in enumerate(flows):
            src, dst, ratio, segs, rate, vals = model.parts[n]
            if vals is None and any(r.get("form") == "expr" for r in _rates(f)):
                model.parts[n] = (src, dst, ratio, segs, _ExprRate(_rates(f), index, two_way=bool(f.get("two_way"))), vals)
    return model


class _ExprRate:
    """A found flow's rate where some segment is an expression (`{"form": "expr", "expr": "min(0.6 * queue,
    40 * ready)"}`, MODEL.md), evaluated state by state with the engine's own expression compiler
    (sdtruth_expr, as the engine runs the truth); its other segments as simulate._Rate (or _Unfloored for a
    two-way flow) evaluates them. Floored at 0 unless two-way, as the engine does. A name the model does
    not step (or flow(id), which a found model has no counters for) reads as 0, as simulate.Model reads a
    stock it does not step; an expression that does not parse reads as 0 (simulate._Rate's answer)."""

    def __init__(self, rates: list[dict], index: dict[str, int], two_way: bool = False):
        from ..sdtruth_expr import ExprError, compile_expr, parse

        self.index, self.two = index, two_way
        self.fns = []
        for r in rates:
            if r.get("form") == "expr":
                try:
                    self.fns.append(compile_expr(parse(r.get("expr"))))
                except (ExprError, KeyError, ValueError, TypeError):
                    self.fns.append(None)
            else:
                self.fns.append((_Unfloored if two_way else _Rate)([r], index))

    def __call__(self, L: np.ndarray, seg: np.ndarray) -> np.ndarray:
        out = np.zeros(L.shape[1])
        names = list(self.index)
        for g in np.unique(seg):
            m = np.flatnonzero(seg == g)
            fn = self.fns[int(g)]
            if fn is None:
                continue
            if isinstance(fn, _Rate):                     # a linear segment (_Unfloored is a _Rate too)
                out[m] = fn(L[:, m], np.zeros(len(m), int))
                continue
            for j in m:
                view = _Zero(zip(names, (float(L[i, j]) if i < L.shape[0] else 0.0 for i in self.index.values())))
                try:
                    v = float(fn(view, _Zero()))
                except (ArithmeticError, ValueError, TypeError):
                    v = 0.0
                out[j] = v if self.two else max(0.0, v)
        return np.nan_to_num(out, nan=0.0, posinf=0.0, neginf=0.0)


class _Zero(dict):
    """A view in which a name nobody gave reads as 0."""

    def __missing__(self, key):
        return 0.0


class _Unfloored(_Rate):
    """A two-way flow's rate: simulate._Rate without the floor at 0."""

    def __call__(self, L: np.ndarray, seg: np.ndarray) -> np.ndarray:
        if self.form == "mixed":
            out = np.zeros(L.shape[1])
            for g in np.unique(seg):
                m = seg == g
                out[m] = _Unfloored([self.rates[g]], self.index)(L[:, m], np.zeros(int(m.sum()), int))
            return out
        if self.form == "constant":
            return self.value[seg]
        if self.form == "proportional":
            return self.k[seg] * self._level(L, self.stocks[0])
        if self.form == "gap":
            return (self.goal[seg] - self._level(L, self.stocks[0])) / self.time[seg]
        if self.form == "linear":
            return self.c[seg] + sum(k[seg] * self._level(L, i) for k, i in zip(self.ks, self.stocks))
        return np.zeros(L.shape[1])


class SignedModel(Model):
    """simulate.Model with two-way flows (rate not floored; a negative amount moves from `to` to `from`)
    and signed stocks (level and outflows not floored). The floor of an unsigned stock applies to
    whichever stock a two-way flow takes from, and a ceiling to whichever it fills, as in the engine."""

    def __init__(self, flows: list[dict], ids: list[str], inputs: dict | None = None, dt: float = 1.0, ceilings: dict | None = None):
        super().__init__(flows, ids, inputs=inputs, dt=dt, ceilings=ceilings)
        index = {s: i for i, s in enumerate(ids)}
        if self.inputs is not None:                           # as simulate.Model indexes the inputs: after the stocks
            index.update({k: len(ids) + j for j, k in enumerate([k for k in inputs["values"] if k not in index])})
        self.two = [bool(f.get("two_way")) for f in flows]
        for n, f in enumerate(flows):
            if not self.two[n] or self.parts[n][5] is not None:
                continue
            src, dst, ratio, segs, _, vals = self.parts[n]
            rates = [g["rate"] for g in f["byTime"]] if f.get("byTime") else [f.get("rate") or {}]
            self.parts[n] = (src, dst, ratio, segs, _Unfloored(rates, index), vals)
        self.signed = np.array([s in signed_stocks(flows) for s in ids], dtype=bool)

    def _amounts(self, L: np.ndarray, t: np.ndarray) -> list:
        R = self._read(L, t)
        zero = np.zeros(L.shape[1], int)
        amounts = []
        for src, dst, ratio, segs, rate, vals in self.parts:
            seg = segs(t) if segs is not None else zero
            amounts.append(vals[seg] if vals is not None else rate(R, seg))
        for i, effect in self.effects:
            amounts[i] = amounts[i] * effect(R)
        if self.n_sub > 1:
            amounts = [a * self.dt for a in amounts]
        S = L.shape[0]
        # what each unsigned stock gives: its outflows (a two-way flow's positive part), a two-way flow
        # into it running backwards, and the flows that use it up; shared out of what it holds
        for c in range(S):
            if self.signed[c]:
                continue
            takers = [(i, float(r), 1.0) for i, (src, _, r, *_) in enumerate(self.parts) if src == c]
            takers += [(i, 1.0, -1.0) for i, (src, dst, *_) in enumerate(self.parts) if dst == c and self.two[i]]
            takers += [(i, per, 1.0) for i, cc, per in self.uses if cc == c]
            if not takers:
                continue
            want = sum(np.maximum(0.0, side * amounts[i]) * w for i, w, side in takers)
            k = np.where((want > L[c]) & (L[c] > -1), np.maximum(0.0, L[c]) / np.where(want > 0, want, 1), 1.0)
            for i, _, side in takers:
                amounts[i] = np.where(side * amounts[i] > 0, amounts[i] * k, amounts[i])
        for c, cap in self.ceilings:                          # nothing enters a full stock
            if c >= S:
                continue
            ins = [(i, 1.0) for i, (_, dst, *_) in enumerate(self.parts) if dst == c]
            ins += [(i, -1.0) for i, (src, *_) in enumerate(self.parts) if src == c and self.two[i]]
            want = sum(np.maximum(0.0, side * amounts[i]) for i, side in ins)
            room = np.maximum(0.0, cap - L[c])
            k = np.where(want > room, room / np.where(want > 0, want, 1), 1.0)
            for i, side in ins:
                amounts[i] = np.where(side * amounts[i] > 0, amounts[i] * k, amounts[i])
        return amounts

    def _amounts_added(self, L: np.ndarray, t: np.ndarray) -> list:
        return self._amounts(L, t)

    def _floor(self, nxt: np.ndarray) -> np.ndarray:
        keep = np.zeros(nxt.shape[0], dtype=bool)
        keep[: len(self.signed)] = self.signed
        return np.where((nxt >= 0) | keep[:, None], nxt, 0.0)

    def _substeps(self, L: np.ndarray, t: np.ndarray) -> np.ndarray:
        for _ in range(self.n_sub):
            L = self._floor(L + self._raw_change(L, t))
        return L

    def _raw_change(self, L: np.ndarray, t: np.ndarray) -> np.ndarray:
        amounts = self._amounts(L, t)
        d = np.zeros_like(L, dtype=float)
        for (src, dst, ratio, *_), a in zip(self.parts, amounts):
            if src is not None:
                d[src] -= a * ratio
            if dst is not None:
                d[dst] += a
        for i, c, per in self.uses:
            d[c] -= amounts[i] * per
        return d

    def change(self, L: np.ndarray, t: np.ndarray) -> np.ndarray:
        if self.n_sub > 1:
            return self._substeps(L, t) - L
        return self._raw_change(L, t)

    def step(self, L: np.ndarray, t: np.ndarray) -> np.ndarray:
        if self.n_sub > 1:
            return self._substeps(L, t)
        return self._floor(L + self._raw_change(L, t))

    def run(self, L: np.ndarray, times: np.ndarray, injections: list[dict] | None = None) -> np.ndarray:
        index = {s: i for i, s in enumerate(self.ids)}
        pulses = [(float(j["t"]), index[j["stock"]], float(j["amount"])) for j in injections or [] if j.get("stock") in index]
        for t in times:
            if pulses:
                L = L.copy()
                for tj, i, amount in pulses:
                    hit = t == tj
                    if hit.any():
                        L[i, hit] = L[i, hit] + amount if self.signed[i] else np.maximum(0.0, L[i, hit] + amount)
                        for c, cap in self.ceilings:
                            if c == i:
                                L[i, hit] = np.minimum(cap, L[i, hit])
            L = self.step(L, t)
        return L
