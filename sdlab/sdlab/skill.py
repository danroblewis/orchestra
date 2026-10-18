"""skill@H: how much of the true model's movement a found model predicts, with a bootstrap interval.

From ~150 moments in a run, the found and the true model are both run H steps from every stock's
true level, fed the same outside inflows (the truth's schedule replaces the found model's outside
inflow into every stock the truth feeds from outside), so only their own dynamics differ.
skill = 1 - (spread between them / how far the truth moved)^2: 1 = behaves as the truth, 0 = no
better than assuming nothing changes, below 0 = worse.

The interval resamples the start moments (each start's spread and movement together) and recomputes
the skill: a 95% percentile bootstrap. It says how much the number depends on which moments were
graded, not how it would differ on another run (grade a fresh run for that).

Used by the ladder (sdlab/ladder) and the examples' bench (tests/bench/grade.py re-exports it).
"""

from __future__ import annotations

import numpy as np

from .discovery.observer import observe, unmeasured
from .discovery.simulate import Model, levels_array, starts_for

BOOTSTRAP = 1000


def truth_flows_at(truth_model: dict, t: int) -> list[dict]:
    """The truth's flows with its schedule applied up to step t: last period's later changes still
    hold, then this period's so far override them."""
    sch = truth_model.get("schedule") or {"every": 0, "changes": []}
    flows = [dict(f) for f in truth_model["flows"]]
    by_id = {f.get("id"): f for f in flows}
    every = int(sch.get("every") or 0)
    within = ((t - 1) % every) + 1 if every else t
    changes = sch.get("changes") or []
    applied = sorted((c for c in changes if c["t"] > within), key=lambda c: c["t"]) if every and t > every else []
    applied += sorted((c for c in changes if c["t"] <= within), key=lambda c: c["t"])
    for c in applied:
        for fid, rate in (c.get("set") or {}).items():
            if fid in by_id:
                by_id[fid]["rate"] = rate
    return flows


def truth_by_time(truth_model: dict, times: list) -> tuple[list[dict], set]:
    """The truth over the run as flows whose rate follows the schedule (byTime), and the stocks it
    feeds with a constant outside inflow."""
    per_t = [truth_flows_at(truth_model, int(t)) for t in times]
    flows = []
    for i, f in enumerate(truth_model["flows"]):
        segs = []
        for t, fl in zip(times, per_t):
            rate = fl[i]["rate"]
            if segs and segs[-1]["rate"] == rate:
                segs[-1]["to"] = t
            else:
                segs.append({"from": t, "to": t, "rate": rate})
        flows.append({**f, "byTime": segs})
    fed = {f["to"] for f in truth_model["flows"] if not f.get("from") and f.get("to") and (f.get("rate") or {}).get("form") == "constant"}
    return flows, fed


def truth_runs(truth_model: dict, data: dict, horizon: int = 20, starts: int = 150) -> dict:
    """The truth's side of same_behaviour (the same for every model graded on this run and horizon):
    pass it as `truth` to grade several models without running the truth again."""
    t = data["t"]
    all_levels = data.get("all_levels") or data["levels"]
    ids = list(all_levels)
    truth, fed = truth_by_time(truth_model, t)
    const = lambda r: r if (r or {}).get("form") == "constant" else {"form": "constant", "value": 0}  # noqa: E731
    exo = [{**f, "byTime": [{**g, "rate": const(g["rate"])} for g in f["byTime"]]} for f in truth if not f.get("from") and f.get("to") in fed]
    A = levels_array(all_levels, ids)
    s0 = starts_for(A.shape[1], horizon, starts)
    times = np.asarray(t, dtype=float)[s0[None, :] + np.arange(horizon)[:, None]]
    injections = data.get("injections")                     # announced interventions, made in both models
    truth_end = Model(truth, ids).run(A[:, s0 - 1], times, injections)
    return {"horizon": horizon, "flows": truth, "ids": ids, "fed": fed, "exo": exo, "A": A, "s0": s0, "times": times, "truth_end": truth_end,
            "injections": injections}


