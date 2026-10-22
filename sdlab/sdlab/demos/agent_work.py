"""Demo 13, agent work as stocks (docs/demos/agent-work.md; OPERATIONALIZATION.md ideas 41-46).

A simulated team of AI agents working tickets: tickets are stocks by state (backlog -> in_progress -> in_review ->
merging -> done), new tickets arrive (a measured input), the agents are the machines that move tickets out of
in_progress (each agent does a fixed number of tickets an hour, capped by the work in hand: a MIN), review sends
some tickets back to the backlog (rework), and a merge gate lands at most a fixed number an hour (a second MIN).
The number of agents is a measured stock set by hand (a dial: 4 agents, then 8 from day 12; announced, as kubectl
scale is in ladder case 306).

The true model lives only here, in memory; it is not a ladder case. Its data comes from the ladder's engine
(ladder/data.simulate). Discovery ran once per strategy (`precompute`, below) and the found models are cached in
~/.cache/sdlab/demos/agent-work/; the demo only reads that cache. Nothing here changes a case, a strategy or the
result store.

Regenerate the cache (single-threaded, a few seconds per fast strategy):
    OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 NUMBA_NUM_THREADS=1 \
        nice -n 19 uv run python -m sdlab.demos.agent_work precompute milp earned_pieces
"""

from __future__ import annotations

import functools
import hashlib
import json
import math
import os
import re
import sys
import time
from pathlib import Path

import numpy as np
from fastapi import APIRouter, HTTPException

from . import engine as E

router = APIRouter()

NAME = "agent-work"
DAY = 24                                   # one step is one hour
STEPS = 30 * DAY                           # 30 days measured
SWITCH = 12 * DAY                          # the dial: 4 -> 8 agents at the start of day 12
AGENTS0, ADDED = 4, 4
STRATEGIES = ("milp", "earned_pieces")    # the cached found models, in the order shown
STAGES = ("backlog", "in_progress", "in_review", "merging")

# the true numbers (what discovery should recover)
TRUE = {
    "per_agent": 0.5,                      # tickets an agent finishes an hour (12 a day)
    "coding_k": 0.4,                       # share of the work in hand finished an hour when agents are not the limit
    "pickup": 0.2,                         # share of the backlog picked up an hour
    "approved": 0.24, "reworked": 0.06,    # review: 0.30 of in_review leaves an hour, a fifth of it back to backlog
    "merge_k": 0.5, "merge_cap": 2.2,      # merge gate: half of what waits, at most 2.2 an hour (52.8 a day)
    "arrivals_mean": 1.8, "arrivals_amp": 1.2,
}


def _p(stock: str, k: float) -> dict:
    return {"form": "proportional", "stock": stock, "k": k}


def _x(expr: str) -> dict:
    return {"form": "expr", "expr": expr}


def truth_model(steps: int = STEPS, extra_agents: int = 0, extra_arrivals: float = 0.0, at: int = STEPS) -> dict:
    """The true model in the engine's format (the shape of cases.truth_model's output). extra_agents and
    extra_arrivals (tickets an hour) take effect from step `at` on (a what-if); the measured run has neither."""
    T = TRUE
    arr = [{"fn": "constant", "value": T["arrivals_mean"]}, {"fn": "sin", "amplitude": T["arrivals_amp"], "period": DAY, "phase": 6}]
    if extra_arrivals:
        arr.append({"fn": "step", "height": float(extra_arrivals), "start": at})
    inj = [{"t": SWITCH, "stock": "agents", "amount": ADDED}]
    if extra_agents:
        inj.append({"t": at, "stock": "agents", "amount": int(extra_agents)})
    stocks = [("backlog", "tickets", 20), ("in_progress", "tickets", 4), ("in_review", "tickets", 2),
              ("merging", "tickets", 1), ("done", "tickets", 0), ("agents", "agents", AGENTS0)]
    flows = [("arrived", None, "backlog", _p("arrivals", 1)),
             ("started", "backlog", "in_progress", _p("backlog", T["pickup"])),
             ("coded", "in_progress", "in_review", _x(f"min(({T['coding_k']} * in_progress), ({T['per_agent']} * agents))")),
             ("approved", "in_review", "merging", _p("in_review", T["approved"])),
             ("reworked", "in_review", "backlog", _p("in_review", T["reworked"])),
             ("merged", "merging", "done", _x(f"min(({T['merge_k']} * merging), {T['merge_cap']})"))]
    return {"id": NAME, "name": "Agent work as stocks (demo 13)", "time_unit": "step", "seed": 13, "steps": int(steps),
            "noise": {}, "inputs": {"arrivals": {"terms": arr}}, "injections": inj,
            "stocks": [{"id": s, "name": s, "unit": u, "initial": i, **({"final": True} if s == "done" else {})} for s, u, i in stocks],
            "flows": [{"id": i, "name": i, "from": a, "to": b, "rate": r} for i, a, b, r in flows]}


