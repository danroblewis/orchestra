"""Demo 6, metastability scan (docs/demos/metastability.md; OPERATIONALIZATION.md ideas 16, 20).

A metastable failure (Bronson et al., HotOS 2021) is a state a trigger (a load spike) pushes a system into and a
reinforcing loop (retries -> load -> timeouts -> retries) keeps it in after the trigger is gone. This demo sweeps
load spikes (extra requests a step for a number of steps) over a kubernetes case, through the case's true model and
through the stored passing found models of several strategies, and classifies each run: back to its normal queue
within a time, or not back within a day ("stuck"). The grid of answers is the safe-load envelope.

The spike is added to the traffic input of an in-memory copy of the true model (a pulse term) and the same series
is fed to each found model's free run. A "mechanism" may add one flow to both (the same flow in the truth's copy
and in each found model's copy): clients that retry harder, so the retry loop amplifies load. Nothing here changes
a case, a simulation, a strategy or the result store; answers are cached as JSON under CACHE.

Regenerate the cache: `uv run python -m sdlab.demos.metastability` (single-threaded; about a minute a case)."""

from __future__ import annotations

import copy
import functools
import json
import math
import os
from pathlib import Path

import numpy as np
from fastapi import APIRouter, HTTPException

from ..ladder import cases as casemod
from ..ladder import sim as ladder_sim
from ..ladder.diff import matched_names
from . import engine as E

router = APIRouter()
VERSION = 5                                                   # bump when an answer's meaning changes (cache key)
CACHE = Path(os.environ.get("SDLAB_DEMO_CACHE", Path.home() / ".cache" / "sdlab" / "demos")) / "metastability"

VARIANT = "none-long"
STRATEGIES = ("milp", "combined2", "kalman_lna", "engine_forms", "structures")
CASES = {
    "310-k8s-memory-oom": {
        "label": "310: one service, autoscaled to 16 pods",
        "about": ("The autoscaler can add pods up to 16 (640 requests a step of dispatch). In the measured run the "
                  "dispatch cap min(0.6 x queue, 40 x ready) never bound: at most 99% of the way."),
    },
    "311-k8s-node-pool": {
        "label": "311: the same service on a node pool of 3 nodes (12 pods)",
        "about": ("Three nodes hold 12 pods (480 requests a step of dispatch), less than the daily peak's 620 "
                  "requests, and a node fails three times a week, so the dispatch cap bound in the measured run."),
    },
}
HEIGHTS = (50, 100, 200, 400, 800, 1600)                      # extra requests a step (normal traffic 180-620)
WIDTHS = (3, 6, 12, 24, 48, 96)                               # steps of 5 minutes: 15 min to 8 h
STARTS = {"trough": 888, "ramp": 960, "peak": 1032}           # day 4 of the run (5-minute steps; 288 a day)
HORIZON = 288                                                  # steps watched after the longest spike ends (a day)
BANDS = ((12, "within 1 h"), (72, "within 6 h"), (HORIZON, "within a day"))
MECHANISMS = {                                                # k: extra requests per timed-out request (a second retry layer)
    "as-built": {"label": "as built (the case's true model)", "k": 0.0},
    "amplify-0.9": {"label": "a second retry layer: each timed-out request comes back 0.9 times", "k": 0.3},
    "amplify-1.05": {"label": "a second retry layer: each timed-out request comes back 1.05 times", "k": 0.45},
    "amplify-1.2": {"label": "a second retry layer: each timed-out request comes back 1.2 times", "k": 0.6},
}
TOL_REL, TOL_ABS = 0.05, 10.0                                 # "back to normal": within 5% or 10 requests of the no-spike run
HOLD = 24                                                     # ... for 2 hours on end


# ---- the models ----

@functools.lru_cache(maxsize=4)
def _setup(case_id: str) -> dict:
    case, truth = E.case_and_truth(case_id, VARIANT)
    d = E.data_for(case, VARIANT)
    base = E.run_truth(truth)
    return {"case": case, "truth": truth, "measured": list(d["levels"]), "t": list(d["t"]),
            "traffic": np.asarray(base["inputs"]["traffic"], float),
            "start": {s["id"]: float(s.get("initial") or 0) for s in truth["stocks"]},
            "injections": list(truth.get("injections") or []), "hash": casemod.case_hash(case)[:12]}


