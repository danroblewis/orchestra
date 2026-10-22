"""Demo 12, blast radius across services (docs/demos/blast-radius.md; ideas 22 and 33 in OPERATIONALIZATION.md).

One service of a multi-service kubernetes case (314: a chain of three, 315: fan-out) is slowed from step T: its pods
pick up work more slowly (dispatch) or its requests take longer to finish (completion). The same slowdown is applied
to an in-memory copy of the case's true model and to a stored found model (a passing result), each beside its own
unchanged run. For every stock: how far it moved away from where it would have been, and when that first passed 5%;
for every service: the largest of its stocks. The ranking slows each service in turn and adds up how much the others
move (dependency risk). Nothing here changes a case, a strategy or the result store."""

from __future__ import annotations

import functools
import math
import re

import numpy as np
from fastapi import APIRouter, HTTPException

from ..ladder import store
from . import engine as E

router = APIRouter()

CASES = {
    "fan-out": {"case": "315-k8s-fan-out", "title": "Fan-out: frontend calls catalog and cart; catalog calls pricing (ladder case 315)"},
    "chain": {"case": "314-k8s-chain-of-three", "title": "A chain of three: frontend calls catalog, catalog calls pricing (ladder case 314)"},
}
VARIANTS = ("none-long", "counts-long")
STRATEGIES = ("kalman_lna", "engine_forms", "milp", "structures", "sindy", "z3robust", "lna_stack")
KINDS = {
    "dispatch": {"from": "queue", "to": "inflight", "label": "pods pick up waiting requests more slowly (dispatch rate ×)"},
    "completion": {"from": "inflight", "to": "responses_total", "label": "requests take longer to finish (completion rate ×)"},
}
MOVED = 0.05            # a stock "moved" when it is more than 5% away from where it would have been without the fault
STEP_MIN = 5            # the kubernetes ladder's step is 5 minutes
NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def service(stock: str) -> str:
    return stock.split("_")[0]


# ---- the models ----

@functools.lru_cache(maxsize=4)
def _case(key: str) -> dict:
    if key not in CASES:
        raise KeyError(key)
    case, truth = E.case_and_truth(CASES[key]["case"], "none-long")
    stocks = [s["id"] for s in truth["stocks"]]
    services = list(dict.fromkeys(service(s) for s in stocks))
    counters = {s["id"] for s in truth["stocks"] if s.get("final") or s["id"].endswith("_total")}
    return {"case": case, "truth": truth, "stocks": stocks, "services": services, "counters": counters}


@functools.lru_cache(maxsize=32)
def _found(key: str, variant: str, strategy: str) -> dict | None:
    c = _case(key)
    if variant not in VARIANTS or strategy not in STRATEGIES:
        raise KeyError(f"{variant} {strategy}")
    r = _stored(CASES[key]["case"], variant, strategy)
    if r is None or not r.get("found"):
        return None
    return {"id": r.get("id"), "status": r.get("status"), "commit": (r.get("code_commit") or "")[:9], "at": r.get("at"),
            "flows": r["found"], "stocks": c["stocks"]}


@functools.lru_cache(maxsize=8)
def _stored(case_id: str, variant: str, strategy: str) -> dict | None:
    """engine.stored_model, with its fallback (the newest passing result when the latest is not one) done here:
    engine's fallback calls store.connect() without `with` and fails (reported for engine.py)."""
    rows = store.latest(case_id, variant, strategy, found=True)
    r = next((x for x in rows if x.get("status") in E.GOOD), None)
    if r is not None:
        return r
    with store.connect() as con:
        got = con.execute("SELECT id FROM results WHERE case_id = ? AND variant = ? AND strategy = ? AND status IN"
                          " ('pass', 'equivalent', 'fits') ORDER BY id DESC LIMIT 1", (case_id, variant, strategy)).fetchone()
    return store.get(int(got[0]), found=True) if got else None


@functools.lru_cache(maxsize=8)
def _truth_base(key: str) -> dict:
    return E.run_truth(_case(key)["truth"])


def _found_run(key: str, flows: list[dict], edited: list[dict] | None, T: int) -> dict:
    """The found model run free from the true levels at the first step (the same start as the truth's run), with the
    flows changed to `edited` from step T on."""
    base = _truth_base(key)
    t, inputs = base["t"], base["inputs"]
    meas = _case(key)["stocks"]
    start = {s: base["levels"][s][0] for s in meas}
    if edited is None:
        return E.free_run(flows, meas, t, start, inputs)
    i0 = max(0, t.index(T) - 1) if T in t else len(t) - 1
    a = E.free_run(flows, meas, t[: i0 + 1], start, {k: v[: i0 + 1] for k, v in inputs.items()})
    b = E.free_run(edited, meas, t[i0:], {s: v[-1] for s, v in a.items()}, {k: v[i0:] for k, v in inputs.items()})
    return {s: a[s] + b[s][1:] for s in a}