BOUNDARY = {"boundary": {"backlog": {"in": ["input"], "out": []}}, "boundary_declared": True}   # tickets come in only as arrivals


def model_hash() -> str:
    return hashlib.sha256(json.dumps(truth_model(), sort_keys=True).encode()).hexdigest()[:16]


@functools.lru_cache(maxsize=1)
def measured() -> dict:
    """The measured run (noise-free): what discovery got."""
    from ..ladder import data as ladder_data
    return ladder_data.simulate(truth_model())


# ---- the found models (cached by precompute) ----

def cache_dir() -> Path:
    return Path(os.environ.get("SDLAB_DEMOS_CACHE") or Path.home() / ".cache" / "sdlab" / "demos") / NAME


def precompute(strategies=STRATEGIES) -> list[dict]:
    """Discover the model once per strategy, as runner.run_item does (measured data plus the declared boundary),
    and write ~/.cache/sdlab/demos/agent-work/found-<strategy>.json."""
    from ..discovery.api import jsonable
    from ..ladder import provenance, runner
    m, d = truth_model(), {**measured(), **BOUNDARY}
    out = []
    for s in strategies:
        prov = provenance.loaded(s)
        began = time.perf_counter()
        r = runner.discover(s, m, d)
        row = {"strategy": s, "flows": jsonable(r.get("flows") or []), "seconds": round(time.perf_counter() - began, 2),
               "model_hash": model_hash(), "at": time.strftime("%Y-%m-%d %H:%M"), **prov}
        cache_dir().mkdir(parents=True, exist_ok=True)
        (cache_dir() / f"found-{s}.json").write_text(json.dumps(row, indent=1))
        out.append(row)
    return out


def found(strategy: str) -> dict:
    p = cache_dir() / f"found-{strategy}.json"
    if strategy not in STRATEGIES or not p.exists():
        raise LookupError(f"no cached found model for {strategy}: run `uv run python -m sdlab.demos.agent_work precompute`")
    row = json.loads(p.read_text())
    row["stale"] = row.get("model_hash") != model_hash()
    return row


def available() -> list[str]:
    return [s for s in STRATEGIES if (cache_dir() / f"found-{s}.json").exists()]


# ---- reading the numbers that matter out of a found model ----

def _rate_text(r) -> str:
    if not isinstance(r, dict):
        return str(r)
    if r.get("form") == "proportional":
        return f"{_g(r['k'])} × {r['stock']}"
    if r.get("form") == "constant":
        return _g(r["value"])
    if r.get("form") == "linear":
        parts = ([_g(r["c"])] if r.get("c") else []) + [f"{_g(t['k'])} × {t['stock']}" for t in r.get("terms") or []]
        return " + ".join(parts) or "0"
    if r.get("form") == "expr":
        return re.sub(r"\d+\.\d{4,}", lambda m: _g(float(m.group(0))), r["expr"])
    return json.dumps(r)


def _g(x: float) -> str:
    return f"{float(x):.4g}"


_FUNCS = {"min": min, "max": max, "abs": abs, "exp": math.exp, "log": math.log, "sqrt": math.sqrt,
          "ceil": math.ceil, "floor": math.floor}


@functools.lru_cache(maxsize=512)
def _compiled(expr: str):
    return compile(expr, "<rate>", "eval")


def rate_value(rate, env: dict) -> float:
    """A found (or true) rate's value at the levels in env (stocks and inputs by name)."""
    if isinstance(rate, (int, float)):
        return float(rate)
    form = rate.get("form")
    if form == "constant":
        return float(rate["value"])
    if form == "proportional":
        return float(rate["k"]) * float(env.get(rate["stock"], 0.0))
    if form == "linear":
        return float(rate.get("c") or 0.0) + sum(float(t["k"]) * float(env.get(t["stock"], 0.0)) for t in rate.get("terms") or [])
    if form == "expr":
        return float(eval(_compiled(rate["expr"]), {"__builtins__": {}}, {**_FUNCS, **env}))   # noqa: S307  (our own cached models)
    raise ValueError(f"unknown rate form {form!r}")


def _out(flows: list[dict], stock: str, env: dict) -> tuple[float, list[tuple[dict, float]]]:
    each = [(f, rate_value(f["rate"], env)) for f in flows if f.get("from") == stock]
    return sum(v for _, v in each), each


