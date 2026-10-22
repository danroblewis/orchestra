"""Demo 16, verify an AI agent's effect (docs/demos/agent-verify.md; OPERATIONALIZATION.md ideas 42 and 43).

The system is a discrete-event simulation (agent_verify_des.py), not a system dynamics model: an on-call support
flow where items arrive, human engineers triage them one at a time, some need a fix, and some reopen later. An AI
agent, a separate program that reacts to the simulation's events, joins at day 21.

1. Before the agent: SD discovery reads the quarter-hourly counts of the first 21 days (items queued, in triage, in
   fix, resolved; new items and engineers on shift as measured inputs) and finds a best-effort model. It is not the
   truth (there is no SD truth here) and the demo measures how wrong it is.
2. The design states what the agent should do (DESIGN), and that is written as an edit to the found model: a new
   flow queued -> resolved (the agent's resolutions) and faster human triage (its notes). The edited model predicts
   the next 21 days.
3. After deployment, the agent's effect is measured through the model in two ways: the counterfactual (the found
   model, unedited, run on the after-period's inputs: what would have happened without the agent, measured minus
   that is the effect), and the closes it cannot explain (measured minus its one-step prediction of the resolved
   count, regressed on the new items: after minus before is the share of new items something new closes, with the
   same weeks of the run without the agent as the noise).
4. The truth comes from the simulation's event log and from the same simulation run without the agent (same
   arrivals, same items' draws: common random numbers), so the true effect is known exactly.

Discovery ran once per strategy (`precompute`), cached in ~/.cache/sdlab/demos/agent-verify/ with each variant's
analysis; requests read that cache. Regenerate (single-threaded, about 40 s a strategy plus a few seconds a variant):
    OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 NUMBA_NUM_THREADS=1 \\
        nice -n 19 uv run python -m sdlab.demos.agent_verify precompute [strategy ...]

Nothing here changes a case, a simulation, a strategy or the result store."""

from __future__ import annotations

import copy
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

from ..ladder import sim as ladder_sim
from . import agent_verify_des as DES
from . import engine as E

router = APIRouter()

NAME = "agent-verify"
EVERY = 0.25                               # hours a sample (a step of the SD model)
PER_H = int(round(1 / EVERY))
HOURS = 42 * 24                            # 6 weeks measured
DEPLOY_H = 21 * 24                         # the agent joins at day 21
T = DEPLOY_H * PER_H                       # the step the agent starts (samples before it are the before-period)
N = HOURS * PER_H
DRAIN = 72                                 # hours simulated past the end, so items opened late still close (their open time)
SEED = 16
STRATEGIES = ("censored", "engine_forms")  # chosen by free-run fit among 7 tried (docs/demos/agent-verify.md)
STOCKS = ("queued", "in_triage", "in_fix", "resolved")
OPEN = ("queued", "in_triage", "in_fix")
INPUTS = ("new_items", "engineers")
BOUNDARY = {"boundary": {"queued": {"in": ["input"], "out": []}}, "boundary_declared": True}   # items enter only as new items
VARIANTS = {
    "good": "the agent as designed",
    "weak": "an agent that resolves far fewer items than planned",
    "misrouting": "an agent that closes many items wrongly (they reopen)",
}

# What the agent's designers say it will do (the same claims for every variant: the variants are what it really does)
DESIGN = {
    "resolve_share": 0.35,                 # it resolves 35% of new items itself
    "note_factor": 0.7,                    # its notes make the humans' triage of the rest 30% shorter
    "slots": 3, "handle_hours": 0.07,      # 3 items at a time, about 4 minutes each (its cap: slots / handle a quarter hour)
    "misroute_max": 0.02,                  # at most 2% of new items closed wrongly
    "targets": {"queue": -0.50, "hours_open": -0.30, "reopens": 0.10},   # queue down by half, time open down 30%, reopens up at most 10%
}


def _sha(o) -> str:
    return hashlib.sha256(json.dumps(o, sort_keys=True).encode()).hexdigest()[:16]


def cache_dir() -> Path:
    return Path(os.environ.get("SDLAB_DEMOS_CACHE") or Path.home() / ".cache" / "sdlab" / "demos") / NAME


COMMAND = ("OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 NUMBA_NUM_THREADS=1 "
           "nice -n 19 uv run python -m sdlab.demos.agent_verify precompute")


