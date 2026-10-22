"""The model view shared by every demo (the user, 2026-10-22): for the found model a demo uses, a diagram of it, and
line charts over time of every measured stock (the data beside the model's prediction, one step ahead and run free)
and of every flow (the true amount per step, where the simulation records it, beside the found model's amount
between the same two stocks).

A demo names its model by a source: "ladder" (a stored result: case, variant, strategy, optional result id) is built
in; a demo with its own simulated system registers one with `register(name, fn)`, where fn(params) returns
{"title", "t", "levels", "inputs", "flows", "true_flows"?, "counters"?, "hidden"?, "source"?} (counters: the true flows'
amounts per step, entry i during the step that ends at levels[i]; true_flows: their {id, from, to})."""

from __future__ import annotations

import functools
import math

import numpy as np
from fastapi import APIRouter, HTTPException, Request

from . import engine as E

router = APIRouter()
SOURCES: dict = {}
POINTS = 500                                   # each series thinned to about this many points


def register(name: str, fn) -> None:
    SOURCES[name] = fn


def _ladder(params: dict) -> dict:
    case_id, variant, strategy = params.get("case"), params.get("variant"), params.get("strategy")
    if not (case_id and variant and strategy):
        raise KeyError("case, variant and strategy")
    case, truth = E.case_and_truth(case_id, variant)
    r = None
    if params.get("result"):
        from ..ladder import store
        r = store.get(int(params["result"]), found=True)
    r = r or E.stored_model(case_id, variant, strategy)
    if r is None:
        raise LookupError(f"no stored passing result of {strategy} on {case_id} {variant}")
    from ..ladder.diff import matched_names
    d = E.data_for(case, variant)
    return {"title": f"{strategy} on {case_id} {variant}", "t": list(d["t"]), "levels": d["levels"], "inputs": d.get("inputs") or {},
            "flows": matched_names(r.get("found") or [], r.get("scores")), "true_flows": truth["flows"], "counters": d.get("counters") or {},
            "hidden": {k: v for k, v in (d.get("all_levels") or {}).items() if k not in d["levels"]},
            "units": {s["id"]: s.get("unit") for s in truth["stocks"]},
            "source": {"strategy": strategy, "result": r.get("id"), "status": r.get("status"), "commit": (r.get("code_commit") or "")[:9],
                       "case": case_id, "variant": variant}}


register("ladder", _ladder)


def _thin(xs, every):
    return [None if (x is None or not math.isfinite(x)) else round(float(x), 4) for x in list(xs)[::every]]


def _ends(f: dict) -> tuple:
    return (f.get("from") or None, f.get("to") or None)


@functools.lru_cache(maxsize=64)
def _view(source: str, key: tuple) -> dict:
    if source not in SOURCES:
        raise KeyError(source)
    src = SOURCES[source](dict(key))
    t, levels, inputs, flows = list(src["t"]), src["levels"], src.get("inputs") or {}, src["flows"]
    measured = list(levels)
    n = len(t)
    # stocks: one step ahead (hidden stocks carried by the model) and free from the first measured levels
    o = E.one_step(flows, measured, t, levels, inputs)
    free = E.free_run(flows, measured, t, {s: levels[s][0] for s in measured}, inputs)
    ids = E.found_ids(flows, measured)
    hidden_found = [s for s in ids if s not in measured]
    # flows: the found model's amount in each step, read on the measured levels (and its own hidden stocks' carried levels)
    mdl = E._model(flows, ids, t, inputs)
    L = np.array([list(map(float, levels[s])) for s in measured] + [o["hidden"][h] for h in hidden_found])
    amounts = np.zeros((len(flows), n))
    if n > 1:
        got = mdl._amounts(L[:, :-1], np.asarray(t[1:], dtype=float))
        for k, a in enumerate(got):
            amounts[k, 1:] = np.asarray(a, dtype=float) * (1.0 / mdl.n_sub if mdl.n_sub > 1 else 1.0)
    pairs: dict = {}
    for k, f in enumerate(flows):
        pairs.setdefault(_ends(f), {"found": np.zeros(n), "true": None, "found_rates": [], "true_ids": []})
        pairs[_ends(f)]["found"] += amounts[k]
        pairs[_ends(f)]["found_rates"].append(f)
    counters = src.get("counters") or {}
    for f in src.get("true_flows") or []:
        if f["id"] in counters:
            p = pairs.setdefault(_ends(f), {"found": None, "true": None, "found_rates": [], "true_ids": []})
            p["true"] = (p["true"] if p["true"] is not None else np.zeros(n)) + np.asarray(counters[f["id"]], dtype=float)
            p["true_ids"].append(f["id"])
    every = max(1, n // POINTS)
    stocks = {s: {"data": _thin(levels[s], every), "one_step": _thin(o["predicted"][s], every), "free": _thin(free[s], every),
                  "unit": (src.get("units") or {}).get(s)} for s in measured}
    hidden = {h: {"found": _thin(o["hidden"][h], every), "true": _thin((src.get("hidden") or {}).get(h, []), every) if (src.get("hidden") or {}).get(h) else None}
              for h in hidden_found}

    def fit(a, b):                                          # relative rms of the found amounts against the true ones
        if a is None or b is None:
            return None
        a, b = np.asarray(a[1:]), np.asarray(b[1:])
        sc = float(np.sqrt(np.mean(b ** 2))) or 1.0
        return float(np.sqrt(np.mean((a - b) ** 2)) / sc)
    flow_rows = []
    for (a, b), p in pairs.items():
        flow_rows.append({"from": a, "to": b, "found": None if p["found"] is None or not p["found_rates"] else _thin(p["found"], every),
                          "true": None if p["true"] is None else _thin(p["true"], every), "true_ids": p["true_ids"],
                          "error": fit(p["found"] if p["found_rates"] else None, p["true"]),
                          "status": "both" if p["found_rates"] and p["true"] is not None else "found only" if p["found_rates"] else "true only"})
    flow_rows.sort(key=lambda r: (r["status"] != "both", -(r["error"] or 0)))
    err = {s: float(np.nanmean(np.abs(np.asarray(o["predicted"][s][1:], float) - np.asarray(levels[s][1:], float))) /
                    (float(np.nanstd(levels[s])) or 1.0)) for s in measured}
    return {"title": src.get("title"), "source": src.get("source"), "t": t[::every], "stocks": stocks, "hidden": hidden, "flows": flow_rows,
            "one_step_error": err, "diagram": {"stocks": [{"id": s, "hidden": False} for s in measured] + [{"id": h, "hidden": True} for h in hidden_found],
                                                "flows": flows}}


@router.get("/view/data")
def view(request: Request, source: str = "ladder") -> dict:
    params = tuple(sorted((k, v) for k, v in request.query_params.items() if k != "source"))
    try:
        return _view(source, params)
    except KeyError as e:
        raise HTTPException(404, f"unknown: {e}") from None
    except LookupError as e:
        raise HTTPException(409, str(e)) from None