def typical() -> dict:
    """The levels at the end of the measured month (and the mean arrivals): where a found rate is read."""
    r = measured()
    env = {s: float(v[-1]) for s, v in r["all_levels"].items()}
    env["arrivals"] = float(np.mean(r["inputs"]["arrivals"]))
    return env


BIG = 1e5        # a pile far larger than any capacity: a flow's value there is its cap


def readings(flows: list[dict]) -> dict:
    """The found model's answers to the demo's questions, read by evaluating its rates (so any written form works):
    the agents' tickets an hour per agent (what leaves in_progress with a huge pile, per agent, at 8 and 16
    agents), the share of review sent back to backlog, and the merge gate's cap (what leaves merging with a huge
    pile, at 8 and 16 agents), with plain notes where the model does not say what the truth does."""
    env = typical()
    out: dict = {}
    A = AGENTS0 + ADDED
    c8, each = _out(flows, "in_progress", {**env, "in_progress": BIG, "agents": A})
    c16, _ = _out(flows, "in_progress", {**env, "in_progress": BIG, "agents": 2 * A})
    capped = c8 < 0.5 * BIG * 0.01                      # a share of a huge pile would be huge: this is a cap
    out["per_agent"] = c8 / A if capped else None
    out["per_agent_16"] = c16 / (2 * A) if capped else None
    out["agent_scales"] = bool(capped and abs(c16 - 2 * c8) < 0.05 * abs(c8))
    dest = sorted({f.get("to") or "outside" for f, _ in each})
    if not capped:
        out["agent_note"] = "missed: what leaves in_progress has no cap, so the model has no per-agent rate"
    elif not out["agent_scales"]:
        out["agent_note"] = "found a cap on in_progress, but it does not grow in step with the agents"
    else:
        out["agent_note"] = "found: a cap on in_progress that grows in step with the agents"
    if dest != ["in_review"]:
        out["agent_note"] += f"; the work goes to {', '.join(dest)} (the truth: in_review only)"
    # review
    _, rev = _out(flows, "in_review", env)
    tot = sum(v for _, v in rev)
    back = sum(v for f, v in rev if f.get("to") == "backlog")
    neg = [f for f, v in rev if v < -1e-9]
    out["rework_share"] = back / tot if tot > 1e-9 and not neg and back > 0 else None
    out["review_dest"] = {(f.get("to") or "outside"): v for f, v in rev}
    if back <= 0:
        out["rework_note"] = "missed: no review → backlog flow (no rework loop)"
    elif neg:
        out["rework_note"] = (f"review → backlog found, but {len(neg)} other flow(s) out of review run backwards "
                              "(negative rates), so the share sent back cannot be read")
    else:
        dests = sorted(d for d in out["review_dest"] if d != "backlog")
        out["rework_note"] = "found: review sends a share back to backlog" + (
            f"; the rest goes to {', '.join(dests)} (the truth: merging)" if dests != ["merging"] else "")
    # merge gate
    m8, mf = _out(flows, "merging", {**env, "merging": BIG, "agents": A})
    m16, _ = _out(flows, "merging", {**env, "merging": BIG, "agents": 2 * A})
    gate = m8 < 0.5 * BIG * 0.01
    out["merge_cap"] = m8 if gate else None
    out["merge_cap_16"] = m16 if gate else None
    out["merge_reads"] = sorted({s for f, _ in mf for s in re.findall(r"[A-Za-z_]\w*", json.dumps(f["rate"]))
                                 if s in STOCKS and s != "merging"})
    if not mf:
        out["merge_note"] = "missed: nothing leaves merging"
    elif not gate:
        out["merge_note"] = "missed: what leaves merging has no cap (a plain share), so the model has no merge gate"
    elif abs(m16 - m8) > 0.05 * abs(m8):
        out["merge_note"] = (f"found a cap near the true one at 8 agents, but written as growing with the agents "
                             f"({_g(m8)} an hour at 8, {_g(m16)} at 16): the gate only bound while 8 agents worked, so the "
                             "data cannot tell a fixed cap from one per agent")
    else:
        out["merge_note"] = "found: a fixed cap on what leaves merging"
    return out