# ---- the simulation's runs ----

@functools.lru_cache(maxsize=8)
def des(variant: str | None) -> dict:
    """The DES with the agent variant from DEPLOY_H on (None: without the agent), samples trimmed to N steps."""
    r = DES.run(HOURS + DRAIN, seed=SEED, agent=variant, agent_from=DEPLOY_H if variant else math.inf,
                log_from=DEPLOY_H, every=EVERY)
    r["t"] = r["t"][:N]
    r["samples"] = {k: [float(x) for x in v[:N]] for k, v in r["samples"].items()}
    return r


def levels(r: dict) -> dict:
    return {s: r["samples"][s] for s in STOCKS}


def inputs(r: dict) -> dict:
    return {k: r["samples"][k] for k in INPUTS}


def before_data() -> dict:
    """What discovery got: the first 21 days of the run without the agent (identical to every variant's: the agent
    only acts from DEPLOY_H, and every item's draws are its own)."""
    r = des(None)
    return {"t": r["t"][:T], "levels": {s: v[:T] for s, v in levels(r).items()}, "eras": [{"start": 1, "label": "Start"}],
            "inputs": {k: v[:T] for k, v in inputs(r).items()}, **BOUNDARY}


def data_hash() -> str:
    d = before_data()
    return _sha({"levels": d["levels"], "inputs": d["inputs"]})


# ---- discovery, once per strategy ----

def page_model() -> dict:
    return {"stocks": [{"id": s, "name": s, "unit": "items", **({"final": True} if s == "resolved" else {})} for s in STOCKS]}


def precompute(strategies=STRATEGIES) -> list[dict]:
    from ..discovery.api import jsonable
    from ..ladder import provenance, runner
    out = []
    for s in strategies:
        prov = provenance.loaded(s)
        began = time.perf_counter()
        r = runner.discover(s, page_model(), before_data())
        row = {"strategy": s, "flows": jsonable(r.get("flows") or []), "seconds": round(time.perf_counter() - began, 2),
               "data_hash": data_hash(), "at": time.strftime("%Y-%m-%d %H:%M"), **prov}
        cache_dir().mkdir(parents=True, exist_ok=True)
        (cache_dir() / f"found-{s}.json").write_text(json.dumps(row, indent=1))
        out.append(row)
        for v in VARIANTS:
            analysis(s, v, refresh=True)
    return out


def found(strategy: str) -> dict:
    p = cache_dir() / f"found-{strategy}.json"
    if strategy not in STRATEGIES or not p.exists():
        raise LookupError(f"no cached found model for {strategy}: run `{COMMAND}`")
    row = json.loads(p.read_text())
    row["stale"] = row.get("data_hash") != data_hash()
    return row


def available() -> list[str]:
    return [s for s in STRATEGIES if (cache_dir() / f"found-{s}.json").exists()]


# ---- the found model: stepping, the design's edit, what it cannot explain ----

def _model(flows: list[dict], t: list, inp: dict):
    return ladder_sim.found_model(flows, list(STOCKS), inputs={"t": list(t), "values": inp})


def one_step(flows: list[dict], r: dict, lo: int, hi: int) -> dict:
    """The model's prediction of each step i in [lo, hi) from the measured levels at i - 1 (all at once)."""
    t, lv, inp = r["t"], levels(r), inputs(r)
    mdl = _model(flows, t, inp)
    L = np.array([[lv[s][i - 1] for i in range(lo, hi)] for s in STOCKS], float)
    P = mdl.step(L, np.array([t[i] for i in range(lo, hi)], float))
    return {s: P[k] for k, s in enumerate(STOCKS)}


def free(flows: list[dict], r: dict, lo: int, hi: int, start: dict | None = None) -> dict:
    """The model run free over steps lo..hi-1 from the measured levels at step lo - 1 (or `start`): out[s][j] is the
    level after step lo + j (the measured inputs of r)."""
    t, lv, inp = r["t"], levels(r), inputs(r)
    a = max(lo - 1, 0)
    st = start or {s: (lv[s][a] if lo > 0 else 0.0) for s in STOCKS}
    tt = ([0] if lo == 0 else []) + list(t[a:hi])
    ii = {k: ([0.0] if lo == 0 else []) + list(v[a:hi]) for k, v in inp.items()}
    out = E.free_run(flows, list(STOCKS), tt, st, ii)
    return {s: out[s][1:] for s in STOCKS}