@functools.lru_cache(maxsize=16)
def _found(case_id: str, strategy: str) -> dict | None:
    r = E.stored_model(case_id, VARIANT, strategy)
    if r is None:
        return None
    flows = matched_names(r.get("found") or [], r.get("scores"))      # a matched hidden stock takes the truth's name
    return {"flows": flows, "source": {"strategy": strategy, "result": r.get("id"), "status": r.get("status"),
                                       "commit": (r.get("code_commit") or "")[:9], "at": r.get("at")},
            "cap": dispatch_cap(flows)}


def dispatch_cap(flows: list[dict]) -> str | None:
    """The found model's queue -> inflight rate when it is capped (a min(...) expression), else None."""
    for f in flows:
        if f.get("from") == "queue" and f.get("to") == "inflight":
            r = f.get("rate") or {}
            if r.get("form") == "expr" and "min(" in (r.get("expr") or ""):
                return r["expr"]
    return None


def dispatch_text(flows: list[dict]) -> str:
    parts = []
    for f in flows:
        if f.get("from") == "queue" and f.get("to") == "inflight":
            r = f.get("rate") or {}
            if r.get("form") == "expr":
                parts.append(_short_expr(r["expr"]))
            elif r.get("form") == "proportional":
                parts.append(f"{r['k']:.4g} × {r['stock']}")
            elif r.get("form") == "constant":
                if abs(float(r["value"])) > 1e-3:
                    parts.append(f"{float(r['value']):.4g}")
            else:
                parts.append(json.dumps(r))
    return " + ".join(parts) or "none"


def _short_expr(s: str) -> str:
    return E.NUM.sub(lambda m: f"{float(m.group(1)):.4g}", s)


def amplify_flow(k: float) -> dict:
    """The mechanism's extra flow: outside -> queue at k x retries (each request waiting to retry sends k more)."""
    return {"id": "amplified", "name": "amplified", "from": None, "to": "queue", "rate": {"form": "proportional", "stock": "retries", "k": float(k)}}


def spike_series(traffic: np.ndarray, t: list, start: int, height: float, width: int) -> np.ndarray:
    """The traffic series with `height` more requests a step for the `width` steps from step `start` (as the
    engine's pulse term {start, width} adds them: steps start .. start + width - 1)."""
    out = traffic.copy()
    tt = np.asarray(t)
    out[(tt >= start) & (tt < start + width)] += float(height)
    return out


def truth_run(case_id: str, mech: str, start: int, height: float, width: int, steps: int) -> dict:
    """The true model's noise-free run with the spike added to an in-memory copy's traffic input (and the
    mechanism's flow, if any): {stock: np.array}."""
    s = _setup(case_id)
    m = copy.deepcopy(s["truth"])
    m["steps"] = int(steps)
    if height and width:
        m["inputs"]["traffic"]["terms"].append({"fn": "pulse", "height": float(height), "start": int(start), "width": int(width)})
    k = MECHANISMS[mech]["k"]
    if k:
        m["flows"].append(amplify_flow(k))
    r = E.run_truth(m)
    return {k2: np.asarray(v, float) for k2, v in r["levels"].items()}


def found_runs(flows: list[dict], case_id: str, mech: str, series: np.ndarray, steps: int) -> dict:
    """The found model run free from the true initial levels, one column per traffic series (series: runs x
    steps), with the case's announced injections at their steps: {stock: array (steps, runs)}. The traffic input
    is carried as a stock the model reads and nothing moves, set to each run's value before each step."""
    s = _setup(case_id)
    k = MECHANISMS[mech]["k"]
    fl = list(flows) + ([amplify_flow(k)] if k else [])
    ids = E.found_ids(fl, s["measured"])
    ids = [x for x in ids if x != "traffic"] + ["traffic"]
    mdl = ladder_sim.found_model(fl, ids)
    n_runs = series.shape[0]
    L = np.array([s["start"].get(x, 0.0) for x in ids], float)[:, None].repeat(n_runs, 1)
    tr = ids.index("traffic")
    inj = {}
    for j in s["injections"]:
        if j.get("stock") in ids:
            inj.setdefault(int(j["t"]), []).append((ids.index(j["stock"]), float(j["amount"])))
    t = s["t"][:steps]
    out = np.empty((len(t), len(ids), n_runs))
    for i, ti in enumerate(t):                                # levels[i] are after step t[i] (t[0] = 1)
        for row, amount in inj.get(int(ti), []):
            L[row] = np.maximum(0.0, L[row] + amount)
        L[tr] = series[:, i]
        L = mdl.step(L, np.array([ti]))
        out[i] = L
    return {x: out[:, j, :] for j, x in enumerate(ids)}


