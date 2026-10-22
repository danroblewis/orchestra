"""Demo 4, capacity projection (docs/demos/capacity.md; OPERATIONALIZATION.md ideas 23, 24), on ladder case
311-k8s-node-pool: traffic scaled up through a stored found model and through the true model, where each capacity
limit binds, the headroom left today, and whether the found model even has each limit (a min form) or only fits
the data because the data never reached it.

Also the shared pieces of demo 5 (risk_calendar.py): the case, its traffic series, the true model run with a given
traffic series, node count and injections (an in-memory copy), and a found model run free with the same series and
injections. Nothing here changes a case, a simulation, a strategy or the result store."""

from __future__ import annotations

import copy
import functools
import hashlib
import json
import math
import os
from pathlib import Path

import numpy as np
from fastapi import APIRouter, HTTPException

from ..ladder import sim as ladder_sim
from ..sdtruth import input_value
from . import engine as E

router = APIRouter()

CASE, VARIANT = "311-k8s-node-pool", "none-long"
STRATEGIES = ("milp", "combined2", "kalman_lna", "structures", "engine_forms")
STEPS_PER_DAY = 288                      # a 5-minute step (the kubernetes ladder); the traffic's daily sine has period 288
DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")   # step 1 is Monday 00:05 (the case: failures Mon/Wed/Fri 10:50 at 130, 706, 1282)
WEEK = 7 * STEPS_PER_DAY
SCALES = tuple(round(0.5 + 0.1 * i, 2) for i in range(21))  # 0.5x .. 2.5x
NODE_CHOICES = (3, 4, 5, 6)
POD_ROOM, POD_SERVES, HPA_MAX = 4, 40, 16
BIND_TOL = 0.01                          # a limit "binds" for headroom when it binds in at least 1% of the week's steps     # the true limits, used only to say where a limit binds on a run's levels


def cache_dir(name: str) -> Path:
    p = Path(os.environ.get("SDLAB_DEMOS_CACHE") or Path.home() / ".cache" / "sdlab" / "demos") / name
    p.mkdir(parents=True, exist_ok=True)
    return p


# ---------- the case, the found models, the two simulators ----------

@functools.lru_cache(maxsize=1)
def setup() -> dict:
    case, truth = E.case_and_truth(CASE, VARIANT)
    data = E.data_for(case, VARIANT)
    start = {s["id"]: float(s.get("initial") or 0) for s in truth["stocks"]}
    return {"case": case, "truth": truth, "data": data, "measured": list(data["levels"]), "start": start,
            "units": {s["id"]: s.get("unit") for s in truth["stocks"]}}


@functools.lru_cache(maxsize=8)
def found(strategy: str) -> dict:
    if strategy not in STRATEGIES:
        raise KeyError(strategy)
    r = E.stored_model(CASE, VARIANT, strategy)
    if r is None or not r.get("found"):
        raise LookupError(f"no stored passing result of {strategy} on {CASE} {VARIANT}")
    return r


def source(strategy: str) -> dict:
    r = found(strategy)
    return {"case": CASE, "variant": VARIANT, "strategy": strategy, "result": r.get("id"), "status": r.get("status"),
            "commit": (r.get("code_commit") or "")[:9], "at": r.get("at")}


@functools.lru_cache(maxsize=4)
def base_traffic(steps: int) -> tuple:
    """The case's traffic for steps 1..steps (its formula carried on past the case's own run)."""
    spec = setup()["truth"]["inputs"]["traffic"]
    return tuple(input_value(spec, float(t), t) for t in range(1, steps + 1))


def case_failures(steps: int) -> list[dict]:
    """The case's announced node failures (Mon, Wed, Fri at 10:50; the node back 30 steps later), every week."""
    week = setup()["truth"].get("injections") or []
    out = []
    for w in range(0, steps, WEEK):
        out += [{**j, "t": int(j["t"]) + w} for j in week if int(j["t"]) + w <= steps]
    return out


def run_true(traffic, nodes: int = 3, injections: list[dict] | None = None) -> dict:
    """The true model (an in-memory copy) with this traffic series, starting with `nodes` nodes: every stock's levels."""
    m = copy.deepcopy(setup()["truth"])
    m["inputs"] = {"traffic": {"values": [float(x) for x in traffic]}}
    m["injections"] = list(injections or [])
    for s in m["stocks"]:
        if s["id"] == "nodes":
            s["initial"] = int(nodes)
    r = E.run_truth(m, steps=len(traffic))
    return {k: np.asarray(v, float) for k, v in r["levels"].items()}