def amounts(flows: list[dict], r: dict, lo: int, hi: int) -> np.ndarray:
    """Each flow's amount a step on the measured states of steps lo..hi-1 (flows x steps), as the simulator moves it."""
    t, lv, inp = r["t"], levels(r), inputs(r)
    mdl = _model(flows, t, inp)
    L = np.array([[lv[s][i - 1] for i in range(lo, hi)] for s in STOCKS], float)
    return np.asarray(mdl._amounts(L, np.array([t[i] for i in range(lo, hi)], float)), float)


def agent_flow(share: float, cap: float | None = None) -> dict:
    """The design's new flow: the agent resolves `share` of the new items, at most `cap` a step."""
    rate = ({"form": "expr", "expr": f"min({float(share)!r} * new_items, {float(cap)!r})"} if cap
            else {"form": "proportional", "stock": "new_items", "k": float(share)})
    return {"from": "queued", "to": "resolved", "rate": rate, "agent": True}


def triage_numbers(flows: list[dict]) -> list[dict]:
    """The numbers that say how fast the humans triage: every number the model multiplies the engineers by (their
    capacity) and every share of in_triage that leaves it a step. (Read from the text after each number, not from
    engine.numbers' label, which can run on past a comma inside min(...).)"""
    out = []
    for n in E.numbers(flows):
        f = flows[n["flow"]]
        r = f.get("rate") or {}
        parts = n["key"].split("/")
        if parts[1] == "expr":
            m = list(E.NUM.finditer(r["expr"]))[int(parts[2])]          # the key counts every number, as set_number does
            after = r["expr"][m.end():]
            hit = re.match(r"\s*\*\s*engineers\b", after) or (f.get("from") == "in_triage" and re.match(r"\s*\*\s*in_triage\b", after))
        else:
            hit = n["label"] == "× engineers" or (f.get("from") == "in_triage" and n["label"] == "× in_triage")
        if hit:
            out.append(n)
    return out


def levers(flows: list[dict], speed: float = 1.0, share: float = 0.0, cap: float | None = None) -> list[dict]:
    """The found model with the humans' triage numbers times `speed` and, when share > 0, the agent's flow
    (`share` of new items, at most `cap` a step)."""
    out = copy.deepcopy(flows)
    if speed != 1.0:
        for n in triage_numbers(out):
            out = E.set_number(out, n["key"], n["value"] * speed)
    if share > 0:
        out.append(agent_flow(share, cap))
    return out


def design_edit(flows: list[dict]) -> tuple[list[dict], list[dict]]:
    """The design written as an edit of the found model: the agent's flow, capped by its slots, and the humans'
    faster triage (the triage numbers divided by the note factor: the handed-off items are nearly all the humans
    triage). Returns the edited flows and the list of edits (for the page)."""
    k = 1 / DESIGN["note_factor"]
    cap = DESIGN["slots"] / DESIGN["handle_hours"] * EVERY
    edits = [{"ends": n["ends"], "label": _short_numbers(n["label"]), "from": n["value"], "to": n["value"] * k}
             for n in triage_numbers(flows)]
    edits.append({"ends": "queued → resolved", "label": "new flow: the agent's resolutions", "from": None,
                  "to": f"min({DESIGN['resolve_share']} × new_items, {cap:.3g} a step)"})
    return levers(flows, speed=k, share=DESIGN["resolve_share"], cap=cap), edits


def close_share(flows: list[dict], r: dict, lo: int, hi: int) -> dict:
    """What the model cannot explain in the resolved count on steps lo..hi-1: the measured change minus the model's
    one-step prediction (each step from the measured levels), regressed on the new items that step and a constant.
    Before the agent the slope is the model's own bias; after it, the slope's rise is the share of new items closed
    by something the model does not have (the agent's quick closes, right or wrong)."""
    lv, inp = levels(r), inputs(r)
    P = one_step(flows, r, lo, hi)
    res = np.asarray(lv["resolved"][lo:hi]) - P["resolved"]
    X = np.column_stack([np.ones(hi - lo), np.asarray(inp["new_items"][lo:hi])])
    b = np.linalg.lstsq(X, res, rcond=None)[0]
    return {"slope": float(b[1]), "per_day": float(b[0]) * 24 * PER_H, "unexplained_per_day": float(res.mean()) * 24 * PER_H}