# ---- classifying a run ----

def recovery(q: np.ndarray, base: np.ndarray, end_index: int) -> int | None:
    """Steps after the spike ends until the queue is back near its no-spike run (within tolerance) and stays
    there for HOLD steps; None when that never happens in the steps watched ("stuck")."""
    b, x = base[end_index:], q[end_index:]
    near = np.abs(x - b) <= np.maximum(TOL_REL * np.abs(b), TOL_ABS)
    run = 0
    for i in range(len(near) - 1, -1, -1):                  # run[i]: near from i on for how many steps
        run = run + 1 if near[i] else 0
        near[i] = run >= HOLD
    hit = np.flatnonzero(near)
    return int(hit[0]) if len(hit) else None


def band(rec: int | None) -> str:
    if rec is None:
        return "stuck"
    for lim, name in BANDS:
        if rec <= lim:
            return name
    return "stuck"


# ---- the scan ----

def _cache_path(key: str) -> Path:
    return CACHE / f"{key}.json"


def _cached(key: str, make):
    p = _cache_path(key)
    try:
        return json.loads(p.read_text())
    except (OSError, ValueError):
        pass
    got = make()
    try:
        CACHE.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(f".{os.getpid()}.tmp")
        tmp.write_text(json.dumps(got))
        tmp.replace(p)
    except OSError:
        pass
    return got


def _steps(start: int) -> int:
    return start + max(WIDTHS) + HORIZON


def _grid_from(qs: dict, base_q: np.ndarray, start: int, t: list) -> list[list[dict]]:
    """qs: {(h, w): queue array}; rows by width, columns by height."""
    tt = list(t)
    rows = []
    for w in WIDTHS:
        end = tt.index(start + w)                             # the first step without the spike
        row = []
        for h in HEIGHTS:
            q = qs[(h, w)]
            rec = recovery(q, base_q, end)
            row.append({"height": h, "width": w, "recovery": rec, "band": band(rec), "growing": rec is None and bool(q[-1] > q[end - 1]),
                        "peak_queue": round(float(q[tt.index(start):].max()), 1),
                        "end_queue": round(float(q[-1]), 1), "end_base": round(float(base_q[-1]), 1)})
        rows.append(row)
    return rows


def coverage(case_id: str) -> dict:
    """How close the measured data (what discovery saw) came to the dispatch cap: the largest 0.6 x queue /
    (40 x ready) over the run, and the steps where it was over 1 (the cap bound)."""
    s = _setup(case_id)
    d = E.data_for(s["case"], VARIANT)
    q, r = np.asarray(d["levels"]["queue"], float), np.asarray(d["levels"]["ready"], float)
    ratio = 0.6 * q / np.maximum(1e-9, 40 * r)
    return {"max_ratio": round(float(ratio.max()), 3), "bound_steps": int((ratio > 1).sum()), "steps": len(q),
            "max_queue": round(float(q.max()), 1)}


def truth_grid(case_id: str, mech: str, start: int) -> dict:
    s = _setup(case_id)
    key = f"truth-{case_id}-{VARIANT}-{s['hash']}-{mech}-{start}-v{VERSION}"

    def make():
        steps = _steps(start)
        t = s["t"][:steps]
        base = truth_run(case_id, mech, start, 0, 0, steps)
        qs = {(h, w): truth_run(case_id, mech, start, h, w, steps)["queue"] for w in WIDTHS for h in HEIGHTS}
        return {"grid": _grid_from(qs, base["queue"], start, t), "base_peak": round(float(base["queue"][t.index(start):].max()), 1),
                "base_stuck": _base_runaway(base["queue"], t, start)}
    return _cached(key, make)