def _match(flows: list[dict], truth: dict) -> list[dict]:
    """Each true flow beside the found flow(s) between the same stocks, and the found flows the truth lacks."""
    rows, used = [], set()
    for tf in truth["flows"]:
        hits = [i for i, f in enumerate(flows) if (f.get("from") or None) == tf["from"] and (f.get("to") or None) == tf["to"]]
        used.update(hits)
        rows.append({"ends": f"{tf['from'] or 'outside'} → {tf['to'] or 'outside'}", "name": tf["id"], "true": _rate_text(tf["rate"]),
                     "found": "; ".join(_rate_text(flows[i]["rate"]) for i in hits) or None,
                     "status": "found" if hits else "missed"})
    for i, f in enumerate(flows):
        if i not in used:
            rows.append({"ends": f"{f.get('from') or 'outside'} → {f.get('to') or 'outside'}", "name": None, "true": None,
                         "found": _rate_text(f["rate"]), "status": "false"})
    return rows


# ---- simulating forward: the true model and a found model under the same change ----

STOCKS = (*STAGES, "done", "agents")


@functools.lru_cache(maxsize=256)
def _truth_run(extra_agents: int, extra_arrivals: float, horizon: int) -> dict:
    r = E.run_truth(truth_model(steps=STEPS + horizon, extra_agents=extra_agents, extra_arrivals=extra_arrivals))
    return r


def _found_run(strategy: str, extra_agents: int, extra_arrivals: float, horizon: int) -> dict:
    """The found model run free from the true levels at the end of the measured month, with the agents dial set and
    the same arrivals the truth gets (both are measured, so a forecast would use them as given)."""
    tr = _truth_run(extra_agents, extra_arrivals, horizon)
    flows = found(strategy)["flows"]
    t = tr["t"][STEPS - 1:]
    start = {s: tr["levels"][s][STEPS - 1] for s in STOCKS}
    start["agents"] = AGENTS0 + ADDED + extra_agents
    inputs = {k: v[STEPS - 1:] for k, v in tr["inputs"].items()}
    return E.free_run(flows, list(STOCKS), t, start, inputs)


def _pair(strategy: str, add: int, extra: float, horizon: int) -> tuple[dict, dict, dict]:
    """The true and the found forecast from the end of the measured month, and their summaries."""
    tr = _truth_run(add, extra, horizon)
    tl = {s: tr["levels"][s][STEPS - 1:] for s in STOCKS}
    inputs = {k: v[STEPS - 1:] for k, v in tr["inputs"].items()}
    fr = _found_run(strategy, add, extra, horizon)
    summ = {"truth": _summary(tl, horizon, truth_model()["flows"], inputs),
            "found": _summary(fr, horizon, found(strategy)["flows"], inputs)}
    return tl, fr, summ


def _summary(levels: dict, horizon: int, flows: list[dict], inputs: dict) -> dict:
    """The last week of a forecast: tickets done a day, mean tickets waiting at each stage, the lead time by Little's
    law (tickets in the system / tickets done an hour), and the bottleneck (theory of constraints): the stage still
    piling up (growing by half a ticket a day or more), else the stage whose outflow runs at its cap the largest share
    of hours (its cap: what would leave it with a huge pile, from the model's own equations), else none."""
    wk = min(7 * DAY, horizon)
    done = np.asarray(levels["done"], float)
    per_day = float((done[-1] - done[-1 - wk]) / wk * DAY)
    mean = {s: float(np.mean(np.asarray(levels[s], float)[-wk:])) for s in STAGES}
    growth = {s: float((levels[s][-1] - levels[s][-1 - wk]) / (wk / DAY)) for s in STAGES}     # tickets a day
    at_cap = {s: 0.0 for s in STAGES}
    n = len(levels["done"])
    for i in range(n - wk, n):
        env = {k: float(v[i]) for k, v in levels.items()} | {k: float(v[i]) for k, v in inputs.items()}
        for s in STAGES:
            cap, _ = _out(flows, s, {**env, s: BIG})
            if cap < 0.005 * BIG:
                now, _ = _out(flows, s, env)
                at_cap[s] += (now >= 0.98 * cap) / wk
    wip = sum(mean.values())
    lead = wip / (per_day / DAY) if per_day > 1e-9 else None
    grow = max(STAGES, key=lambda s: growth[s])
    busy = max(STAGES, key=lambda s: at_cap[s])
    if growth[grow] >= 0.5:
        pile, why = grow, "growing"
    elif at_cap[busy] >= 0.05:
        pile, why = busy, "at its cap"
    else:
        pile, why = "none", "keeps up"
    return {"done_per_day": per_day, "mean": mean, "growth_per_day": growth, "at_cap": at_cap, "wip": wip,
            "lead_hours": lead, "pile": pile, "why": why, "growing": why == "growing"}


def _finite(x):
    return None if x is None or not math.isfinite(x) else x