# ---- reading a found model ----

def _g(x: float) -> str:
    return f"{float(x):.4g}"


def _short_numbers(text: str) -> str:
    return re.sub(r"\d+\.\d{4,}(?:[eE][-+]?\d+)?", lambda m: _g(float(m.group(0))), text)


def rate_text(r) -> str:
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
        return _short_numbers(r["expr"])
    return json.dumps(r)


def ends(f: dict) -> str:
    return f"{f.get('from') or 'outside'} → {f.get('to') or 'outside'}"


def per_hour(x) -> float:
    return float(np.mean(x)) * PER_H


def little_hours(lv: dict, inp: dict, lo: int, hi: int) -> float:
    """Little's law: items open (queued + in triage + in fix) ÷ new items an hour = hours open per item."""
    wip = float(np.mean(sum(np.asarray(lv[s][lo:hi], float) for s in OPEN)))
    return wip / per_hour(inp["new_items"][lo:hi])


# ---- the truth, from the event log ----

def _in_after(e) -> bool:
    return DEPLOY_H <= e[0] < HOURS


def truth(variant: str) -> dict:
    """The agent's true effect over the after-period, from the event logs: the run with the agent against the run
    without it (same arrivals and the same items' draws)."""
    a, b = des(variant), des(None)
    after = lambda r: [i for i in r["items"] if DEPLOY_H <= i["created"] < HOURS]        # noqa: E731
    days = (HOURS - DEPLOY_H) / 24
    reopens = lambda r: sum(1 for e in r["events"] if e[2] == "reopens" and _in_after(e)) / days   # noqa: E731
    new = len(after(a))
    c = {k: sum(1 for e in a["events"] if e[1] == "agent" and e[2] == w and _in_after(e))
         for k, w in (("takes", "takes"), ("resolves", "resolves"), ("misroutes", "misroutes"), ("hands_off", "hands off"))}
    tri = [e for e in a["events"] if e[1] == "engineer" and e[2].startswith("triages") and _in_after(e)]
    noted = sum(1 for e in tri if "note" in e[2]) / max(len(tri), 1)
    note = DES.AGENTS[variant]["note"]
    q = lambda r: float(np.mean(r["samples"]["queued"][T:]))                             # noqa: E731
    hrs = lambda r: float(np.mean([i["open_hours"] for i in after(r)]))                  # noqa: E731
    return {"new_items": new, "new_per_day": new / days, "agent": c, "resolve_share": c["resolves"] / new,
            "misroute_share": c["misroutes"] / new, "handoff_share": c["hands_off"] / new,
            "closed_share": (c["resolves"] + c["misroutes"]) / new,
            "noted_share": noted, "note_factor": note, "speed": 1 / (1 - noted * (1 - note)),
            "queue": {"with": q(a), "without": q(b), "change": q(a) / q(b) - 1},
            "hours_open": {"with": hrs(a), "without": hrs(b), "change": hrs(a) / hrs(b) - 1},
            "reopens_per_day": {"with": reopens(a), "without": reopens(b), "extra": reopens(a) - reopens(b)},
            "still_open": sum(1 for i in after(a) if not i["closed"])}


# ---- the analysis of one variant through one found model ----

def _stats(lv: dict, inp: dict, lo: int, hi: int) -> dict:
    return {"queue": float(np.mean(lv["queued"][lo:hi])), "hours_open": little_hours(lv, inp, lo, hi),
            "in_triage": float(np.mean(lv["in_triage"][lo:hi])), "in_fix": float(np.mean(lv["in_fix"][lo:hi]))}


def _fit(flows, r) -> dict:
    """The found model's errors before the agent: one step ahead and run free from step 0 (in items)."""
    lv = levels(r)
    os_ = one_step(flows, r, 1, T)
    fr = free(flows, r, 0, T)
    out = {}
    for s in OPEN:
        y = np.asarray(lv[s][:T])
        out[s] = {"mean": float(y.mean()), "free_mean": float(np.mean(fr[s])),
                  "one_step_rmse": float(np.sqrt(np.mean((os_[s] - y[1:]) ** 2))),
                  "free_rmse": float(np.sqrt(np.mean((np.asarray(fr[s]) - y) ** 2)))}
    return out


DAY_STEPS = 24 * PER_H