def found_grid(case_id: str, strategy: str, mech: str, start: int) -> dict | None:
    f = _found(case_id, strategy)
    if f is None:
        return None
    s = _setup(case_id)
    key = f"found-{case_id}-{VARIANT}-{strategy}-{f['source']['result']}-{mech}-{start}-v{VERSION}"

    def make():
        steps = _steps(start)
        t = s["t"][:steps]
        cells = [(0, 0)] + [(h, w) for w in WIDTHS for h in HEIGHTS]
        series = np.stack([spike_series(s["traffic"][:steps], t, start, h, w) for h, w in cells])
        q = found_runs(f["flows"], case_id, mech, series, steps)["queue"]
        qs = {c: q[:, i] for i, c in enumerate(cells)}
        base = qs.pop((0, 0))
        return {"grid": _grid_from(qs, base, start, t), "base_peak": round(float(base[t.index(start):].max()), 1),
                "base_stuck": _base_runaway(base, t, start)}
    got = _cached(key, make)
    return {**got, "source": f["source"], "cap": f["cap"], "dispatch": dispatch_text(f["flows"])}


def _base_runaway(q: np.ndarray, t: list, start: int) -> bool:
    """The no-spike run itself never comes back: its queue at the end is far above its level before the spike
    window (the mechanism alone tipped it over)."""
    before = float(q[t.index(start) - 288: t.index(start)].max())
    return bool(q[-1] > 3 * max(before, 100.0))


def agreement(truth: dict, found: dict) -> dict:
    """Cells where the found model's answer has the truth's band; stuck cells it calls safe (dangerous) and safe
    cells it calls stuck; the recovery time's median error over the cells both call recovering."""
    same = missed = false = 0
    errs = []
    for tr, fr in zip(sum(truth["grid"], []), sum(found["grid"], [])):
        same += tr["band"] == fr["band"]
        missed += tr["band"] == "stuck" and fr["band"] != "stuck"
        false += tr["band"] != "stuck" and fr["band"] == "stuck"
        if tr["recovery"] is not None and fr["recovery"] is not None:
            errs.append(fr["recovery"] - tr["recovery"])
    n = len(sum(truth["grid"], []))
    return {"cells": n, "same_band": same, "missed_stuck": missed, "false_stuck": false,
            "median_recovery_error": float(np.median(errs)) if errs else None,
            "worst_underestimate": int(min(errs)) if errs else None}


@functools.lru_cache(maxsize=32)
def scan(case_id: str, mech: str = "as-built", start: str = "ramp") -> dict:
    if case_id not in CASES or mech not in MECHANISMS or start not in STARTS:
        raise KeyError(f"{case_id} {mech} {start}")
    T0 = STARTS[start]
    tg = truth_grid(case_id, mech, T0)
    found = []
    for st in STRATEGIES:
        fg = found_grid(case_id, st, mech, T0)
        if fg is None:
            found.append({"strategy": st, "missing": f"no stored passing result of {st} on {case_id} {VARIANT}"})
            continue
        found.append({"strategy": st, **fg, "agreement": agreement(tg, fg)})
    return {"case": case_id, "variant": VARIANT, "about": CASES[case_id], "mechanism": {"key": mech, **MECHANISMS[mech]},
            "start": {"key": start, "t": T0}, "heights": list(HEIGHTS), "widths": list(WIDTHS), "horizon": HORIZON,
            "tolerance": {"relative": TOL_REL, "absolute": TOL_ABS}, "bands": [b for _, b in BANDS] + ["stuck"],
            "truth": {**tg, "dispatch": dispatch_text(_setup(case_id)["truth"]["flows"])}, "found": found,
            "coverage": coverage(case_id), "loop": loop_gain()}


