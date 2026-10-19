"""A truth that runs at a sub-step (dt = 1/n < 1) as its per-recorded-step equivalent, so the scorer
compares numbers on the same basis as the data (the user, 2026-10-19: "I would hope the issue would
fall out after normalization").

The data of such a truth are recorded once per step, after n Euler sub-steps that each move
rate x dt. A found model is a one-step map of the recorded levels, so its numbers are per recorded
step: a drain k becomes 1 - (1 - k dt)^n per step (0.1 at dt 1/8 reads as 0.0952), and a constant
inflow c moves c per step whatever dt is. The scorer's truth is therefore:

- **each flow's amount over a recorded step**: the truth's n sub-steps run from every recorded state
  (all stocks, hidden ones too, injections made at the start of the step, as the engine makes them;
  no noise; outflows share what a stock holds, as the engine does), each flow's amounts summed over
  its sub-steps;
- **each flow's numbers in its own form**: a linear rate (constant, proportional, gap, linear) has
  its numbers refitted by least squares of that amount on what the rate reads (its constant and its
  stocks and inputs), per schedule segment, so a drain k gives exactly 1 - (1 - k dt)^n and a gap or a
  linear rate exactly the one-step map's numbers (a single stock: exact; a stock fed by another within
  the step: the best one-step number in the truth's form); a rate with effects (a product) keeps its
  shape and is scaled by the least-squares factor between that amount and its one-step amount at the
  same state;
- **a flow with effects compared as a whole** (score.py) is compared against that scaled form: the
  best one-step product. (The summed sub-step amounts themselves are not a product of the step's
  start levels: on 100's outbreaks they differ from the best product by 6.7% rms, so no one-step
  model, the truth's own form included, could meet the noise-free 2% against them.)

Measured inputs are read at the step's value (the engine's mean over the step's sub-steps). A truth
at dt = 1 is returned unchanged. In the score hash (score.py).
"""

from __future__ import annotations

import copy

import numpy as np

from .fisher import _effect, _rate
from .parts import linear_form


def substeps(truth_model: dict) -> int:
    dt = float(truth_model.get("dt") or 1)
    return max(1, round(1 / dt)) if dt < 1 else 1


def _segment_steps(flow: dict, steps: np.ndarray) -> list[np.ndarray]:
    segs = flow.get("byTime") or [{"from": -np.inf, "to": np.inf, "rate": flow.get("rate")}]
    return [np.flatnonzero((steps >= g["from"]) & (steps <= g["to"])) for g in segs]


def step_amounts(truth_flows: list[dict], data: dict, n: int) -> np.ndarray:
    """Each truth flow's amount over every recorded step (flows x steps): n sub-steps of dt = 1/n from
    the recorded state at the step's start."""
    t = data["t"]
    lv = data.get("all_levels") or data["levels"]
    ids = list(lv)
    inputs = {k: v for k, v in (data.get("inputs") or {}).items() if k not in lv}
    idx = {s: i for i, s in enumerate(ids)}
    for k in inputs:
        idx[k] = len(idx)
    K = len(t) - 1
    X = np.array([np.asarray(lv[s], dtype=float)[:-1] for s in ids])
    tindex = {v: i for i, v in enumerate(t)}
    for j in data.get("injections") or []:
        if j.get("stock") in lv and j["t"] in tindex and tindex[j["t"]] >= 1:
            X[ids.index(j["stock"]), tindex[j["t"]] - 1] += float(j["amount"])
    X = np.maximum(X, 0.0)
    U = np.array([np.asarray(v, dtype=float)[1: K + 1] for v in inputs.values()]) if inputs else np.zeros((0, K))
    steps = np.asarray(t[1:])
    segs = [_segment_steps(f, steps) for f in truth_flows]
    dt = 1.0 / n
    total = np.zeros((len(truth_flows), K))
    for _ in range(n):
        view = np.vstack([X, U]) if len(U) else X
        q = np.zeros((len(truth_flows), K))
        for fi, f in enumerate(truth_flows):
            r = np.zeros(K)
            rates = f.get("byTime") or [{"rate": f.get("rate")}]
            for g, m in zip(rates, segs[fi]):
                if len(m):
                    r[m] = _rate(g["rate"], view[:, m], idx, f)
            for e in f.get("effects") or []:
                r = r * _effect(e, view, idx)
            q[fi] = r * dt
        # outflows share what a stock holds (co-flows take `per` of it), as the engine does
        for s, si in ((s, i) for i, s in enumerate(ids)):
            take = [(fi, float(f.get("ratio") or 1)) for fi, f in enumerate(truth_flows) if f.get("from") == s]
            take += [(fi, float(u.get("per") or 0)) for fi, f in enumerate(truth_flows) for u in f.get("uses") or []
                     if u.get("stock") == s and float(u.get("per") or 0) > 0]
            if not take:
                continue
            want = sum(q[fi] * w for fi, w in take)
            k = np.where((want > X[si]) & (want > 0), np.maximum(0.0, X[si]) / np.maximum(want, 1e-300), 1.0)
            for fi in {fi for fi, _ in take}:
                q[fi] = q[fi] * k
        for fi, f in enumerate(truth_flows):
            if f.get("from") in idx and f["from"] in lv:
                X[idx[f["from"]]] -= q[fi] * float(f.get("ratio") or 1)
            if f.get("to") in idx and f["to"] in lv:
                X[idx[f["to"]]] += q[fi]
            for u in f.get("uses") or []:
                if u.get("stock") in lv and float(u.get("per") or 0) > 0:
                    X[idx[u["stock"]]] -= q[fi] * float(u["per"])
        total += q
    return total