def _coarse(x, every: int = DAY_STEPS) -> list:
    """Daily means, for the charts (the day/night swing hides the before/after difference otherwise)."""
    x = np.asarray(x, float)
    m = len(x) // every * every
    return x[:m].reshape(-1, every).mean(axis=1).tolist()


def analyse(strategy: str, variant: str) -> dict:
    fm = found(strategy)
    flows = fm["flows"]
    ra, r0 = des(variant), des(None)
    lv, inp = levels(ra), inputs(ra)
    edited, edits = design_edit(flows)
    pred = free(edited, ra, T, N)                 # the design's prediction: the edited model from the state at T
    cf = free(flows, ra, T, N)                    # the counterfactual: the found model as it was, the same inputs
    ia = {k: v[T:] for k, v in inp.items()}
    n = N - T
    S = {"observed": _stats({s: lv[s][T:] for s in STOCKS}, ia, 0, n), "predicted": _stats(pred, ia, 0, n),
         "counterfactual": _stats(cf, ia, 0, n), "true_counterfactual": _stats({s: levels(r0)[s][T:] for s in STOCKS}, ia, 0, n),
         "before": _stats(lv, inp, 0, T)}
    eff = lambda a, b: a / b - 1 if b > 1e-9 else None                                    # noqa: E731
    cs = {"before": close_share(flows, r0, 1, T), "after": close_share(flows, ra, T, N),
          "quiet": close_share(flows, r0, T, N)}                    # quiet: the same weeks without the agent (the noise)
    tr = truth(variant)
    rc = ra["samples"]["reopened_total"]
    counter = {"before": (rc[T - 1] - rc[0]) / (T / PER_H / 24), "after": (rc[N - 1] - rc[T - 1]) / ((N - T) / PER_H / 24)}
    model_view = {"resolve_share": cs["after"]["slope"] - cs["before"]["slope"],
                  "resolve_noise": abs(cs["quiet"]["slope"] - cs["before"]["slope"]),
                  "queue": eff(S["observed"]["queue"], S["counterfactual"]["queue"]),
                  "hours_open": eff(S["observed"]["hours_open"], S["counterfactual"]["hours_open"]),
                  "back_flows": [{"ends": ends(f), "rate": rate_text(f["rate"])} for f in flows if f.get("to") == "queued" and f.get("from")],
                  "reopen_counter_per_day": counter}
    predicted = {"resolve_share": DESIGN["resolve_share"], "speed": 1 / DESIGN["note_factor"],
                 "queue": eff(S["predicted"]["queue"], S["counterfactual"]["queue"]),
                 "hours_open": eff(S["predicted"]["hours_open"], S["counterfactual"]["hours_open"])}
    charts = {"t_days": _coarse(np.arange(1, N + 1) / PER_H / 24), "after_start": T // DAY_STEPS,
              "observed": {s: _coarse(lv[s]) for s in OPEN},
              "true_counterfactual": {s: _coarse(levels(r0)[s]) for s in OPEN},
              "before_fit": {s: _coarse(free(flows, r0, 0, T)[s]) for s in OPEN},
              "predicted": {s: _coarse(pred[s]) for s in OPEN}, "counterfactual": {s: _coarse(cf[s]) for s in OPEN}}
    log = [e for e in ra["events"] if e[0] >= DEPLOY_H][:60]
    return {"strategy": strategy, "variant": variant, "label": VARIANTS[variant], "fit": _fit(flows, r0), "stats": S,
            "edits": edits, "close_share": cs, "true": tr, "model": model_view, "predicted": predicted, "charts": charts,
            "log": log, "agent_cfg": DES.AGENTS[variant],
            "found": {"commit": (fm.get("code_commit") or "")[:9], "dirty": fm.get("code_dirty"), "seconds": fm.get("seconds"),
                      "at": fm.get("at"), "stale": fm["stale"], "flows": [{"ends": ends(f), "rate": rate_text(f["rate"])} for f in flows]}}


def _key(strategy: str) -> str:
    here = Path(__file__).resolve().parent
    src = (here / "agent_verify.py").read_text() + (here / "agent_verify_des.py").read_text()
    return _sha({"src": hashlib.sha256(src.encode()).hexdigest(), "found": found(strategy)["flows"]})