def _clean(o):
    if isinstance(o, float):
        return _finite(round(o, 4))
    if isinstance(o, dict):
        return {k: _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    return o


# ---- the endpoints' content ----

def overview() -> dict:
    tm = truth_model()
    r = measured()
    every = 3
    series = {s: r["levels"][s][::every] for s in STOCKS}
    series["arrivals"] = r["inputs"]["arrivals"][::every]
    arrivals_day = float(np.mean(r["inputs"]["arrivals"]) * DAY)
    true_read = readings(tm["flows"])                         # the same reading of the true model
    share = true_read["rework_share"]
    models = []
    for s in available():
        f = found(s)
        rd = readings(f["flows"])
        models.append({"strategy": s, "commit": (f.get("code_commit") or "")[:9], "dirty": f.get("code_dirty"),
                       "seconds": f.get("seconds"), "at": f.get("at"), "stale": f["stale"], "readings": rd,
                       "flows": _match(f["flows"], tm), "agents_needed": _needed(rd.get("per_agent"), rd.get("rework_share"), arrivals_day)})
    return _clean({"t": r["t"][::every], "series": series, "switch": SWITCH, "steps": STEPS, "day": DAY,
                   "agents": [AGENTS0, AGENTS0 + ADDED], "arrivals_per_day": arrivals_day, "true": true_read,
                   "true_flows": [{"ends": f"{f['from'] or 'outside'} → {f['to'] or 'outside'}", "name": f["id"], "rate": _rate_text(f["rate"])} for f in tm["flows"]],
                   "agents_needed_true": _needed(TRUE["per_agent"], share, arrivals_day),
                   "max_done_true": TRUE["merge_cap"] * DAY, "models": models, "strategies": list(STRATEGIES)})


def _needed(per_agent, share, arrivals_day):
    """Little's law / flow balance: agents needed so that coding keeps up with arrivals plus rework."""
    if not per_agent or per_agent <= 0 or share is None or share >= 1:
        return None
    return arrivals_day / (1 - share) / (per_agent * DAY)


def whatif(strategy: str, add: int, extra: float = 0.0, horizon: int = 14 * DAY) -> dict:
    """From the end of the measured month (8 agents): add `add` agents (and `extra` tickets an hour), run both models
    `horizon` steps on; the curves and the last week's summary, found beside true."""
    tl, fr, summ = _pair(strategy, add, extra, horizon)
    return _clean({"strategy": strategy, "add": add, "extra": extra, "agents": AGENTS0 + ADDED + add,
                   "t": _truth_run(add, extra, horizon)["t"][STEPS - 1:], "truth": tl, "found": {s: fr[s] for s in STOCKS},
                   "summary": summ})


def sweep(strategy: str, extra: float = 0.0, horizon: int = 14 * DAY, top: int = 12) -> dict:
    """add = -4..top more agents than today's 8: tickets done a day and where they pile up, found beside true."""
    found(strategy)
    rows = []
    for add in range(-AGENTS0 - 2, top + 1, 2):
        _, _, summ = _pair(strategy, add, extra, horizon)
        rows.append({"add": add, "agents": AGENTS0 + ADDED + add, **summ})
    return _clean({"strategy": strategy, "extra": extra, "rows": rows, "arrivals_per_day": float(TRUE["arrivals_mean"] * DAY + extra * DAY)})


def _call(fn, *a, **k):
    try:
        return fn(*a, **k)
    except LookupError as e:
        raise HTTPException(409, str(e)) from None


@router.get(f"/{NAME}/overview")
def overview_route() -> dict:
    return _call(overview)


@router.get(f"/{NAME}/forecast")
def forecast_route(strategy: str = STRATEGIES[0], add: int = 4, extra: float = 0.0) -> dict:
    return _call(whatif, strategy, max(-AGENTS0 - 3, min(int(add), 40)), max(-1.5, min(float(extra), 5.0)))


@router.get(f"/{NAME}/sweep")
def sweep_route(strategy: str = STRATEGIES[0], extra: float = 0.0) -> dict:
    return _call(sweep, strategy, max(-1.5, min(float(extra), 5.0)))


if __name__ == "__main__":                                    # python -m sdlab.demos.agent_work precompute [strategies]
    args = sys.argv[1:]
    if not args or args[0] != "precompute":
        sys.exit("usage: python -m sdlab.demos.agent_work precompute [strategy ...]")
    for row in precompute(tuple(args[1:]) or STRATEGIES):
        print(row["strategy"], f"{row['seconds']} s", len(row["flows"]), "flows")
        for f in row["flows"]:
            print("   ", f.get("from"), "->", f.get("to"), _rate_text(f.get("rate")))