@functools.lru_cache(maxsize=8)
def _found_base(key: str, variant: str, strategy: str) -> dict:
    return _found_run(key, _found(key, variant, strategy)["flows"], None, 0)


# ---- the fault: the same slowdown on the true flow and on the found flows between the same stocks ----

def _ends(svc: str, kind: str) -> tuple[str, str]:
    k = KINDS[kind]
    return f"{svc}_{k['from']}", f"{svc}_{k['to']}"


def _true_change(key: str, svc: str, kind: str, factor: float, T: int) -> dict | None:
    a, b = _ends(svc, kind)
    tf = E.true_flow_between(_case(key)["truth"], a, b)
    if tf is None:
        return None
    rate = E.scale_true_rate(tf["rate"], factor)
    return None if rate is None else {"t": T, "flow": tf["id"], "rate": rate, "label": f"{svc} {kind} × {factor:g}"}


def _found_edit(flows: list[dict], svc: str, kind: str, factor: float) -> tuple[list[dict] | None, int]:
    """The found flows with every flow between the fault's two stocks scaled by factor, and how many there were."""
    a, b = _ends(svc, kind)
    out, hit = [], 0
    for f in flows:
        if f.get("from") == a and f.get("to") == b:
            r = E.scale_true_rate(f.get("rate"), factor)
            if r is not None:
                f = {**f, "rate": r}
                hit += 1
        out.append(f)
    return (out if hit else None), hit


# ---- how far each stock moved, and when ----

def _signal(key: str, s: str, xs) -> np.ndarray:
    v = np.asarray(xs, float)
    return np.diff(v, prepend=v[0]) if s in _case(key)["counters"] else v          # a counter: its per-step increase


def _impact(key: str, t: list, base: dict, changed: dict, T: int) -> dict:
    """{stock: {peak, sign, arrival, after, lasting}}: the peak of |changed - base| / typical level from T on, the
    first step it passed MOVED, and whether it is still past MOVED at the end."""
    out = {}
    tt = np.asarray(t)
    w = tt >= T
    for s in _case(key)["stocks"]:
        b, c = _signal(key, s, base[s]), _signal(key, s, changed[s])
        scale = max(float(np.mean(np.abs(b[w]))), 1e-9)
        r = (c - b) / scale
        r[~w] = 0.0
        k = int(np.argmax(np.abs(r)))
        hit = np.flatnonzero(np.abs(r) > MOVED)
        out[s] = {"peak": float(abs(r[k])), "sign": int(np.sign(r[k])), "peak_at": int(tt[k]),
                  "arrival": int(tt[hit[0]]) if len(hit) else None, "after": int(tt[hit[0]] - T) if len(hit) else None,
                  "lasting": bool(abs(r[-1]) > MOVED)}
    return out


def _by_service(key: str, imp: dict) -> dict:
    out = {}
    for svc in _case(key)["services"]:
        rows = {s: v for s, v in imp.items() if service(s) == svc}
        top = max(rows, key=lambda s: rows[s]["peak"])
        arr = [v["after"] for v in rows.values() if v["after"] is not None]
        out[svc] = {"peak": rows[top]["peak"], "stock": top, "after": min(arr) if arr else None,
                    "reached": bool(arr), "lasting": any(v["lasting"] for v in rows.values())}
    return out


# ---- the call graph a model implies: service X -> Y when a flow into (or out of) Y reads or moves X's stocks ----

def _reads(rate) -> set[str]:
    if isinstance(rate, dict):
        got = set()
        for k, v in rate.items():
            if k == "stock" and isinstance(v, str):
                got.add(v)
            elif k == "expr" and isinstance(v, str):
                got |= set(NAME.findall(v))
            elif isinstance(v, (dict, list)):
                got |= _reads(v)
        return got
    if isinstance(rate, list):
        return set().union(*[_reads(x) for x in rate]) if rate else set()
    if isinstance(rate, str):
        return set(NAME.findall(rate))
    return set()


def graph(flows: list[dict], stocks: list[str]) -> list[list[str]]:
    known = set(stocks)
    edges = set()
    for f in flows:
        target = f.get("to") or f.get("from")
        if target not in known:
            continue
        src = {s for s in _reads(f.get("rate")) | _reads(f.get("effects") or []) if s in known}
        if f.get("from") in known:
            src.add(f["from"])
        for s in src:
            if service(s) != service(target):
                edges.add((service(s), service(target)))
    return sorted([a, b] for a, b in edges)