def _renamed(x, names: dict):
    """Flows with every stock reference (from, to, stock, driver) renamed by `names`."""
    if isinstance(x, list):
        return [_renamed(v, names) for v in x]
    if isinstance(x, dict):
        return {k: names.get(v, v) if k in ("from", "to", "stock", "driver") and isinstance(v, str) else _renamed(v, names) for k, v in x.items()}
    return x


def same_behaviour(result: dict, truth_model: dict, data: dict, horizon: int = 20, starts: int = 150, truth: dict | None = None,
                   ci: bool = False, own_run: bool = True) -> dict:
    """skill@horizon of result's flows against the truth on this run; with ci, also "ci": the 95%
    bootstrap interval over the start moments ([lo, hi]).

    A found model may have unmeasured stocks of its own (any stock its flows move things into or out of
    that is not measured). They are kept apart from the truth's stocks (never started from the truth's
    level of a stock that happens to share the name) and started from the found model's own estimate of
    their levels: result["inferred_levels"] ({id: series aligned with t}) on the run it was fitted on;
    on any other run (own_run=False, e.g. a fresh run), or without one, the estimate the found model
    itself gives from that run's measured levels (sdlab/discovery/observer.py)."""
    tr = truth or truth_runs(truth_model, data, horizon, starts)
    ids, fed, exo, A, s0, times, truth_end = (tr[k] for k in ("ids", "fed", "exo", "A", "s0", "times", "truth_end"))
    measured = list(data["levels"])
    own = [f for f in result["flows"] if not (not f.get("from") and f.get("to") in fed and not f.get("driver") and (f.get("rate") or {}).get("form") == "constant")]
    hidden = list(dict.fromkeys(unmeasured(own, measured) + list(result.get("inferred_levels") or {})))
    if hidden:
        est = dict(result.get("inferred_levels") or {}) if own_run else {}
        if any(h not in est for h in hidden):
            first = {h: v[0] for h, v in (result.get("inferred_levels") or {}).items() if v}
            est = {**observe(own, measured, data["t"], data["levels"], hidden, first), **est}
        names = {x: f"found:{x}" for x in hidden}
        A_found = np.vstack([A] + [np.nan_to_num(np.asarray(est[x], dtype=float))[None, :] for x in hidden])
        found_end = Model(_renamed(own, names) + exo, ids + list(names.values())).run(A_found[:, s0 - 1], times, tr.get("injections"))[: len(ids)]
    else:
        found_end = Model(own + exo, ids).run(A[:, s0 - 1], times, tr.get("injections"))
    m = [ids.index(k) for k in measured]
    apart = float(((found_end[m] - truth_end[m]) ** 2).sum())
    moved = float(((truth_end[m] - A[m][:, s0 - 1]) ** 2).sum())
    ratio = (apart / max(1e-9, moved)) ** 0.5
    # how much there was to predict: the truth's movement over the horizon, in each stock's level
    # spread (rms over stocks and starts); near 0 the skill's denominator is small and the grade fragile
    sd = A[m].std(axis=1)
    sd[sd == 0] = 1
    spread = float(np.sqrt((((truth_end[m] - A[m][:, s0 - 1]) / sd[:, None]) ** 2).mean()))
    out = {"horizon": horizon, "apart": ratio, "skill": 1 - ratio * ratio, "moved": spread}
    if ci:
        out["ci"] = bootstrap_skill(((found_end[m] - truth_end[m]) ** 2).sum(axis=0), ((truth_end[m] - A[m][:, s0 - 1]) ** 2).sum(axis=0))
    return out


def bootstrap_skill(apart_i: np.ndarray, moved_i: np.ndarray, n: int = BOOTSTRAP, seed: int = 0) -> list[float] | None:
    """95% percentile interval of 1 - sum(apart) / sum(moved) with the starts resampled."""
    apart_i, moved_i = np.nan_to_num(np.asarray(apart_i, float), nan=1e12, posinf=1e12), np.asarray(moved_i, float)
    k = len(apart_i)
    if k < 2:
        return None
    idx = np.random.default_rng(seed).integers(0, k, size=(n, k))
    skills = 1 - apart_i[idx].sum(axis=1) / np.maximum(1e-9, moved_i[idx].sum(axis=1))
    lo, hi = np.percentile(skills, [2.5, 97.5])
    return [float(lo), float(hi)]