@functools.lru_cache(maxsize=64)
def example(case_id: str, strategy: str, mech: str, start: str, height: float, width: int) -> dict:
    """One spike, the truth's and one found model's runs beside their no-spike runs, thinned for the page."""
    if case_id not in CASES or mech not in MECHANISMS or start not in STARTS:
        raise KeyError(f"{case_id} {mech} {start}")
    f = _found(case_id, strategy)
    if f is None:
        raise LookupError(f"no stored passing result of {strategy} on {case_id} {VARIANT}")
    s = _setup(case_id)
    T0 = STARTS[start]
    steps = _steps(T0)
    t = s["t"][:steps]
    lo = T0 - 72
    tb, ts = truth_run(case_id, mech, T0, 0, 0, steps), truth_run(case_id, mech, T0, height, width, steps)
    series = np.stack([spike_series(s["traffic"][:steps], t, T0, 0, 0), spike_series(s["traffic"][:steps], t, T0, height, width)])
    fr = found_runs(f["flows"], case_id, mech, series, steps)
    end = t.index(T0 + int(width))
    out = {}
    for st in ("queue", "retries", "inflight", "ready"):
        if st in fr:
            out[st] = {"truth": _r(ts[st][lo:]), "truth_base": _r(tb[st][lo:]), "found": _r(fr[st][lo:, 1]), "found_base": _r(fr[st][lo:, 0])}
    if "nodes" in ts:
        out["ready"]["room"] = _r(4 * ts["nodes"][lo:])
    traffic = series[1][lo:]
    rec_t, rec_f = recovery(ts["queue"], tb["queue"], end), recovery(fr["queue"][:, 1], fr["queue"][:, 0], end)
    capped = 0.6 * ts["queue"] > 40 * ts["ready"] + 1e-9
    first_cap = next((t[i] for i in range(t.index(T0), len(t)) if capped[i]), None)
    return {"case": case_id, "strategy": strategy, "source": f["source"], "mechanism": {"key": mech, **MECHANISMS[mech]},
            "start": T0, "height": height, "width": width, "t": t[lo:], "traffic": _r(traffic), "stocks": out, "clip": CLIP,
            "truth": {"recovery": rec_t, "band": band(rec_t), "growing": rec_t is None and bool(ts["queue"][-1] > ts["queue"][end - 1]),
                      "capped_steps": int(capped[t.index(T0):].sum()), "first_capped": first_cap},
            "found": {"recovery": rec_f, "band": band(rec_f), "growing": rec_f is None and bool(fr["queue"][-1, 1] > fr["queue"][end - 1, 1]),
                      "cap": f["cap"], "dispatch": dispatch_text(f["flows"])}}


CLIP = 1e6                                                    # a runaway queue is drawn up to here


def _r(xs) -> list:
    return [None if not math.isfinite(float(x)) else round(min(float(x), CLIP), 2) for x in xs]


def loop_gain() -> dict:
    """The retry loop, read off the truth's numbers: per request waiting in the queue, the share timed out a step
    (0.08), the share of those retried (0.6) and given up (0.4). Below the cap the queue loses 0.6 + 0.08 x 0.4 =
    63.2% a step; at the cap it loses only the given-up share, 0.08 x 0.4 = 3.2% a step, and with an extra k x
    retries flowing in it loses 0.08 x (0.4 - k): it grows once k > 0.4 (the tipping point's condition)."""
    return {"timeout": 0.08, "retried": 0.6, "gave_up": 0.4, "loss_below_cap": 0.6 + 0.08 * 0.4, "loss_at_cap": 0.08 * 0.4,
            "tips_when_k_above": 0.4}


# ---- routes ----

def _http(fn, *a):
    try:
        return fn(*a)
    except KeyError as e:
        raise HTTPException(404, f"unknown: {e}") from None
    except LookupError as e:
        raise HTTPException(409, str(e)) from None


@router.get("/metastability/options")
def options() -> dict:
    return {"cases": CASES, "mechanisms": MECHANISMS, "starts": STARTS, "strategies": list(STRATEGIES), "variant": VARIANT,
            "heights": list(HEIGHTS), "widths": list(WIDTHS), "horizon": HORIZON, "loop": loop_gain()}


@router.get("/metastability/scan")
def scan_route(case: str = "310-k8s-memory-oom", mechanism: str = "as-built", start: str = "ramp") -> dict:
    return _http(scan, case, mechanism, start)


@router.get("/metastability/example")
def example_route(case: str = "310-k8s-memory-oom", strategy: str = "milp", mechanism: str = "as-built", start: str = "ramp",
                  height: float = 800, width: int = 48) -> dict:
    return _http(example, case, strategy, mechanism, start, float(height), int(width))


def precompute() -> None:
    for c in CASES:
        for m in MECHANISMS:
            for s in STARTS:
                r = scan(c, m, s)
                print(c, m, s, "truth stuck cells:", sum(x["band"] == "stuck" for x in sum(r["truth"]["grid"], [])),
                      {f["strategy"]: (f.get("agreement") or {}).get("same_band") for f in r["found"]}, flush=True)


if __name__ == "__main__":
    precompute()