def _layout(services: list[str], edges: list[list[str]]) -> dict:
    """Columns by the longest call path from a service nobody calls (the true graph, so both drawings line up)."""
    depth = {s: 0 for s in services}
    for _ in services:
        for a, b in edges:
            depth[b] = max(depth[b], depth[a] + 1)
    cols: dict[int, list[str]] = {}
    for s in services:
        cols.setdefault(depth[s], []).append(s)
    return {s: {"col": depth[s], "row": cols[depth[s]].index(s), "rows": len(cols[depth[s]])} for s in services}


# ---- the endpoints ----

def _source(key: str, variant: str, strategy: str, f: dict) -> dict:
    return {"case": CASES[key]["case"], "variant": variant, "strategy": strategy, "result": f["id"], "status": f["status"],
            "commit": f["commit"], "at": f["at"]}


@functools.lru_cache(maxsize=4)
def setup() -> dict:
    out = []
    for key, c in CASES.items():
        k = _case(key)
        true_edges = graph(k["truth"]["flows"], k["stocks"])
        cells = []
        for v in VARIANTS:
            for s in STRATEGIES:
                f = _found(key, v, s)
                if f is None:
                    continue
                fe = graph(f["flows"], k["stocks"])
                cells.append({"variant": v, "strategy": s, "result": f["id"], "status": f["status"], "commit": f["commit"],
                              "false_links": [e for e in fe if e not in true_edges], "missed_links": [e for e in true_edges if e not in fe]})
        out.append({"key": key, "case": c["case"], "title": c["title"], "services": k["services"], "edges": true_edges,
                    "layout": _layout(k["services"], true_edges), "steps": len(_truth_base(key)["t"]), "models": cells})
    return {"cases": out, "kinds": {k: v["label"] for k, v in KINDS.items()}, "moved": MOVED, "step_minutes": STEP_MIN}


def _check(key, variant, strategy, svc, kind, factor, T) -> dict:
    c = _case(key)
    if svc not in c["services"] or kind not in KINDS:
        raise KeyError(f"{svc} {kind}")
    if not (0.0 <= factor <= 10.0):
        raise ValueError("factor must be between 0 and 10")
    n = len(_truth_base(key)["t"])
    if not (10 <= T <= n - 10):
        raise ValueError(f"t must be between 10 and {n - 10}")
    f = _found(key, variant, strategy)
    if f is None:
        raise LookupError(f"no stored passing result of {strategy} on {CASES[key]['case']} {variant}")
    return f


def _round(xs, nd=3):
    return [None if not math.isfinite(x) else round(float(x), nd) for x in xs]