def run_found(flows: list[dict], traffic, nodes: int = 3, injections: list[dict] | None = None) -> dict:
    """A found model run free from the case's start levels (nodes set), with the same traffic and injections as the
    truth (each applied before its step, as the engine does). Its own (hidden) stocks start at 0."""
    b = setup()
    t = list(range(1, len(traffic) + 1))
    ids = E.found_ids(flows, b["measured"])
    mdl = ladder_sim.found_model(flows, ids, inputs={"t": t, "values": {"traffic": [float(x) for x in traffic]}})
    idx = {s: i for i, s in enumerate(ids)}
    st = {**b["start"], "nodes": float(nodes)}
    L = np.array([st.get(s, 0.0) if s in b["measured"] else 0.0 for s in ids], float)[:, None]
    by_t: dict[int, list] = {}
    for j in injections or []:
        if j["stock"] in idx:
            by_t.setdefault(int(j["t"]), []).append((idx[j["stock"]], float(j["amount"])))
    out = np.zeros((len(ids), len(t)))
    for i, ti in enumerate(t):
        if i == 0:                      # level at step 1 is the start (as the engine records step 1's level)
            out[:, 0] = L[:, 0]
            continue
        if ti in by_t:
            L = L.copy()
            for k, a in by_t[ti]:
                L[k, 0] = max(0.0, L[k, 0] + a)
        L = mdl.step(L, np.array([ti]))
        out[:, i] = L[:, 0]
    return {s: out[k] for s, k in idx.items()}


def _key(*parts) -> str:
    return hashlib.sha1(json.dumps([setup()["case"].get("hash"), *parts], default=str).encode()).hexdigest()[:16]


def _cached(name: str, key: str, fn):
    p = cache_dir(name) / f"{key}.json"
    if p.exists():
        try:
            return json.loads(p.read_text())
        except ValueError:
            pass
    v = fn()
    tmp = p.with_suffix(f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(v, separators=(",", ":")))
    tmp.replace(p)
    return v


def _r(x, nd=3):
    return None if x is None or not math.isfinite(float(x)) else round(float(x), nd)


# ---------- 4. capacity projection ----------

def _binds(L: dict) -> dict:
    """Where each limit binds on a run's levels, judged with the true limits (so found and true runs are judged
    alike): the serving limit (ready pods serve at most 40 requests a step), the node room (pods pending that cannot
    start: 4 pods a node), the autoscaler's maximum (16 pods wanted)."""
    q, ready, pend, nodes, cpu, des = (np.asarray(L[s], float) for s in ("queue", "ready", "pending", "nodes", "cpu", "desired"))
    serving = 0.6 * q > POD_SERVES * ready + 1e-6
    room = np.maximum(0.0, POD_ROOM * nodes - ready)
    no_room = (pend >= 0.5) & (room < 0.5 * pend - 1e-6)
    hpa = np.ceil(cpu / 192.5) > HPA_MAX
    return {"serving": serving, "room": no_room, "hpa": hpa | (des > HPA_MAX + 0.5)}


def _summary(L: dict, traffic: np.ndarray) -> dict:
    b = _binds(L)
    q = np.asarray(L["queue"], float)
    lost = 0.4 * float(np.sum(L["retries"]))                     # the true share of timed-out requests that give up
    return {"queue_peak": _r(q.max(), 1), "queue_mean": _r(q.mean(), 1), "pending_peak": _r(np.max(L["pending"]), 2),
            "ready_peak": _r(np.max(L["ready"]), 2), "desired_peak": _r(np.max(L["desired"]), 2),
            "lost_share": _r(lost / float(np.sum(traffic)), 4),
            "binds": {k: _r(float(v.mean()), 4) for k, v in b.items()}}


def _sweep_truth(nodes: int, failures: bool) -> list[dict]:
    def go():
        base = np.asarray(base_traffic(WEEK))
        inj = case_failures(WEEK) if failures else []
        return [_summary(run_true(k * base, nodes, inj), k * base) for k in SCALES]
    return _cached("capacity", _key("truth", nodes, failures, SCALES, WEEK), go)


def _sweep_found(strategy: str, nodes: int, failures: bool) -> list[dict]:
    r = found(strategy)

    def go():
        base = np.asarray(base_traffic(WEEK))
        inj = case_failures(WEEK) if failures else []
        return [_summary(run_found(r["found"], k * base, nodes, inj), k * base) for k in SCALES]
    return _cached("capacity", _key("found", strategy, r.get("id"), nodes, failures, SCALES, WEEK), go)


def _headroom(rows: list[dict]) -> dict:
    """The largest scale (of SCALES, from the bottom, without a gap) where the limit binds in under 1% of the week's
    steps (under about 1.7 hours of the week)."""
    out = {}
    for k in ("serving", "room", "hpa"):
        best = None
        for s, row in zip(SCALES, rows):
            if row["binds"][k] >= BIND_TOL:
                break
            best = s
        out[k] = best
    return out


CAPS = (  # the true model's capacity limits: its flow id, what it is in plain words, the condition on the data
    ("dispatched", "serving: each ready pod serves at most 40 requests a step", "serving"),
    ("started", "node room: a pending pod starts only while a node has room (4 pods a node)", "room"),
    ("hpa_up", "autoscaler maximum: at most 16 pods wanted", "hpa"),
)


