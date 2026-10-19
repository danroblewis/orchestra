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
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np

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


def amounts(f: dict, data: dict, states: list[dict]) -> np.ndarray:
    """A whole flow's amount per step on the run's states (see the module docstring); byTime segments
    (its schedule) followed."""
    names = set(states[0]) if states else set()
    aux = (f.get("whole") or {}).get("auxiliaries") or {}
    prog = _Program({"stocks": [{"id": n} for n in sorted(names)], "auxiliaries": aux, "flows": []})
    segs = f.get("byTime") or [{"from": -np.inf, "to": np.inf, "rate": f.get("rate")}]
    fns = [prog.flow({**f, "rate": g["rate"]}) for g in segs]
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