@functools.lru_cache(maxsize=64)
def spread(key: str, variant: str, strategy: str, svc: str, kind: str, factor: float = 0.5, T: int = 1000) -> dict:
    f = _check(key, variant, strategy, svc, kind, factor, T)
    c = _case(key)
    tb = _truth_base(key)
    t = tb["t"]
    tc = _true_change(key, svc, kind, factor, T)
    tr = E.run_truth(c["truth"], change=tc)["levels"] if tc else None
    fb = _found_base(key, variant, strategy)
    edited, hits = _found_edit(f["flows"], svc, kind, factor)
    fr = _found_run(key, f["flows"], edited, T) if edited else None
    t_imp = _impact(key, t, tb["levels"], tr, T) if tr else None
    f_imp = _impact(key, t, fb, fr, T) if fr else None
    lo = max(0, t.index(T) - 200)
    every = max(1, (len(t) - lo) // 400)
    sl = slice(lo, None, every)
    def sig(s, xs):
        return _round(_signal(key, s, xs)[sl].tolist())
    series = {s: {"counter": s in c["counters"], "true_base": sig(s, tb["levels"][s]), "true": sig(s, tr[s]) if tr else None,
                  "found_base": sig(s, fb[s]), "found": sig(s, fr[s]) if fr else None} for s in c["stocks"]}
    t_svc = _by_service(key, t_imp) if t_imp else None
    f_svc = _by_service(key, f_imp) if f_imp else None
    true_edges, found_edges = graph(c["truth"]["flows"], c["stocks"]), graph(f["flows"], c["stocks"])
    return {"source": _source(key, variant, strategy, f), "fault": {"service": svc, "kind": kind, "label": KINDS[kind]["label"],
            "factor": factor, "t": T, "ends": list(_ends(svc, kind)), "true_flow": tc and tc["flow"], "found_flows": hits},
            "t": t[sl], "series": series, "stocks": {"true": t_imp, "found": f_imp}, "services": {"true": t_svc, "found": f_svc},
            "edges": {"true": true_edges, "found": found_edges}, "layout": _layout(c["services"], true_edges),
            "differences": _differences(c["services"], svc, t_svc, f_svc, true_edges, found_edges),
            "moved": MOVED, "step_minutes": STEP_MIN}


def _differences(services, svc, t_svc, f_svc, true_edges, found_edges) -> list[dict]:
    """Where the found model's spread differs from the truth's, in plain words: {kind: missed | false | timing |
    size, about: link | service, service, text}."""
    out = []
    for a, b in found_edges:
        if [a, b] not in true_edges:
            out.append({"kind": "false", "about": "link", "service": b, "text": f"the found model has a link {a} → {b} that the true model does not have"})
    for a, b in true_edges:
        if [a, b] not in found_edges:
            out.append({"kind": "missed", "about": "link", "service": b, "text": f"the found model misses the link {a} → {b}"})
    if t_svc is None or f_svc is None:
        return out
    for s in services:
        tv, fv = t_svc[s], f_svc[s]
        if tv["reached"] and not fv["reached"]:
            out.append({"kind": "missed", "about": "service", "service": s, "text": f"{s} moves {100 * tv['peak']:.0f}% in the truth; the found model says it does not move"})
        elif fv["reached"] and not tv["reached"]:
            out.append({"kind": "false", "about": "service", "service": s, "text": f"the found model says {s} moves {100 * fv['peak']:.0f}%; in the truth it does not move"})
        elif tv["reached"] and fv["reached"]:
            if tv["after"] != fv["after"] and abs(tv["after"] - fv["after"]) > 1:
                out.append({"kind": "timing", "about": "service", "service": s, "text": f"{s}: the found model says the impact arrives after {fv['after']} steps, the truth after {tv['after']}"})
            rel = abs(fv["peak"] - tv["peak"]) / max(tv["peak"], 1e-9)
            if rel > 0.2:
                out.append({"kind": "size", "about": "service", "service": s, "text": f"{s}: the found model's peak move is {100 * fv['peak']:.0f}%, the truth's {100 * tv['peak']:.0f}%"})
    return out


@functools.lru_cache(maxsize=32)
def ranking(key: str, variant: str, strategy: str, kind: str = "completion", factor: float = 0.5, T: int = 1000) -> dict:
    """Dependency risk: each service slowed in turn; its spread is the sum of the other services' peak moves (and how
    many of them moved past MOVED), found vs true; ranked by the true spread."""
    c = _case(key)
    rows = []
    for svc in c["services"]:
        r = spread(key, variant, strategy, svc, kind, factor, T)
        row = {"service": svc}
        for side in ("true", "found"):
            sv = r["services"][side]
            if sv is None:
                row[side] = None
                continue
            others = {s: v for s, v in sv.items() if s != svc}
            row[side] = {"spread": sum(v["peak"] for v in others.values()), "reached": sorted(s for s, v in others.items() if v["reached"]),
                         "own": sv[svc]["peak"]}
        rows.append(row)
    for side in ("true", "found"):
        ok = [x for x in rows if x[side] is not None]
        for x in ok:                                                  # ties (services that spread nothing) share a rank
            x[side]["rank"] = 1 + sum(y[side]["spread"] > x[side]["spread"] + 1e-6 for y in ok)
    rows.sort(key=lambda x: (x["true"]["rank"] if x["true"] else 99))
    same = all(x["true"] and x["found"] and x["true"]["rank"] == x["found"]["rank"] for x in rows)
    same_reach = all(x["true"] and x["found"] and x["true"]["reached"] == x["found"]["reached"] for x in rows)
    f = _found(key, variant, strategy)
    return {"source": _source(key, variant, strategy, f), "kind": kind, "label": KINDS[kind]["label"], "factor": factor, "t": T,
            "rows": rows, "same_order": same, "same_reach": same_reach, "moved": MOVED}


def _http(fn, *a):
    try:
        return fn(*a)
    except KeyError as e:
        raise HTTPException(404, f"unknown: {e}") from None
    except LookupError as e:
        raise HTTPException(409, str(e)) from None
    except ValueError as e:
        raise HTTPException(422, str(e)) from None


@router.get("/blast-radius/setup")
def setup_route() -> dict:
    return _http(setup)


@router.get("/blast-radius/spread")
def spread_route(case: str = "fan-out", variant: str = "none-long", strategy: str = "kalman_lna", service: str = "catalog",
                 kind: str = "completion", factor: float = 0.5, t: int = 1000) -> dict:
    return _http(spread, case, variant, strategy, service, kind, round(float(factor), 4), int(t))


@router.get("/blast-radius/ranking")
def ranking_route(case: str = "fan-out", variant: str = "none-long", strategy: str = "kalman_lna", kind: str = "completion",
                  factor: float = 0.5, t: int = 1000) -> dict:
    return _http(ranking, case, variant, strategy, kind, round(float(factor), 4), int(t))