def _refit(rate: dict, amount: np.ndarray, x0: np.ndarray, idx: dict, flow: dict, effects: np.ndarray) -> dict:
    """The rate's numbers refitted to the per-step amounts on these steps (its own form kept)."""
    lf = linear_form(rate) if not flow.get("effects") else None
    form = (rate or {}).get("form")
    if lf is not None and form in ("constant", "proportional", "gap", "linear"):
        c, ks = lf
        readers = [j for j in ks if j in idx]
        const = form != "proportional" and (form != "linear" or bool(c))
        cols = ([np.ones(x0.shape[1])] if const else []) + [x0[idx[j]] for j in readers]
        if not cols or len(amount) < len(cols):
            return rate
        A = np.array(cols).T
        beta, *_ = np.linalg.lstsq(A, amount, rcond=None)
        c2 = float(beta[0]) if const else 0.0
        k2 = dict(zip(readers, (float(b) for b in beta[1 if const else 0:])))
        if form == "constant":
            return {**rate, "value": c2}
        if form == "proportional":
            return {**rate, "k": k2[rate.get("stock")]}
        if form == "gap":
            kk = -k2[rate.get("stock")]
            if kk <= 0:
                return {"form": "linear", "c": c2, "terms": [{"stock": rate.get("stock"), "k": -kk}]}
            return {**rate, "time": 1.0 / kk, "goal": c2 / kk}
        terms = []
        seen = set()
        for x in rate.get("terms") or []:
            s = x.get("stock")
            if s in seen:
                continue
            seen.add(s)
            terms.append({**x, "k": k2.get(s, float(x.get("k") or 0))})
        return {**rate, **({"c": c2} if const else {}), "terms": terms}
    # a product (a rate with effects, or a form that is not linear): its shape kept, scaled
    base = _rate(rate, x0, idx, flow) * effects
    den = float(base @ base)
    if den <= 0:
        return rate
    s = float(base @ amount) / den
    return _scaled(rate, s)


def _scaled(rate: dict, x: float) -> dict:
    r = dict(rate or {})
    form = r.get("form")
    if form == "constant":
        r["value"] = float(r.get("value") or 0) * x
    elif form == "proportional":
        r["k"] = float(r.get("k") or 0) * x
    elif form == "gap":
        r["goal"] = float(r.get("goal") or 0)
        r["time"] = float(r.get("time") or 1) / x if x else r.get("time")
    elif form == "linear":
        r["c"] = float(r.get("c") or 0) * x
        r["terms"] = [{**t, "k": float(t.get("k") or 0) * x} for t in r.get("terms") or []]
    return r


def per_step(truth_flows: list[dict], data: dict, truth_model: dict) -> tuple[list[dict], np.ndarray | None]:
    """(the truth's flows with per-recorded-step numbers, each flow's summed sub-step amount per step);
    the flows unchanged and None at dt = 1."""
    n = substeps(truth_model)
    if n == 1 or len(data["t"]) < 3:
        return truth_flows, None
    data = data.get("clean") or data                    # a noisy variant: the run underneath, every step
    amounts = step_amounts(truth_flows, data, n)
    t = data["t"]
    lv = data.get("all_levels") or data["levels"]
    ids = list(lv)
    inputs = {k: v for k, v in (data.get("inputs") or {}).items() if k not in lv}
    idx = {s: i for i, s in enumerate(ids)}
    for k in inputs:
        idx[k] = len(idx)
    K = len(t) - 1
    X = np.array([np.asarray(lv[s], dtype=float)[:-1] for s in ids])
    tindex = {v: i for i, v in enumerate(t)}
    for j in data.get("injections") or []:
        if j.get("stock") in lv and j["t"] in tindex and tindex[j["t"]] >= 1:
            X[ids.index(j["stock"]), tindex[j["t"]] - 1] += float(j["amount"])
    if inputs:
        X = np.vstack([X, np.array([np.asarray(v, dtype=float)[1: K + 1] for v in inputs.values()])])
    steps = np.asarray(t[1:])
    out = copy.deepcopy(truth_flows)
    for fi, f in enumerate(out):
        eff = np.ones(K)
        for e in f.get("effects") or []:
            eff = eff * _effect(e, X, idx)
        if f.get("byTime"):
            for g, m in zip(f["byTime"], _segment_steps(f, steps)):
                if len(m):
                    g["rate"] = _refit(g["rate"], amounts[fi, m], X[:, m], idx, f, eff[m])
            f["rate"] = f["byTime"][-1]["rate"]
        else:
            f["rate"] = _refit(f.get("rate"), amounts[fi], X, idx, f, eff)
    return out, amounts