@functools.lru_cache(maxsize=16)
def caps(strategy: str) -> list[dict]:
    """For each true limit: the true rate, the found flow between the same stocks and whether it has a min form,
    and how often the training data (the case's none-long run) reached the limit."""
    b = setup()
    flows = found(strategy)["found"]
    reached = _binds(b["data"]["all_levels"])
    out = []
    for fid, words, key in CAPS:
        tf = next(f for f in b["truth"]["flows"] if f["id"] == fid)
        ff = [f for f in flows if (f.get("from") or None) == (tf.get("from") or None) and (f.get("to") or None) == (tf.get("to") or None)]
        txt = "; ".join(_rate_text(f) for f in ff) or None
        has_min = any("min(" in str((f.get("rate") or {}).get("expr", "")).replace(" ", "") for f in ff)
        frac = float(reached[key].mean())
        if has_min and frac > 0:
            verdict, cls = "found, and the data reached it: projections past it are supported", "good"
        elif has_min:
            verdict, cls = "found, though the data never reached it", "warn"
        elif frac > 0:
            verdict, cls = "missed: the data reached it but the found model has no limit there", "bad"
        else:
            verdict, cls = "not in the found model: the data never reached it, so the model fits but is not proven past it", "warn"
        out.append({"flow": fid, "what": words, "ends": f"{tf.get('from') or 'outside'} → {tf.get('to') or 'outside'}",
                    "true_rate": (tf.get("rate") or {}).get("expr") if isinstance(tf.get("rate"), dict) else str(tf.get("rate")),
                    "found_rate": txt, "has_min": has_min, "reached": round(frac, 4), "verdict": verdict, "class": cls})
    return out


def _rate_text(f: dict) -> str:
    r = f.get("rate") or {}
    if r.get("form") == "expr":
        return E.NUM.sub(lambda m: f"{float(m.group(1)):.4g}", r.get("expr") or "")
    if r.get("form") == "proportional":
        return f"{float(r['k']):.4g} × {r['stock']}"
    if r.get("form") == "linear":
        return " + ".join([f"{float(r['c']):.4g}"] * bool(r.get("c")) + [f"{float(x['k']):.4g} × {x['stock']}" for x in r.get("terms") or []])
    if r.get("form") == "constant":
        return f"{float(r['value']):.4g}"
    return json.dumps(r)


def projection(strategy: str = "milp", nodes: int = 3, failures: bool = True) -> dict:
    if nodes not in NODE_CHOICES:
        raise KeyError(f"nodes {nodes}")
    tr = _sweep_truth(nodes, failures)
    fo = _sweep_found(strategy, nodes, failures)
    return {"source": source(strategy), "scales": list(SCALES), "nodes": nodes, "failures": failures, "steps": WEEK,
            "truth": tr, "found": fo, "headroom": {"truth": _headroom(tr), "found": _headroom(fo)}, "caps": caps(strategy),
            "strategies": list(STRATEGIES), "node_choices": list(NODE_CHOICES)}


@functools.lru_cache(maxsize=32)
def week(strategy: str, scale: float, nodes: int, failures: bool) -> dict:
    """One scale's week, found beside true: queue, pending, ready, desired (thinned to every 4th step)."""
    base = np.asarray(base_traffic(WEEK))
    inj = case_failures(WEEK) if failures else []
    tr = run_true(scale * base, nodes, inj)
    fo = run_found(found(strategy)["found"], scale * base, nodes, inj)
    every = 4
    stocks = {s: {"truth": [_r(x, 2) for x in tr[s][::every]], "found": [_r(x, 2) for x in fo[s][::every]], "unit": setup()["units"].get(s)}
              for s in ("queue", "pending", "ready", "desired")}
    return {"source": source(strategy), "scale": scale, "nodes": nodes, "t": list(range(1, WEEK + 1))[::every], "stocks": stocks,
            "failures": sorted({int(j["t"]) for j in inj if j["stock"] == "nodes" and j["amount"] < 0})}


def _http(fn, *a):
    try:
        return fn(*a)
    except KeyError as e:
        raise HTTPException(404, f"unknown: {e}") from None
    except LookupError as e:
        raise HTTPException(409, str(e)) from None


@router.get("/capacity/projection")
def projection_route(strategy: str = "milp", nodes: int = 3, failures: bool = True) -> dict:
    return _http(projection, strategy, nodes, failures)


@router.get("/capacity/week")
def week_route(strategy: str = "milp", scale: float = 2.0, nodes: int = 3, failures: bool = True) -> dict:
    if nodes not in NODE_CHOICES:
        raise HTTPException(404, f"unknown: nodes {nodes}")
    return _http(week, strategy, round(max(0.5, min(2.5, scale)), 2), nodes, failures)


if __name__ == "__main__":          # warm the cache: uv run python -m sdlab.demos.capacity
    for n in NODE_CHOICES:
        for fl in (True, False):
            for s in STRATEGIES:
                try:
                    projection(s, n, fl)
                except LookupError as e:
                    print(e)
            print("nodes", n, "failures", fl, "done", flush=True)