def analysis(strategy: str, variant: str, refresh: bool = False) -> dict:
    """analyse(), cached in the cache dir by the code and the found model (a request reads the file)."""
    if variant not in VARIANTS:
        raise KeyError(variant)
    key = _key(strategy)
    p = cache_dir() / f"analysis-{strategy}-{variant}.json"
    if not refresh and p.exists():
        row = json.loads(p.read_text())
        if row.get("key") == key:
            return row["analysis"]
    out = _clean(analyse(strategy, variant))
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"key": key, "analysis": out}))
    return out


# ---- verdicts ----

def reopen_allowance(new_per_day: float) -> float:
    """The design's misroute limit as extra reopens a day: 2% of the new items, plus a quarter for slack."""
    return 1.25 * DESIGN["misroute_max"] * new_per_day


def word(vals: dict, allowance: float) -> str:
    """yes: every claim met; no: an outcome (queue, hours open) moved less than half its target, or the rework rose
    more than 3x the allowance (a harmful side effect); partly: otherwise. vals holds the claims' met flags and
    the outcome changes; a claim that cannot be judged (None) is left out."""
    tg = DESIGN["targets"]
    for k in ("queue", "hours_open"):
        if vals[k] is None or vals[k] > 0.5 * tg[k]:
            return "no"
    if vals["reopens_extra"] is not None and vals["reopens_extra"] > 3 * allowance:
        return "no"
    return "yes" if all(m for m in vals["met"] if m is not None) else "partly"


def verdicts(a: dict) -> dict:
    """Each design claim: met in truth? met as seen through the model? and the overall verdicts."""
    D, tr, mv, pr = DESIGN, a["true"], a["model"], a["predicted"]
    tg = D["targets"]
    allow = reopen_allowance(tr["new_per_day"])
    near = lambda x, want: x is not None and x >= 0.9 * want                              # noqa: E731
    cut = lambda x, want: x is not None and x <= 0.8 * want                               # noqa: E731
    claims = [
        {"key": "resolve", "claim": f"it resolves {D['resolve_share']:.0%} of new items itself", "kind": "share",
         "intended": D["resolve_share"], "predicted": pr["resolve_share"], "model": mv["resolve_share"], "true": tr["resolve_share"],
         "met_true": near(tr["resolve_share"], D["resolve_share"]), "met_model": near(mv["resolve_share"], D["resolve_share"]),
         "note": (f"through the model: the share of new items closed that the model cannot explain (±{mv['resolve_noise']:.1%} on "
                  f"the same weeks without the agent). It counts every close, right or wrong: the agent closed "
                  f"{tr['closed_share']:.1%} ({tr['resolve_share']:.1%} right, {tr['misroute_share']:.1%} wrong)")},
        {"key": "speed", "claim": f"its notes make human triage {1 - D['note_factor']:.0%} shorter", "kind": "speed",
         "intended": 1 / D["note_factor"], "predicted": pr["speed"], "model": None, "true": tr["speed"],
         "met_true": tr["speed"] >= 0.9 / D["note_factor"], "met_model": None,
         "note": (f"triage speed, × before. Not measured through the model: refitting its triage numbers gave nonsense (they "
                  f"are not one clean rate in this model); it shows only in the outcomes below. True: {tr['noted_share']:.0%} "
                  f"of human triages carry a note, each {1 - tr['note_factor']:.0%} shorter")},
        {"key": "misroute", "claim": f"it closes at most {D['misroute_max']:.0%} of new items wrongly", "kind": "share",
         "intended": D["misroute_max"], "predicted": 0.0, "model": None, "true": tr["misroute_share"],
         "met_true": tr["misroute_share"] <= 1.25 * D["misroute_max"], "met_model": None,
         "note": "a wrong close looks like a resolution in the counts: the model cannot see it"},
        {"key": "reopens", "claim": f"so reopened items rise by at most {allow:.1f} a day", "kind": "per_day",
         "intended": allow, "predicted": 0.0, "model": None, "true": tr["reopens_per_day"]["extra"],
         "met_true": tr["reopens_per_day"]["extra"] <= allow, "met_model": None,
         "note": (("the model's flows back into the queue (" + "; ".join(f"{x['ends']} = {x['rate']}" for x in mv["back_flows"]) + ") "
                   "are its only rework, and none stands for reopening") if mv["back_flows"] else "the model has no flow back into the queue")
         + (f". The ticket system's reopen counter (not given to discovery) reads {mv['reopen_counter_per_day']['before']:.1f} a day "
            f"before, {mv['reopen_counter_per_day']['after']:.1f} after")},
        {"key": "queue", "claim": f"items waiting for triage {tg['queue']:+.0%}", "kind": "change", "intended": tg["queue"],
         "predicted": pr["queue"], "model": mv["queue"], "true": tr["queue"]["change"],
         "met_true": cut(tr["queue"]["change"], tg["queue"]), "met_model": cut(mv["queue"], tg["queue"]),
         "note": "through the model: measured against the model's counterfactual (the model without the agent, the same inputs)"},
        {"key": "hours_open", "claim": f"hours an item is open {tg['hours_open']:+.0%}", "kind": "change",
         "intended": tg["hours_open"], "predicted": pr["hours_open"], "model": mv["hours_open"], "true": tr["hours_open"]["change"],
         "met_true": cut(tr["hours_open"]["change"], tg["hours_open"]), "met_model": cut(mv["hours_open"], tg["hours_open"]),
         "note": "through the model: Little's law (items open ÷ new items an hour); true: each item's open hours in the log"},
    ]
    t_vals = {"queue": tr["queue"]["change"], "hours_open": tr["hours_open"]["change"],
              "reopens_extra": tr["reopens_per_day"]["extra"], "met": [c["met_true"] for c in claims]}
    m_vals = {"queue": mv["queue"], "hours_open": mv["hours_open"], "reopens_extra": None,
              "met": [c["met_model"] for c in claims]}
    judged = [c for c in claims if c["met_model"] is not None]
    return {"claims": claims, "word": word(t_vals, allow), "model_word": word(m_vals, allow),
            "n_met": sum(bool(c["met_true"]) for c in claims), "n": len(claims),
            "model_agrees": sum(bool(c["met_model"]) == bool(c["met_true"]) for c in judged), "model_judged": len(judged),
            "allowance": allow}


def _finite(x):
    return None if x is None or not math.isfinite(x) else x


def _clean(o):
    if isinstance(o, (float, np.floating)):
        return _finite(round(float(o), 5))
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    if isinstance(o, dict):
        return {k: _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    return o


# ---- the endpoints ----

def overview() -> dict:
    return _clean({"strategies": available(), "all_strategies": list(STRATEGIES), "variants": VARIANTS, "design": DESIGN,
                   "system": DES.SYSTEM, "every_hours": EVERY, "deploy_day": DEPLOY_H / 24, "days": HOURS / 24,
                   "command": COMMAND, "shifts": "4 engineers 08-20 on weekdays (5 in the 19-20 handover), 2 at weekends, 1 at night"})


def result(strategy: str, variant: str) -> dict:
    a = analysis(strategy, variant)
    return {**a, "verdict": _clean(verdicts(a))}


def _call(fn, *a, **k):
    try:
        return fn(*a, **k)
    except KeyError as e:
        raise HTTPException(404, f"unknown: {e}") from None
    except LookupError as e:
        raise HTTPException(409, str(e)) from None


@router.get(f"/{NAME}/overview")
def overview_route() -> dict:
    return _call(overview)


@router.get(f"/{NAME}/verify")
def verify_route(strategy: str = STRATEGIES[0], variant: str = "good") -> dict:
    return _call(result, strategy, variant)


if __name__ == "__main__":                                    # python -m sdlab.demos.agent_verify precompute [strategies]
    args = sys.argv[1:]
    if not args or args[0] not in ("precompute", "analyse"):
        sys.exit("usage: python -m sdlab.demos.agent_verify precompute [strategy ...] | analyse")
    if args[0] == "precompute":
        for row in precompute(tuple(args[1:]) or STRATEGIES):
            print(row["strategy"], f"{row['seconds']} s", len(row["flows"]), "flows")
            for f in row["flows"]:
                print("   ", ends(f), rate_text(f.get("rate")))
    for s in available():
        for v in VARIANTS:
            r = result(s, v)
            vd = r["verdict"]
            print(s, v, "true:", vd["word"], "model:", vd["model_word"], f"{vd['n_met']}/{vd['n']} met; model agrees {vd['model_agrees']}/{vd['model_judged']}")
            for c in vd["claims"]:
                print(f"    {c['claim']:<45} intended {c['intended']} predicted {c['predicted']} model {c['model']} true {c['true']}"
                      f" met_true {c['met_true']} met_model {c['met_model']}")
